"""Calibration API endpoints — database-backed, with auto-calibration"""
import time
import json
import base64
import logging
import cv2
import numpy as np
from fastapi import APIRouter
from app import calibration, database
from app.arm_client import ArmClient
from app.camera import Camera
from app.worker_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calibration", tags=["calibration"])


@router.get("/status")
async def calibration_status():
    return await calibration.get_all_calibrations()


@router.get("/{station_id}")
async def get_station_calibration(station_id: int):
    cal = await calibration.get_calibration(station_id)
    if not cal:
        return {"error": "Not calibrated", "station_id": station_id}
    return {"station_id": station_id, "calibrated": True, **cal}


@router.post("/convert")
async def convert_pixel_to_arm(data: dict):
    station_id = data["station_id"]
    if not await calibration.is_calibrated(station_id):
        return {"error": "Station %d not calibrated" % station_id}
    ax, ay = await calibration.pixel_to_arm(
        station_id, data["px"], data["py"],
        data["cur_arm_x"], data["cur_arm_y"]
    )
    return {"arm_x": ax, "arm_y": ay}


@router.post("/save")
async def save_calibration_data(data: dict):
    station_id = data.pop("station_id")
    await calibration.save_calibration(station_id, data)
    return {"success": True}


@router.post("/auto-calibrate")
async def auto_calibrate(data: dict):
    """3-point auto calibration.
    Body: {station_id, arm_id, start_x, start_y, ref_arm_x, ref_arm_y, template_b64}

    Process:
    1. Move to A=(start_x, start_y), take photo, find template pixel position
    2. Move to B=A+(0,10), take photo, find template pixel position
    3. Move to C=A+(10,0), take photo, find template pixel position
    4. Compute scale, rotation, affine matrix from pixel displacements
    5. Save to calibrations table
    """
    station_id = data["station_id"]
    arm_id = data["arm_id"]
    start_x = float(data["start_x"])
    start_y = float(data["start_y"])
    ref_arm_x = float(data["ref_arm_x"])
    ref_arm_y = float(data["ref_arm_y"])
    template_b64 = data.get("template_b64")
    step_mm = float(data.get("step_mm", 10))

    worker = manager.get_worker(arm_id)
    if not worker:
        return {"error": "No worker for arm %d" % arm_id}

    arm = worker.arm_client
    cam = worker.camera

    if not arm.is_connected():
        return {"error": "Arm not connected. Connect arm first."}

    cam.stream_start()
    time.sleep(0.5)

    template = None
    if template_b64:
        tpl_bytes = base64.b64decode(template_b64)
        tpl_arr = np.frombuffer(tpl_bytes, dtype=np.uint8)
        template = cv2.imdecode(tpl_arr, cv2.IMREAD_COLOR)

    positions = [
        ("A", start_x, start_y),
        ("B", start_x, start_y + step_mm),
        ("C", start_x + step_mm, start_y),
    ]

    photos = []
    pixel_positions = []

    raw_height = None
    for label, px, py in positions:
        arm.move(px, py)
        time.sleep(1)
        frame = cam.capture_frame()
        if frame is None:
            return {"error": "Camera capture failed at position %s" % label}
        if raw_height is None:
            raw_height = frame.shape[0]   # raw (unrotated) image height = 480
        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        photos.append(rotated)

        if template is not None:
            found = _find_template(rotated, template)
            if found:
                pixel_positions.append(found)
            else:
                pixel_positions.append(None)
        else:
            pixel_positions.append(None)

    has_all = all(p is not None for p in pixel_positions)

    if not has_all:
        photos_b64 = []
        for img in photos:
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            photos_b64.append(base64.b64encode(buf).decode("utf-8"))
        return {
            "status": "need_manual",
            "message": "Template matching failed. Please click the reference point in each photo.",
            "photos": photos_b64,
            "pixel_positions": pixel_positions,
        }

    result = _compute_calibration(
        pixel_positions, positions, ref_arm_x, ref_arm_y, step_mm,
        raw_height
    )

    await calibration.save_calibration(station_id, result)

    return {"status": "ok", **result}


