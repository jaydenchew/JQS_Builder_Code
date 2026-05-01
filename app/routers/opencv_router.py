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


# === FIND_AND_CLICK template + live test ================================
# Templates live alongside CHECK_SCREEN references in references/<arm>/<bank>/
# but use a "_tpl.jpg" suffix to keep the two namespaces visually separate.
# Same path scheme as app/find_and_click.py:get_template_path so the runtime
# loader and Builder save end up at the same file.

def _tpl_path(bank_code, name, arm_name=None):
    if arm_name:
        d = os.path.join(REFS_DIR, arm_name, bank_code)
    else:
        d = os.path.join(REFS_DIR, bank_code)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s_tpl.jpg" % name)


@router.post("/capture-template")
async def capture_template(data: dict):
    """Save a cropped sub-region of the current frame as a FIND_AND_CLICK template.

    Body:
        bank_code (str), name (str), arm_id (int)
        rect: {x, y, w, h}  rectangle in rotated-frame pixel coords

    Returns: {success, filename, name, preview (base64 jpg)}.
    """
    bank_code = data["bank_code"]
    name = data.get("name") or "button"
    arm_name = await _get_arm_name(data.get("arm_id"))
    rect = data.get("rect") or {}
    x = int(rect.get("x", 0))
    y = int(rect.get("y", 0))
    w = int(rect.get("w", 0))
    h = int(rect.get("h", 0))
    if w <= 0 or h <= 0:
        return {"error": "rect.w / rect.h must be positive"}

    cam = _get_cam(data.get("arm_id"))
    frame = cam.capture_rotated()
    if frame is None:
        return {"error": "Camera not available"}
    fh, fw = frame.shape[:2]
    x2 = min(fw, x + w)
    y2 = min(fh, y + h)
    x = max(0, x)
    y = max(0, y)
    if x2 <= x or y2 <= y:
        return {"error": "rect outside frame bounds"}

    crop = frame[y:y2, x:x2]
    if crop.size == 0:
        return {"error": "rect produces empty crop"}

    path = _tpl_path(bank_code, name, arm_name)
    _, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    with open(path, "wb") as f:
        f.write(buf.tobytes())

    b64 = base64.b64encode(buf).decode("utf-8")
    return {
        "success": True,
        "filename": "%s/%s_tpl.jpg" % (bank_code, name),
        "name": name,
        "preview": b64,
        "width": crop.shape[1],
        "height": crop.shape[0],
    }


@router.get("/templates/{bank_code}/{name}/preview")
async def template_preview(bank_code: str, name: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    path = _tpl_path(bank_code, name, arm_name)
    if not os.path.exists(path):
        path = _tpl_path(bank_code, name)
    if not os.path.exists(path):
        return {"error": "Not found"}
    img = cv2.imread(path)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return {"preview": base64.b64encode(buf).decode("utf-8")}


@router.delete("/templates/{bank_code}/{name}")
async def delete_template(bank_code: str, name: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    for path in [_tpl_path(bank_code, name, arm_name), _tpl_path(bank_code, name)]:
        if os.path.exists(path):
            os.remove(path)
            return {"success": True, "deleted": path}
    return {"error": "Not found"}


@router.post("/find-and-click")
async def find_and_click_test(data: dict):
    """Builder live test of FIND_AND_CLICK.

    Body:
        arm_id (int), station_id (int), bank_code (str)
        ui_element_key (str)  -- camera anchor position lookup key
        config: dict           -- same shape as a flow_step.description JSON
        click_after_find: bool -- default true; pass false to preview only

    Returns the diagnostics dict from app.find_and_click.find_and_click,
    or {"error": "..."} on hard failures (worker / arm / cal missing).
    """
    from app import find_and_click as fac
    from app.actions import lookup_ui_element

    arm_id = data.get("arm_id")
    station_id = data.get("station_id")
    bank_code = data.get("bank_code")
    ui_key = data.get("ui_element_key")
    config = data.get("config") or {}
    click_after_find = bool(data.get("click_after_find", True))

    if arm_id is None or station_id is None or not bank_code or not ui_key:
        return {"error": "arm_id, station_id, bank_code, ui_element_key required"}

    worker = manager.get_worker(int(arm_id))
    if worker is None:
        return {"error": "No worker for arm_id=%s (resume from Dashboard first)" % arm_id}

    try:
        cam_x, cam_y = await lookup_ui_element(bank_code, int(station_id), ui_key)
    except ValueError as e:
        return {"error": "Camera anchor not found: %s" % e}

    arm_name = await _get_arm_name(int(arm_id))

    try:
        result = await fac.find_and_click(
            config=config,
            station_id=int(station_id),
            bank_code=bank_code,
            arm_name=arm_name,
            arm=worker.arm_client,
            cam=worker.camera,
            executor=worker._executor,
            anchor_pos=(cam_x, cam_y),
            click_after_find=click_after_find,
        )
        result["ok"] = True
        return result
    except RuntimeError as e:
        logger.warning("FIND_AND_CLICK test failed: %s", e)
        return {"ok": False, "found": False, "error": str(e)}
    except Exception as e:
        logger.exception("FIND_AND_CLICK test crashed: %s", e)
        return {"ok": False, "found": False, "error": str(e)}


@router.post("/find-and-swipe")
async def find_and_swipe_test(data: dict):
    """Builder live test of FIND_AND_SWIPE.

    Body:
        arm_id (int), station_id (int), bank_code (str)
        swipe_key (str)             -- looks up start/end in swipe_actions
        config: dict                -- same shape as flow_step.description JSON
                                       (template/ocr/combine/threshold/roi/...)
        swipe_after_find: bool      -- default true; pass false to preview only

    Returns the diagnostics dict from app.find_and_swipe.find_and_swipe,
    including matched start, computed end, and clamp_warning if applicable.
    """
    from app import find_and_swipe as fas
    from app.actions import lookup_swipe

    arm_id = data.get("arm_id")
    station_id = data.get("station_id")
    bank_code = data.get("bank_code")
    swipe_key = data.get("swipe_key")
    config = data.get("config") or {}
    swipe_after_find = bool(data.get("swipe_after_find", True))

    if arm_id is None or station_id is None or not bank_code or not swipe_key:
        return {"error": "arm_id, station_id, bank_code, swipe_key required"}

    worker = manager.get_worker(int(arm_id))
    if worker is None:
        return {"error": "No worker for arm_id=%s (resume from Dashboard first)" % arm_id}

    try:
        sx_rec, sy_rec, ex_rec, ey_rec = await lookup_swipe(
            bank_code, int(station_id), swipe_key)
    except ValueError as e:
        return {"error": "Swipe coords not found: %s" % e}

    arm_name = await _get_arm_name(int(arm_id))

    try:
        result = await fas.find_and_swipe(
            config=config,
            station_id=int(station_id),
            bank_code=bank_code,
            arm_name=arm_name,
            arm=worker.arm_client,
            cam=worker.camera,
            executor=worker._executor,
            recorded_swipe=(sx_rec, sy_rec, ex_rec, ey_rec),
            swipe_after_find=swipe_after_find,
        )
        result["ok"] = True
        return result
    except RuntimeError as e:
        logger.warning("FIND_AND_SWIPE test failed: %s", e)
        return {"ok": False, "found": False, "error": str(e)}
    except Exception as e:
        logger.exception("FIND_AND_SWIPE test crashed: %s", e)
        return {"ok": False, "found": False, "error": str(e)}
