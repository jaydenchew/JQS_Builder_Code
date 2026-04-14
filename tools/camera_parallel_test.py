"""Camera parallel capability test.

Tests whether multiple USB cameras can be opened and read simultaneously
using different OpenCV backends (MSMF, DSHOW).

IMPORTANT: Stop the WA-Unified service before running this script,
           otherwise the service holds camera handles.

Usage:
    python tools/camera_parallel_test.py
    python tools/camera_parallel_test.py --cameras 0 1 2
    python tools/camera_parallel_test.py --duration 30
"""
import cv2
import time
import argparse
import threading
import numpy as np
from dataclasses import dataclass, field

BACKENDS = {
    "MSMF": cv2.CAP_MSMF,
    "DSHOW": cv2.CAP_DSHOW,
    "AUTO": cv2.CAP_ANY,
}


@dataclass
class CameraStats:
    camera_id: int
    backend: str
    opened: bool = False
    open_error: str = ""
    total_reads: int = 0
    success_reads: int = 0
    fail_reads: int = 0
    max_consecutive_fails: int = 0
    black_frames: int = 0
    read_times: list = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.success_reads / self.total_reads * 100) if self.total_reads else 0

    @property
    def avg_read_ms(self) -> float:
        return (sum(self.read_times) / len(self.read_times) * 1000) if self.read_times else 0

    def summary(self) -> str:
        lines = [
            f"  Camera {self.camera_id} [{self.backend}]:",
            f"    isOpened: {self.opened}",
        ]
        if not self.opened:
            lines.append(f"    Error: {self.open_error}")
            return "\n".join(lines)
        lines += [
            f"    Reads: {self.success_reads}/{self.total_reads} "
            f"({self.success_rate:.1f}% success)",
            f"    Failed: {self.fail_reads}  |  Max consecutive fails: {self.max_consecutive_fails}",
            f"    Black frames: {self.black_frames}",
            f"    Avg read time: {self.avg_read_ms:.1f} ms",
        ]
        return "\n".join(lines)


def is_black_frame(frame, threshold=10) -> bool:
    """Check if frame is mostly black or white (corrupted)."""
    mean = np.mean(frame)
    return mean < threshold or mean > 245


def test_single_camera(cam_id: int, backend_code: int, backend_name: str,
                        duration: float, interval: float,
                        cap_holder: dict, stats_out: dict,
                        open_barrier: threading.Barrier):
    """Thread target: open one camera, read frames for `duration` seconds."""
    stats = CameraStats(camera_id=cam_id, backend=backend_name)

    cap = cv2.VideoCapture(cam_id, backend_code)
    cap_holder[cam_id] = cap

    if not cap.isOpened():
        stats.opened = False
        stats.open_error = f"VideoCapture({cam_id}, {backend_name}).isOpened() = False"
        stats_out[cam_id] = stats
        try:
            open_barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        return

    stats.opened = True
    # warmup
    for _ in range(3):
        cap.read()

    print(f"  [cam{cam_id}] Opened OK with {backend_name}, waiting for all cameras...")

    try:
        open_barrier.wait(timeout=10)
    except threading.BrokenBarrierError:
        pass

    print(f"  [cam{cam_id}] Starting read loop ({duration}s)...")

    consecutive_fails = 0
    end_time = time.time() + duration

    while time.time() < end_time:
        t0 = time.perf_counter()
        ret, frame = cap.read()
        elapsed = time.perf_counter() - t0

        stats.total_reads += 1
        stats.read_times.append(elapsed)

        if not ret or frame is None:
            stats.fail_reads += 1
            consecutive_fails += 1
            stats.max_consecutive_fails = max(stats.max_consecutive_fails, consecutive_fails)
        else:
            stats.success_reads += 1
            consecutive_fails = 0
            if is_black_frame(frame):
                stats.black_frames += 1

        time.sleep(interval)

    cap.release()
    stats_out[cam_id] = stats


def test_backend(backend_name: str, backend_code: int,
                 camera_ids: list[int], duration: float, interval: float) -> dict:
    """Test one backend with all cameras in parallel."""
    print(f"\n{'='*60}")
    print(f"  Backend: {backend_name}  |  Cameras: {camera_ids}  |  Duration: {duration}s")
    print(f"{'='*60}")

    barrier = threading.Barrier(len(camera_ids))
    stats_out = {}
    cap_holder = {}
    threads = []

    for cam_id in camera_ids:
        t = threading.Thread(
            target=test_single_camera,
            args=(cam_id, backend_code, backend_name,
                  duration, interval, cap_holder, stats_out, barrier),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=duration + 15)

    return stats_out


def test_dshow_by_name(camera_ids: list[int], duration: float, interval: float):
    """Extra test: try opening DSHOW cameras by enumerated device path."""
    print(f"\n{'='*60}")
    print(f"  DSHOW device enumeration test")
    print(f"{'='*60}")

    for cam_id in camera_ids:
        cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
        if cap.isOpened():
            print(f"  [cam{cam_id}] DSHOW by index: OK")
            ret, frame = cap.read()
            print(f"  [cam{cam_id}] First read: {'OK' if ret else 'FAILED'}")
            cap.release()
        else:
            print(f"  [cam{cam_id}] DSHOW by index: FAILED (can't open)")


