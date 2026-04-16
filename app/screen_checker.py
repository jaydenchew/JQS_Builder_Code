"""屏幕检查模块 — CHECK_SCREEN action type 的执行引擎

功能：
  1. 移动到拍照位，拍一张当前屏幕截图
  2. 用 SSIM + 边缘相似度与参考图片比对
  3. 如果匹配 → 屏幕正确，继续 flow
  4. 如果不匹配 → 可能有弹窗，执行 handler flow 关闭弹窗，再重试
  5. 超过最大重试次数 → 失败

配置存储在 flow_steps.description 字段，JSON 格式：
{
    "reference": "homepage",
    "handler_flow": "BANK__template_id",
    "threshold": 0.85,
    "max_retries": 3
}
"""
import cv2
import numpy as np
import os
import json
import logging

logger = logging.getLogger(__name__)

REFERENCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")
os.makedirs(REFERENCES_DIR, exist_ok=True)


def get_reference_path(bank_code: str, name: str, arm_name: str = None):
    if arm_name:
        d = os.path.join(REFERENCES_DIR, arm_name, bank_code)
    else:
        d = os.path.join(REFERENCES_DIR, bank_code)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.jpg" % name)


def load_reference(bank_code: str, name: str, arm_name: str = None):
    """加载参考图片（支持中文路径，优先 arm 目录）"""
    path = get_reference_path(bank_code, name, arm_name)
    if not os.path.exists(path):
        path = get_reference_path(bank_code, name)
    if not os.path.exists(path):
        logger.error("参考图片不存在: %s", path)
        return None
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        logger.error("参考图片加载失败: %s", path)
    return img


def compare_screen(current_frame, reference, threshold=0.85, roi=None):
    """比较当前屏幕和参考图片 (SSIM + 边缘相似度)
    roi: {"top_percent", "bottom_percent", "left_percent", "right_percent"}
    """
    if current_frame is None or reference is None:
        return False, 0.0

    if roi:
        h, w = current_frame.shape[:2]
        y1 = int(h * roi.get("top_percent", 0) / 100)
        y2 = int(h * roi.get("bottom_percent", 100) / 100)
        x1 = int(w * roi.get("left_percent", 0) / 100)
        x2 = int(w * roi.get("right_percent", 100) / 100)
        if y1 < y2 and x1 < x2:
            current_frame = current_frame[y1:y2, x1:x2]
            reference = reference[y1:y2, x1:x2]
        else:
            logger.warning("Invalid CHECK_SCREEN ROI: top=%d bottom=%d left=%d right=%d, using full image", y1, y2, x1, x2)

    gray_cur = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)

    if gray_ref.shape != gray_cur.shape:
        gray_cur = cv2.resize(gray_cur, (gray_ref.shape[1], gray_ref.shape[0]))

    h = 320
    w = int(h * gray_ref.shape[1] / gray_ref.shape[0])
    r = cv2.resize(gray_ref, (w, h))
    c = cv2.resize(gray_cur, (w, h))

    ssim = _ssim(r, c)
    edge = _edge_similarity(r, c)

    score = 0.6 * max(0, ssim) + 0.4 * max(0, edge)
    score = min(1.0, score)

    is_match = score >= threshold
    return is_match, round(score, 4)


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


def capture_rotated_from(camera_instance):
    """Capture a rotated frame from a given camera instance"""
    frame = camera_instance.capture_frame()
    if frame is None:
        return None
    return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)


def parse_check_config(description: str):
    """从 step.description 解析 CHECK_SCREEN 配置"""
    if not description:
        return None
    try:
        return json.loads(description)
    except (json.JSONDecodeError, TypeError):
        logger.error("CHECK_SCREEN 配置解析失败: %s", description)
        return None
