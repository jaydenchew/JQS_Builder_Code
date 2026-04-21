"""Calibration API endpoints — fiducial card based.

Replaces the old 3-point auto-calibration (which suffered from frequent
collinear failures, weak template matches, and no quality metric). New flow:

  1. User places calibration card with its printed axes parallel to arm X/Y
  2. UI captures one photo via /capture-for-calibration
  3. User clicks the 4 corners of the inner black square (order: TL, TR, BR, BL)
  4. User jogs the pen tip onto the card crosshair
  5. /fiducial-save fits a full 2x3 affine via least squares and reports RMSE

The fitted matrix includes off-diagonal terms, so any camera-mount rotation
relative to the arm axes is absorbed automatically.
"""
import base64
import logging
import cv2
import numpy as np
from fastapi import APIRouter
from app import calibration
from app.worker_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calibration", tags=["calibration"])

# Reject calibrations whose fit residual exceeds this threshold (mm).
# Typical good calibrations come in at 0.3-0.5mm; > 2mm usually means the
# user clicked corners imprecisely or placed the card at an angle.
RMSE_THRESHOLD_MM = 2.0


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
    """Generic manual save endpoint, kept for scripted/advanced use."""
    station_id = data.pop("station_id")
    await calibration.save_calibration(station_id, data)
    return {"success": True}