def main():
    parser = argparse.ArgumentParser(description="Camera parallel test")
    parser.add_argument("--cameras", nargs="+", type=int, default=[0, 1, 2],
                        help="Camera IDs to test (default: 0 1 2)")
    parser.add_argument("--duration", type=float, default=20,
                        help="Test duration in seconds (default: 20)")
    parser.add_argument("--interval", type=float, default=0.2,
                        help="Read interval in seconds (default: 0.2)")
    args = parser.parse_args()

    print(f"OpenCV version: {cv2.__version__}")
    print(f"Available backends: {[cv2.videoio_registry.getBackendName(b) for b in cv2.videoio_registry.getBackends()]}")
    print(f"Testing cameras: {args.cameras}")
    print(f"Duration: {args.duration}s, Interval: {args.interval}s")

    # --- Test 1: Each camera individually (baseline) ---
    print(f"\n{'#'*60}")
    print(f"  PHASE 1: Individual camera test (MSMF, one at a time)")
    print(f"{'#'*60}")

    individual_ok = []
    for cam_id in args.cameras:
        stats = test_backend("MSMF", cv2.CAP_MSMF, [cam_id], 5, args.interval)
        s = stats.get(cam_id)
        if s and s.opened and s.success_rate > 90:
            individual_ok.append(cam_id)
            print(f"  cam{cam_id}: OK ({s.success_rate:.0f}% success)")
        else:
            print(f"  cam{cam_id}: FAILED")
            if s:
                print(s.summary())

    if len(individual_ok) < 2:
        print("\n  Less than 2 cameras work individually. Cannot test parallel.")
        return

    # --- Test 2: All cameras parallel with MSMF ---
    print(f"\n{'#'*60}")
    print(f"  PHASE 2: Parallel camera test (MSMF, all at once)")
    print(f"{'#'*60}")

    msmf_results = test_backend("MSMF", cv2.CAP_MSMF, individual_ok,
                                 args.duration, args.interval)
    print("\n  MSMF Parallel Results:")
    for cam_id in sorted(msmf_results):
        print(msmf_results[cam_id].summary())

    # --- Test 3: DSHOW individual (check if index works at all) ---
    print(f"\n{'#'*60}")
    print(f"  PHASE 3: DSHOW individual test")
    print(f"{'#'*60}")

    dshow_ok = []
    for cam_id in individual_ok:
        stats = test_backend("DSHOW", cv2.CAP_DSHOW, [cam_id], 5, args.interval)
        s = stats.get(cam_id)
        if s and s.opened and s.success_rate > 90:
            dshow_ok.append(cam_id)
            print(f"  cam{cam_id}: OK ({s.success_rate:.0f}% success)")
        else:
            print(f"  cam{cam_id}: FAILED")
            if s:
                print(s.summary())

    # --- Test 4: DSHOW parallel (if individual works) ---
    if len(dshow_ok) >= 2:
        print(f"\n{'#'*60}")
        print(f"  PHASE 4: Parallel camera test (DSHOW, all at once)")
        print(f"{'#'*60}")

        dshow_results = test_backend("DSHOW", cv2.CAP_DSHOW, dshow_ok,
                                      args.duration, args.interval)
        print("\n  DSHOW Parallel Results:")
        for cam_id in sorted(dshow_results):
            print(dshow_results[cam_id].summary())
    else:
        print(f"\n  DSHOW: Only {len(dshow_ok)} camera(s) work by index. Skipping parallel test.")
        dshow_results = {}

    # --- Test 5: AUTO backend parallel ---
    print(f"\n{'#'*60}")
    print(f"  PHASE 5: Parallel camera test (AUTO/default backend)")
    print(f"{'#'*60}")

    auto_results = test_backend("AUTO", cv2.CAP_ANY, individual_ok,
                                 args.duration, args.interval)
    print("\n  AUTO Parallel Results:")
    for cam_id in sorted(auto_results):
        print(auto_results[cam_id].summary())

    # --- Final verdict ---
    print(f"\n{'#'*60}")
    print(f"  FINAL VERDICT")
    print(f"{'#'*60}")

    def judge(results: dict) -> str:
        if not results:
            return "NOT_TESTED"
        opened = sum(1 for s in results.values() if s.opened)
        if opened < 2:
            return "FAILED (can't open multiple cameras)"
        rates = [s.success_rate for s in results.values() if s.opened]
        min_rate = min(rates) if rates else 0
        if min_rate >= 95:
            return "STABLE"
        elif min_rate >= 70:
            return "UNSTABLE"
        else:
            return "FAILED"

    msmf_verdict = judge(msmf_results)
    dshow_verdict = judge(dshow_results)
    auto_verdict = judge(auto_results)

    print(f"  MSMF parallel:  {msmf_verdict}")
    print(f"  DSHOW parallel: {dshow_verdict}")
    print(f"  AUTO parallel:  {auto_verdict}")

    if msmf_verdict == "STABLE":
        print("\n  >>> Recommendation: Use MSMF, remove exclusive model (Plan A)")
    elif dshow_verdict == "STABLE":
        print("\n  >>> Recommendation: Switch to DSHOW (Plan A2)")
    elif auto_verdict == "STABLE":
        print("\n  >>> Recommendation: Use AUTO backend")
    elif msmf_verdict == "UNSTABLE" or auto_verdict == "UNSTABLE":
        print("\n  >>> Recommendation: Keep exclusive model, optimize queue (Plan B)")
        print("      Or investigate USB bandwidth (try lower resolution)")
    else:
        print("\n  >>> Recommendation: Keep exclusive model (Plan B)")


if __name__ == "__main__":
    main()