@router.post("/auto-calibrate/manual-points")
async def auto_calibrate_manual(data: dict):
    """Complete calibration using manually clicked pixel positions.
    Body: {station_id, points: [[px_a,py_a],[px_b,py_b],[px_c,py_c]],
           start_x, start_y, ref_arm_x, ref_arm_y, step_mm, raw_height}
    """
    station_id = data["station_id"]
    points = data["points"]
    start_x = float(data["start_x"])
    start_y = float(data["start_y"])
    step_mm = float(data.get("step_mm", 10))
    ref_arm_x = float(data["ref_arm_x"])
    ref_arm_y = float(data["ref_arm_y"])
    raw_height = int(data.get("raw_height", 480))

    pixel_positions = [(p[0], p[1]) for p in points]
    positions = [
        ("A", start_x, start_y),
        ("B", start_x, start_y + step_mm),
        ("C", start_x + step_mm, start_y),
    ]

    result = _compute_calibration(pixel_positions, positions, ref_arm_x, ref_arm_y, step_mm, raw_height)
    await calibration.save_calibration(station_id, result)
    return {"status": "ok", **result}


def _find_template(image, template):
    """Find template in image using OpenCV matchTemplate. Returns (x,y) center or None."""
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < 0.5:
        return None
    th, tw = template.shape[:2]
    cx = max_loc[0] + tw / 2
    cy = max_loc[1] + th / 2
    return (cx, cy)


def _compute_calibration(pixel_positions, arm_positions, ref_arm_x, ref_arm_y,
                         step_mm, raw_height):
    """Compute affine matrix from 3 pixel positions + known arm movements.

    Solves the linear system directly (no angle-based approximation).

    pixel_positions: [(px_a, py_a), (px_b, py_b), (px_c, py_c)] on ROTATED image
    arm_positions: [("A", ax, ay), ("B", bx, by), ("C", cx, cy)]
    ref_arm_x, ref_arm_y: known arm coordinates for the reference icon at pixel A
    raw_height: height of the ORIGINAL (unrotated) camera frame (e.g. 480)

    Matrix M maps RAW pixel coords to arm coords (consistent with pixel_to_arm):
      raw_x = rotated_y,  raw_y = (raw_height-1) - rotated_x
      arm = M @ [raw_x, raw_y, 1]

    We require:
      M2 @ dr_y = [0, step_mm]   (arm Y increases, arm X unchanged when moving to B)
      M2 @ dr_x = [step_mm, 0]   (arm X increases, arm Y unchanged when moving to C)
    where dr_y, dr_x are raw-space displacements.
    """
    pa = np.array(pixel_positions[0], dtype=float)
    pb = np.array(pixel_positions[1], dtype=float)
    pc = np.array(pixel_positions[2], dtype=float)

    # Convert rotated pixel positions to raw pixel coordinates
    # raw_x = rotated_y,  raw_y = (H-1) - rotated_x
    H = raw_height - 1

    def to_raw(p):
        return np.array([p[1], H - p[0]])

    ra = to_raw(pa)
    rb = to_raw(pb)
    rc = to_raw(pc)

    # Raw-space displacements when arm moved +Y and +X respectively
    dr_y = rb - ra
    dr_x = rc - ra

    # Solve: M2 @ [dr_y | dr_x] = [[0, step], [step, 0]]
    A = np.column_stack([dr_y, dr_x])
    det = np.linalg.det(A)
    if abs(det) < 1e-6:
        raise ValueError(
            "Calibration points appear collinear (det=%.2e). "
            "Choose points that form a larger triangle." % det
        )

    rhs = np.array([[0.0, -step_mm], [-step_mm, 0.0]])
    M2 = rhs @ np.linalg.inv(A)

    # Translation: at raw position ra the arm should reach (ref_arm_x, ref_arm_y)
    t = np.array([ref_arm_x, ref_arm_y]) - M2 @ ra

    M = [
        [float(M2[0, 0]), float(M2[0, 1]), float(t[0])],
        [float(M2[1, 0]), float(M2[1, 1]), float(t[1])],
    ]

    scale_y = step_mm / np.linalg.norm(rb - ra)
    scale_x = step_mm / np.linalg.norm(rc - ra)
    scale = (scale_x + scale_y) / 2

    # rotation: angle of the first column of M2 in arm space
    rotation_deg = float(np.degrees(np.arctan2(M2[1, 0], M2[0, 0])))

    return {
        "transform_matrix": M,
        "camera_park_pos": [arm_positions[0][1], arm_positions[0][2]],
        "scale_mm_per_pixel": round(scale, 6),
        "rotation_degrees": round(rotation_deg, 2),
        "raw_height": raw_height,
    }
