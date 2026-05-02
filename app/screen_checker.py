"""屏幕检查模块 — CHECK_SCREEN action type 的执行引擎

算法：ORB 特征 + Similarity 对齐 + 对齐后 SSIM（三层门禁）
  1. 移动到拍照位，拍一张当前屏幕截图
  2. ORB 在全图上提取关键点 → BFMatcher + Lowe ratio → estimateAffinePartial2D
  3. 用 Similarity 矩阵把当前帧 warp 到参考帧坐标系
  4. 在可选 ROI 内对已对齐的两张图做 masked SSIM
  5. 通过条件：inliers >= MIN_INLIERS AND aligned_ssim >= threshold AND valid_ratio >= MIN_VALID_RATIO

配置存储在 flow_steps.description 字段，JSON 格式：
{
    "reference": "homepage",
    "handler_flow": "BANK__template_id",
    "threshold": 0.80,
    "max_retries": 3,
    "trigger": "on_mismatch",
    "roi": {"top_percent": 25, "bottom_percent": 90, "left_percent": 20, "right_percent": 87}
}

threshold 语义：对齐后 SSIM（0.0–1.0）。POC 验证：正例 min=0.95, 异常 max=0.60。
min_inliers / valid_ratio 作为模块常量，不暴露到 UI。

trigger 语义（在 actions.execute_check_screen 里消费，本模块只存储不解释）：
  on_mismatch（默认，旧行为）— 期望 match。看到画面 → ok；看不到 → 跑 handler+retry。
  on_match（新）— 期望 mismatch（画面不应在）。看不到 → ok；看到 → 跑 handler 清掉它+retry。
两种模式逻辑对称，max_retries 在两种模式下都是"给画面变成期望状态的最多机会次数"。
on_mismatch 用于"必看画面"（如已回到主屏检查），on_match 用于"偶发 popup"（如验证码弹窗）。
"""
import cv2
import numpy as np
import os
import json
import time
import logging

logger = logging.getLogger(__name__)

REFERENCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "references")
os.makedirs(REFERENCES_DIR, exist_ok=True)


ORB_NFEATURES = 2000
MIN_INLIERS = 25
DEFAULT_SSIM_THRESHOLD = 0.80
MIN_VALID_RATIO = 0.60
RATIO_TEST = 0.75
SCALE_TOLERANCE = (0.85, 1.15)


def _empty_result(reason: str, elapsed_ms: float, inliers: int = 0,
                  rot_deg: float = 0.0, scale: float = 0.0,
                  valid_ratio: float = 0.0, ssim: float = 0.0):
    return {
        "pass": False,
        "ssim": round(ssim, 4),
        "inliers": int(inliers),
        "rot_deg": round(rot_deg, 2),
        "scale": round(scale, 3),
        "valid_ratio": round(valid_ratio, 3),
        "ms": round(elapsed_ms, 1),
        "reason": reason,
    }


def get_reference_path(bank_code: str, name: str, arm_name: str = None):
    if arm_name:
        d = os.path.join(REFERENCES_DIR, arm_name, bank_code)
    else:
        d = os.path.join(REFERENCES_DIR, bank_code)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.jpg" % name)


def load_reference(bank_code: str, name: str, arm_name: str = None):
    """加载参考图片（支持中文路径，优先 arm 目录）。返回 BGR ndarray 或 None。"""
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


def _align_similarity(ref_gray: np.ndarray, cur_gray: np.ndarray):
    """ORB + RANSAC Similarity 对齐 current→reference 坐标系。

    返回 (aligned_gray, mask_valid, inliers, rot_deg, scale) 或 None（无法对齐）。
    """
    if ref_gray.shape != cur_gray.shape:
        cur_gray = cv2.resize(cur_gray, (ref_gray.shape[1], ref_gray.shape[0]))

    orb = cv2.ORB_create(nfeatures=ORB_NFEATURES, scaleFactor=1.2, nlevels=8)
    kp1, des1 = orb.detectAndCompute(ref_gray, None)
    kp2, des2 = orb.detectAndCompute(cur_gray, None)

    if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
        return None

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(des1, des2, k=2)

    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < RATIO_TEST * n.distance:
            good.append(m)

    if len(good) < 4:
        return None

    src = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)

    M, mask = cv2.estimateAffinePartial2D(
        src, dst,
        method=cv2.RANSAC,
        ransacReprojThreshold=5.0,
        maxIters=2000,
        confidence=0.995,
    )
    if M is None or mask is None:
        return None

    inliers = int(mask.sum())

    a, b = float(M[0, 0]), float(M[0, 1])
    scale = float(np.sqrt(a * a + b * b))
    rot_deg = float(np.degrees(np.arctan2(b, a)))

    h, w = ref_gray.shape
    aligned_gray = cv2.warpAffine(cur_gray, M, (w, h), flags=cv2.INTER_LINEAR)
    mask_valid = cv2.warpAffine(
        np.ones_like(cur_gray, dtype=np.uint8) * 255, M, (w, h),
        flags=cv2.INTER_NEAREST,
    )
    return aligned_gray, mask_valid, inliers, rot_deg, scale