@router.post("/capture-for-calibration")
async def capture_for_calibration(data: dict):
    """Capture one rotated photo and return it as base64 for the UI to
    display and let the user click the 4 corners of the calibration card.

    Body: {arm_id}
    Returns:
      image_b64, raw_width, raw_height, rotated_width, rotated_height,
      photo_arm_x, photo_arm_y
    """
    arm_id = data["arm_id"]
    worker = manager.get_worker(arm_id)
    if not worker:
        return {"error": "No worker for arm %d" % arm_id}
    arm = worker.arm_client
    if not arm.is_connected():
        return {"error": "Arm not connected. Connect arm first."}
    cam = worker.camera
    frame = cam.capture_fresh()
    if frame is None:
        return {"error": "Camera capture failed"}
    raw_h, raw_w = frame.shape[:2]
    rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    rot_h, rot_w = rotated.shape[:2]
    _, buf = cv2.imencode(".jpg", rotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    photo_x, photo_y = arm.get_position()
    return {
        "image_b64": base64.b64encode(buf).decode("utf-8"),
        "raw_width": int(raw_w),
        "raw_height": int(raw_h),
        "rotated_width": int(rot_w),
        "rotated_height": int(rot_h),
        "photo_arm_x": float(photo_x),
        "photo_arm_y": float(photo_y),
    }


@router.post("/fiducial-save")
async def fiducial_save(data: dict):
    """Fit 2x3 affine from 4 clicked corners + pen-on-crosshair alignment,
    report RMSE, save if acceptable.

    Body:
      station_id, photo_arm_x, photo_arm_y, pen_arm_x, pen_arm_y,
      corners_rotated: [{x, y}, {x, y}, {x, y}, {x, y}]  # order TL, TR, BR, BL
      card_size_mm (default 50), raw_width, raw_height

    Returns:
      status: "ok" | "poor_precision" | error message
      transform_matrix, camera_park_pos, scale_mm_per_pixel, rotation_degrees, raw_height
      rmse_mm, per_anchor_error_mm, scale_x_mm_per_px, scale_y_mm_per_px, scale_anisotropy
    """
    try:
        station_id = int(data["station_id"])
        card_size = float(data.get("card_size_mm", 50))
        half = card_size / 2.0

        pen_arm = (float(data["pen_arm_x"]), float(data["pen_arm_y"]))
        photo_arm = (float(data["photo_arm_x"]), float(data["photo_arm_y"]))
        corners_rot = data["corners_rotated"]
        if len(corners_rot) != 4:
            return {"error": "corners_rotated must have exactly 4 points (TL, TR, BR, BL)"}
        raw_height = int(data["raw_height"])
    except (KeyError, ValueError, TypeError) as e:
        return {"error": "Invalid request: %s" % e}

    # Convert rotated pixel -> raw pixel using the same formula as pixel_to_arm
    # (see app/calibration.py:94-95). Rotated image was produced by
    # cv2.ROTATE_90_CLOCKWISE, so: raw_x = rotated_y, raw_y = (H-1) - rotated_x.
    H = raw_height - 1

    def to_raw(p):
        return (float(p["y"]), float(H - p["x"]))

    tl_raw = to_raw(corners_rot[0])
    tr_raw = to_raw(corners_rot[1])
    br_raw = to_raw(corners_rot[2])
    bl_raw = to_raw(corners_rot[3])
    # Crosshair pixel = geometric center of the 4 corner pixels.
    cross_raw = (
        (tl_raw[0] + tr_raw[0] + br_raw[0] + bl_raw[0]) / 4.0,
        (tl_raw[1] + tr_raw[1] + br_raw[1] + bl_raw[1]) / 4.0,
    )

    # Under the "card axes aligned with arm axes" assumption (user placed the
    # card with printed edges parallel to the arm's X/Y), the 4 corners sit at
    # fixed offsets from the crosshair in arm space. Crosshair itself is where
    # the user touched the pen, hence pen_arm.
    pairs = [
        (cross_raw, pen_arm),
        (tl_raw, (pen_arm[0] - half, pen_arm[1] - half)),
        (tr_raw, (pen_arm[0] + half, pen_arm[1] - half)),
        (br_raw, (pen_arm[0] + half, pen_arm[1] + half)),
        (bl_raw, (pen_arm[0] - half, pen_arm[1] + half)),
    ]

    M, rmse, per_anchor_errs = _fit_fiducial_affine(pairs)

    # Report scale and rotation (from the fitted matrix — NOT hardcoded to 0).
    # Scale comes from the column norms; rotation from the first column's angle
    # in arm space (same formula as the old _compute_calibration).
    M_np = np.array(M)
    col_x = M_np[:, 0]
    col_y = M_np[:, 1]
    scale_x = float(np.linalg.norm(col_x))
    scale_y = float(np.linalg.norm(col_y))
    scale_avg = (scale_x + scale_y) / 2.0
    rotation_deg = float(np.degrees(np.arctan2(col_x[1], col_x[0])))

    result = {
        "transform_matrix": M,
        "camera_park_pos": [photo_arm[0], photo_arm[1]],
        "scale_mm_per_pixel": round(scale_avg, 6),
        "rotation_degrees": round(rotation_deg, 2),
        "raw_height": raw_height,
    }

    status = "ok" if rmse <= RMSE_THRESHOLD_MM else "poor_precision"
    if status == "ok":
        await calibration.save_calibration(station_id, result)
        logger.info(
            "Fiducial calibration saved: station=%d rmse=%.3fmm rot=%.2fdeg scale=%.4f",
            station_id, rmse, rotation_deg, scale_avg,
        )
    else:
        logger.warning(
            "Fiducial calibration rejected: station=%d rmse=%.3fmm threshold=%.2fmm",
            station_id, rmse, RMSE_THRESHOLD_MM,
        )

    return {
        "status": status,
        "rmse_mm": round(rmse, 3),
        "per_anchor_error_mm": [round(e, 3) for e in per_anchor_errs],
        "scale_x_mm_per_px": round(scale_x, 6),
        "scale_y_mm_per_px": round(scale_y, 6),
        "scale_anisotropy": round(max(scale_x, scale_y) / max(min(scale_x, scale_y), 1e-9), 3),
        **result,
    }


def _fit_fiducial_affine(pairs):
    """Fit a full 2x3 affine matrix mapping raw pixel -> arm coord via least
    squares. Unlike a hardcoded diagonal matrix, this preserves any rotation
    between the camera pixel axes and the arm axes (the existing codebase
    stores 2x3 with off-diagonal terms, so downstream consumers are already
    compatible).

    Equation: arm = M @ [raw_x, raw_y, 1], where M = [[a, b, c], [d, e, f]]
    Expanded:
      arm_x = a*raw_x + b*raw_y + c
      arm_y = d*raw_x + e*raw_y + f

    For N pairs we build a 2N x 6 design matrix and solve for [a, b, c, d, e, f]
    via np.linalg.lstsq. Minimum 3 pairs to be solvable; more gives overdetermined
    fit plus a meaningful RMSE quality metric.

    Args:
      pairs: list of ((raw_x, raw_y), (arm_x, arm_y))

    Returns:
      M: 2x3 nested list, same shape as the legacy _compute_calibration output
      rmse_mm: root-mean-square 2D residual in millimeters
      per_anchor_errs_mm: per-pair 2D euclidean residual in millimeters
    """
    n = len(pairs)
    if n < 3:
        raise ValueError("Need at least 3 pairs to fit 2x3 affine, got %d" % n)

    A = np.zeros((2 * n, 6), dtype=float)
    b = np.zeros(2 * n, dtype=float)
    for i, ((rx, ry), (ax, ay)) in enumerate(pairs):
        A[2 * i] = [rx, ry, 1.0, 0.0, 0.0, 0.0]
        A[2 * i + 1] = [0.0, 0.0, 0.0, rx, ry, 1.0]
        b[2 * i] = ax
        b[2 * i + 1] = ay

    p, *_ = np.linalg.lstsq(A, b, rcond=None)

    M = [
        [float(p[0]), float(p[1]), float(p[2])],
        [float(p[3]), float(p[4]), float(p[5])],
    ]

    M_np = np.array(M)
    per_anchor_errs = []
    for (rx, ry), (ax, ay) in pairs:
        pred = M_np @ np.array([rx, ry, 1.0])
        err = float(np.sqrt((pred[0] - ax) ** 2 + (pred[1] - ay) ** 2))
        per_anchor_errs.append(err)
    rmse = float(np.sqrt(sum(e ** 2 for e in per_anchor_errs) / n))
    return M, rmse, per_anchor_errs
