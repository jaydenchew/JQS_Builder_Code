"""OpenCV screen verification: reference images + comparison.
Uses same path format as screen_checker: references/{arm_name}/{bank_code}/{name}.jpg
"""
import os
import base64
import cv2
import numpy as np
from fastapi import APIRouter
from app import camera
from app.worker_manager import manager

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
    threshold = data.get("threshold", 0.70)
    roi = data.get("roi")
    arm_name = await _get_arm_name(data.get("arm_id"))

    path = _ref_path(bank_code, name, arm_name)
    if not os.path.exists(path):
        path = _ref_path(bank_code, name)
    if not os.path.exists(path):
        return {"error": "Reference not found: %s/%s" % (bank_code, name)}

    ref_data = np.fromfile(path, dtype=np.uint8)
    ref = cv2.imdecode(ref_data, cv2.IMREAD_GRAYSCALE)
    cam = _get_cam(data.get("arm_id"))
    frame = cam.capture_rotated()
    if frame is None:
        return {"error": "Camera not available"}

    cur = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if roi:
        ref = _crop_roi(ref, roi)
        cur = _crop_roi(cur, roi)

    score = _compare_grayscale(ref, cur)
    return {
        "match": score >= threshold,
        "score": round(score, 4),
        "threshold": threshold,
    }


def _crop_roi(img, roi):
    h, w = img.shape[:2]
    y1 = int(h * roi.get("top_percent", 0) / 100)
    y2 = int(h * roi.get("bottom_percent", 100) / 100)
    x1 = int(w * roi.get("left_percent", 0) / 100)
    x2 = int(w * roi.get("right_percent", 100) / 100)
    return img[y1:y2, x1:x2]


@router.delete("/references/{bank_code}/{name}")
async def delete_reference(bank_code: str, name: str, arm_id: int = None):
    arm_name = await _get_arm_name(arm_id)
    for path in [_ref_path(bank_code, name, arm_name), _ref_path(bank_code, name)]:
        if os.path.exists(path):
            os.remove(path)
            return {"success": True, "deleted": path}
    return {"error": "Not found"}


def _compare_grayscale(ref, cur):
    if ref.shape != cur.shape:
        cur = cv2.resize(cur, (ref.shape[1], ref.shape[0]))

    h = 320
    w = int(h * ref.shape[1] / ref.shape[0])
    r = cv2.resize(ref, (w, h))
    c = cv2.resize(cur, (w, h))

    ssim = _ssim(r, c)
    edge = _edge_similarity(r, c)

    score = 0.8 * max(0, ssim) + 0.2 * max(0, edge)
    return min(1.0, score)


def _ssim(img1, img2):
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    i1 = img1.astype(np.float64)
    i2 = img2.astype(np.float64)
    k = (11, 11)

    mu1 = cv2.GaussianBlur(i1, k, 1.5)
    mu2 = cv2.GaussianBlur(i2, k, 1.5)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu12 = mu1 * mu2

    s1_sq = cv2.GaussianBlur(i1 * i1, k, 1.5) - mu1_sq
    s2_sq = cv2.GaussianBlur(i2 * i2, k, 1.5) - mu2_sq
    s12 = cv2.GaussianBlur(i1 * i2, k, 1.5) - mu12

    ssim_map = ((2 * mu12 + C1) * (2 * s12 + C2)) / \
               ((mu1_sq + mu2_sq + C1) * (s1_sq + s2_sq + C2))
    return float(ssim_map.mean())


def _edge_similarity(img1, img2):
    e1 = cv2.Canny(img1, 50, 150)
    e2 = cv2.Canny(img2, 50, 150)

    both = np.sum((e1 > 0) & (e2 > 0))
    total = max(np.sum(e1 > 0) + np.sum(e2 > 0), 1)
    iou = 2.0 * both / total

    return float(iou)
