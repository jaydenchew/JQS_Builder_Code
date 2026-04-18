# CHECK_SCREEN Operations Guide

运维 / Builder 使用者一页纸手册。看懂 log 里的 `Test Compare:` 和 `CHECK_SCREEN:` 行 → 知道何时放心、何时警觉、何时动手。

## 一条 log 长什么样

**Builder "Test Compare"（每点一次打一条）**
```
[INFO] app.routers.opencv_router: Test Compare: bank=ACLEDA ref=arm01_acleda_3 arm=ARM-01
  ssim=0.9054 inliers=915 rot=-0.01deg scale=0.999 valid=1.00 ms=195
  reason=match threshold=0.80 match=True
```

**生产 flow 执行（每次 CHECK_SCREEN step 打一条，可能多次重试）**
```
[INFO] app.actions: CHECK_SCREEN: attempt 1/3, ssim=0.9054 inliers=915 rot=-0.01deg
  valid=1.00 reason=match threshold=0.80 match=True
```

## 8 个字段的读法

| 字段 | 健康值 | 含义 | 出问题时说明 |
|---|---|---|---|
| `ssim` | **≥ 0.85** | 对齐后两张图的像素相似度（0-1） | 低于 threshold → fail |
| `inliers` | **≥ 50** | ORB 特征点匹配上的内点数 | < 25 → `wrong_screen` |
| `rot_deg` | **-1 ~ +1 度** | 当前帧相对参考帧的旋转角 | 持续 > 3 度 → 手机/支架松了 |
| `scale` | **0.95 ~ 1.05** | 当前帧相对参考帧的缩放比 | > 1.10 or < 0.90 → 摄像头被移位 |
| `valid_ratio` | **≥ 0.90** | warp 后有效像素占 ROI 比例 | < 0.60 → 对齐质量差 |
| `ms` | **30-200** | 单次比对耗时（含 capture_fresh） | > 500 → 相机/CPU 卡 |
| `reason` | `match` | 诊断标签 | 见下方 4 种 |
| `threshold` | 一般 0.80 | 当前 step 的 SSIM 阈值 | 仅显示当前设置 |

## `reason` 的 4 种取值

| reason | 含义 | 运维动作 |
|---|---|---|
| `match` | 三层门禁全过，正常 | 无 |
| `popup_detected` | 是正确页面，但被东西遮住了 | 正常 —— handler_flow 会自动处理弹窗 |
| `wrong_screen` | 根本不是这个页面 | 检查上一步是否成功跳转；若频繁出现，检查 bank app 是否被更新了 |
| `alignment_failed` | ORB 连对齐都没做到（低光、屏幕黑、特征极少） | 检查相机是否被遮挡；检查手机屏幕是否真的亮着 |

## 健康基线（现场应该是什么样）

一个稳定运行的系统，正确页面 Test Compare 应该长这样：
- `ssim` 0.88-0.95
- `inliers` 300-1500
- `rot_deg` 在 ±0.5 度内波动
- `scale` 在 0.99-1.01 内波动
- `valid_ratio` = 1.00 或非常接近
- `ms` 50-200
- `reason=match`

**数据基本不漂移** = 物理环境稳定 = 无需动作。

## 5 个警戒信号（发生了就要动手）

1. **`rot_deg` 开始持续出现 ±2-3 度**
   → 手机在支架里松动，或支架本身移位
   → 动作：检查支架螺丝，把手机按回到位

2. **`scale` 持续跑偏到 0.90 或 1.10**
   → 摄像头被撞了、前后距离变了
   → 动作：Dashboard → Verify Camera 看实时画面，必要时重新对准

3. **`inliers` 在同一个参考图上从 500+ 掉到 50-100**
   → 屏幕脏了 / 摄像头脏了 / 焦距跑了 / 光线改变
   → 动作：擦屏幕和摄像头；检查现场光源有没有变（新开的灯、窗帘拉开）

4. **`reason=wrong_screen` 频繁出现在同一个 step**
   → 上一步 CLICK/TYPE 实际没成功跳转，但系统以为成功了
   → 动作：重新拍参考图（可能 bank app 更新了 UI）；或检查上一步的坐标/OCR

5. **`reason=alignment_failed` 反复出现**
   → 罕见，通常是相机黑屏或手机锁屏了
   → 动作：重启相机（Dashboard Verify）；唤醒手机屏幕

## 一次校准流程（新装机或重大改动后做一次）

1. Builder 打开一个 CHECK_SCREEN step
2. 摆好手机、正确页面 → 点 `Capture Now` 存参考图
3. 点 `Test Compare`，记下 `ssim` 值（比如 0.93）
4. 手动挪一下手机 0.5cm → `Test Compare` 再记一次（比如 0.89）
5. 把 `Match Threshold` 设为 `[两次中较低值] - 0.05`（这里就是 0.84）
6. 保存

这样既能过正常波动，又不会太松放过错误页面。

## 历史上的黑名单（避免重蹈覆辙）

- **别做**：把 threshold 调到 0.50 强过。你其实只是关闭了保护，下一次错页面也会过。正确做法是查 `reason`：是 `popup` 就加 handler_flow，是 `wrong_screen` 就修上一步。
- **别做**：把 ROI 缩到一个按钮那么小。ROI 只是让 SSIM 忽略动态区域，小 ROI 不能提升对齐精度（对齐永远在全图做），只会让 SSIM 噪声放大。建议 ROI 至少占全图 40%。
- **别做**：每次失败就重拍参考图。如果原参考图是对的，失败通常是现场问题（光/位置/脏污），重拍只会把问题固化进新参考图。

## 相关文档

- [CHANGELOG.md](CHANGELOG.md) — 2026-04-18 条目，算法替换细节
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) — DD-022，为什么选这个算法
- [ORB+OCR/check_screen_poc.py](ORB+OCR/check_screen_poc.py) — 可重跑的 POC 基线
