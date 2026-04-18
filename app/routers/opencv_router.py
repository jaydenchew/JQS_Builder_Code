"""OpenCV screen verification: reference images + comparison.
Uses same path format as screen_checker: references/{arm_name}/{bank_code}/{name}.jpg

/compare delegates to screen_checker.compare_screen so Builder "Test Compare"
and runtime CHECK_SCREEN share one implementation (ORB align + masked SSIM).
"""
import os
import base64
import logging
import cv2
from fastapi import APIRouter
from app import camera, screen_checker
from app.worker_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/opencv", tags=["opencv"])

REFS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "references")
os.makedirs(REFS_DIR, exist_ok=True)


def _get_cam(arm_id=None):
    if arm_id is not None:
        worker = manager.get_worker(arm_id)
        if worker:
            return worker.camera
    return camera


def _ref_path(bank_code, name, arm_name=None):
    """Path: references/{arm_name}/{bank_code}/{name}.jpg or references/{bank_code}/{name}.jpg (legacy)"""
    if arm_name:
        d = os.path.join(REFS_DIR, arm_name, bank_code)
    else:
        d = os.path.join(REFS_DIR, bank_code)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.jpg" % name)


async def _get_arm_name(arm_id):
    if arm_id is None:
        return None
    from app import database
    row = await database.fetchone("SELECT name FROM arms WHERE id = %s", (arm_id,))
    return row["name"] if row else None


@router.post("/capture-reference")
async def capture_reference(data: dict):
    bank_code = data["bank_code"]
    name = data.get("name", "homepage")
    arm_name = await _get_arm_name(data.get("arm_id"))

    cam = _get_cam(data.get("arm_id"))
    frame = cam.capture_rotated()
    if frame is None:
        return {"error": "Camera not available"}

    path = _ref_path(bank_code, name, arm_name)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    with open(path, "wb") as f:
        f.write(buf.tobytes())

    b64 = base64.b64encode(buf).decode("utf-8")
    return {"success": True, "filename": "%s/%s.jpg" % (bank_code, name), "name": name, "preview": b64}


@router.post("/snapshot")
async def snapshot(data: dict):
    """Capture a rotated frame and return as base64 JPEG (no file saved)."""
    cam = _get_cam(data.get("arm_id"))
    frame = cam.capture_rotated()
    if frame is None:
        return {"error": "Camera not available"}
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    b64 = base64.b64encode(buf).decode("utf-8")
    return {"success": True, "image": b64, "width": frame.shape[1], "height": frame.shape[0]}


@router.get("/references/{bank_code}")
async def list_references(bank_code: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    refs = []
    if arm_name:
        bank_dir = os.path.join(REFS_DIR, arm_name, bank_code)
    else:
        bank_dir = os.path.join(REFS_DIR, bank_code)
    if not os.path.isdir(bank_dir):
        return refs
    for f in sorted(os.listdir(bank_dir)):
        if f.endswith(".jpg"):
            name = f[:-4]
            refs.append({"filename": f, "name": name, "bank_code": bank_code})
    return refs


@router.get("/references/{bank_code}/{name}/preview")
async def reference_preview(bank_code: str, name: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    path = _ref_path(bank_code, name, arm_name)
    if not os.path.exists(path):
        path = _ref_path(bank_code, name)
    if not os.path.exists(path):
        return {"error": "Not found"}
    img = cv2.imread(path)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return {"preview": base64.b64encode(buf).decode("utf-8")}


@router.post("/compare")
async def compare_screen(data: dict):
    bank_code = data["bank_code"]
    name = data.get("name", "homepage")
    threshold = data.get("threshold", screen_checker.DEFAULT_SSIM_THRESHOLD)
    roi = data.get("roi")
    arm_name = await _get_arm_name(data.get("arm_id"))

    reference = screen_checker.load_reference(bank_code, name, arm_name)
    if reference is None:
        return {"error": "Reference not found: %s/%s" % (bank_code, name)}

    cam = _get_cam(data.get("arm_id"))
    # 必须和 actions.execute_check_screen 走同一条路径：capture_fresh() 关闭并重开相机，
    # 绕过 DSHOW 内部 buffer 的旧帧，保证 Builder "Test Compare" 的分数等于运行时分数。
    frame = cam.capture_fresh()
    if frame is None:
        return {"error": "Camera not available"}
    current = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

    result = screen_checker.compare_screen(current, reference, threshold, roi)
    logger.info(
        "Test Compare: bank=%s ref=%s arm=%s ssim=%.4f inliers=%d rot=%.2fdeg scale=%.3f valid=%.2f ms=%.0f reason=%s threshold=%.2f match=%s",
        bank_code, name, arm_name or "-", result["ssim"], result["inliers"],
        result["rot_deg"], result["scale"], result["valid_ratio"], result["ms"],
        result["reason"], threshold, result["pass"],
    )
    return {
        **result,
        "match": result["pass"],
        "score": round(result["ssim"], 4),
        "threshold": threshold,
    }


@router.delete("/references/{bank_code}/{name}")
async def delete_reference(bank_code: str, name: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    for path in [_ref_path(bank_code, name, arm_name), _ref_path(bank_code, name)]:
        if os.path.exists(path):
            os.remove(path)
            return {"success": True, "deleted": path}
    return {"error": "Not found"}