def compare_screen(current_frame, reference, threshold: float = DEFAULT_SSIM_THRESHOLD, roi=None):
    """比较当前屏幕与参考图片（ORB 对齐 + masked SSIM）。

    参数：
        current_frame: BGR ndarray，相机捕获并已旋转的当前帧
        reference:     BGR ndarray，来自 load_reference()
        threshold:     对齐后 SSIM 阈值（0.0–1.0），默认 DEFAULT_SSIM_THRESHOLD
        roi:           dict {top_percent, bottom_percent, left_percent, right_percent} 或 None

    返回：dict，字段：
        pass (bool), ssim (float), inliers (int), rot_deg (float),
        scale (float), valid_ratio (float), ms (float),
        reason (str)  — "match" | "popup_detected" | "wrong_screen" | "alignment_failed"
    """
    t0 = time.perf_counter()

    if current_frame is None or reference is None:
        return _empty_result("alignment_failed", (time.perf_counter() - t0) * 1000)

    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    gray_cur = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

    aligned = _align_similarity(gray_ref, gray_cur)
    if aligned is None:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning("CHECK_SCREEN align failed (ORB/RANSAC returned None)")
        return _empty_result("alignment_failed", elapsed)

    aligned_gray, mask_valid, inliers, rot_deg, scale = aligned

    if scale < SCALE_TOLERANCE[0] or scale > SCALE_TOLERANCE[1]:
        logger.warning(
            "CHECK_SCREEN scale out of tolerance: scale=%.3f (expected %.2f..%.2f) — 对齐可能不稳，仅告警",
            scale, SCALE_TOLERANCE[0], SCALE_TOLERANCE[1],
        )

    ref_roi = gray_ref
    aligned_roi = aligned_gray
    mask_roi = mask_valid
    if roi:
        h, w = gray_ref.shape
        y1 = int(h * roi.get("top_percent", 0) / 100)
        y2 = int(h * roi.get("bottom_percent", 100) / 100)
        x1 = int(w * roi.get("left_percent", 0) / 100)
        x2 = int(w * roi.get("right_percent", 100) / 100)
        if y1 < y2 and x1 < x2:
            ref_roi = gray_ref[y1:y2, x1:x2]
            aligned_roi = aligned_gray[y1:y2, x1:x2]
            mask_roi = mask_valid[y1:y2, x1:x2]
        else:
            logger.warning(
                "Invalid CHECK_SCREEN ROI: top=%d bottom=%d left=%d right=%d, using full image",
                y1, y2, x1, x2,
            )

    valid_ratio = float((mask_roi > 0).mean()) if mask_roi.size > 0 else 0.0

    if mask_roi.sum() > 0:
        ref_masked = cv2.bitwise_and(ref_roi, ref_roi, mask=mask_roi)
        aligned_masked = cv2.bitwise_and(aligned_roi, aligned_roi, mask=mask_roi)
        ssim_score = _ssim(ref_masked, aligned_masked)
    else:
        ssim_score = 0.0

    elapsed = (time.perf_counter() - t0) * 1000

    inliers_ok = inliers >= MIN_INLIERS
    ssim_ok = ssim_score >= threshold
    valid_ok = valid_ratio >= MIN_VALID_RATIO

    if inliers_ok and ssim_ok and valid_ok:
        reason = "match"
    elif not inliers_ok:
        reason = "wrong_screen"
    elif not ssim_ok:
        reason = "popup_detected"
    else:
        reason = "wrong_screen"

    return {
        "pass": bool(inliers_ok and ssim_ok and valid_ok),
        "ssim": round(float(ssim_score), 4),
        "inliers": int(inliers),
        "rot_deg": round(rot_deg, 2),
        "scale": round(scale, 3),
        "valid_ratio": round(valid_ratio, 3),
        "ms": round(elapsed, 1),
        "reason": reason,
    }


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


def parse_check_config(description: str):
    """从 step.description 解析 CHECK_SCREEN 配置"""
    if not description:
        return None
    try:
        return json.loads(description)
    except (json.JSONDecodeError, TypeError):
        logger.error("CHECK_SCREEN 配置解析失败: %s", description)
        return None
