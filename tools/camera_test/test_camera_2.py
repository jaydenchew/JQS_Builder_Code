"""Test all available OpenCV backends for simultaneous multi-camera support.

Tests: MSMF, FFmpeg, GStreamer with various resolutions and formats.

Run:  python tools/camera_backend_test.py
"""
import cv2
import time
import sys


CAM_A = 0
CAM_B = 1


def check_backends():
    """Check which backends are available in this OpenCV build."""
    print("=" * 60)
    print("OpenCV Build Info")
    print("=" * 60)
    print("Version: %s" % cv2.__version__)

    info = cv2.getBuildInformation()
    sections = ["Video I/O", "DirectShow", "MSMF", "FFmpeg", "GStreamer"]
    for section in sections:
        for line in info.split("\n"):
            if section.lower() in line.lower():
                print("  %s" % line.strip())
    print()


def try_open_both(backend_id, backend_name, props=None):
    """Try to open both cameras with given backend and optional properties.
    Returns (success, cap_a, cap_b, details)"""
    try:
        cap_a = cv2.VideoCapture(CAM_A, backend_id)
    except Exception as e:
        return False, None, None, "Camera %d open error: %s" % (CAM_A, e)

    if not cap_a.isOpened():
        return False, None, None, "Camera %d failed to open" % CAM_A

    if props:
        for prop, val in props.items():
            cap_a.set(prop, val)

    try:
        cap_b = cv2.VideoCapture(CAM_B, backend_id)
    except Exception as e:
        cap_a.release()
        return False, None, None, "Camera %d open error: %s" % (CAM_B, e)

    if not cap_b.isOpened():
        cap_a.release()
        return False, None, None, "Camera %d failed to open (while %d is open)" % (CAM_B, CAM_A)

    if props:
        for prop, val in props.items():
            cap_b.set(prop, val)

    return True, cap_a, cap_b, "Both opened"


def test_read_both(cap_a, cap_b, warmup=3):
    """Try to read frames from both open cameras."""
    time.sleep(0.3)
    for _ in range(warmup):
        cap_a.grab()
        cap_b.grab()

    ret_a, frame_a = cap_a.read()
    ret_b, frame_b = cap_b.read()

    details = "cam%d: read=%s %s | cam%d: read=%s %s" % (
        CAM_A, ret_a, str(frame_a.shape) if ret_a else "None",
        CAM_B, ret_b, str(frame_b.shape) if ret_b else "None",
    )
    return ret_a and ret_b, details


def run_test(name, backend_id, props=None):
    """Run a complete open+read test for a backend configuration."""
    props_str = ""
    if props:
        parts = []
        prop_names = {
            cv2.CAP_PROP_FRAME_WIDTH: "width",
            cv2.CAP_PROP_FRAME_HEIGHT: "height",
            cv2.CAP_PROP_FOURCC: "fourcc",
            cv2.CAP_PROP_FPS: "fps",
            cv2.CAP_PROP_BUFFERSIZE: "buffersize",
        }
        for p, v in props.items():
            pname = prop_names.get(p, str(p))
            parts.append("%s=%s" % (pname, int(v) if v == int(v) else v))
        props_str = " (%s)" % ", ".join(parts)

    print("  %-45s" % (name + props_str), end="", flush=True)

    opened, cap_a, cap_b, open_detail = try_open_both(backend_id, name, props)
    if not opened:
        print("FAIL (open): %s" % open_detail)
        return False

    read_ok, read_detail = test_read_both(cap_a, cap_b)
    cap_a.release()
    cap_b.release()

    if read_ok:
        print("PASS  %s" % read_detail)
    else:
        print("FAIL (read): %s" % read_detail)

    return read_ok


def test_msmf():
    """Test MSMF backend with various configurations."""
    print("\n" + "=" * 60)
    print("TEST: MSMF (Media Foundation)")
    print("=" * 60)

    mjpeg = cv2.VideoWriter.fourcc(*"MJPG")

    configs = [
        ("MSMF default", {}),
        ("MSMF 320x240", {cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
        ("MSMF 160x120", {cv2.CAP_PROP_FRAME_WIDTH: 160, cv2.CAP_PROP_FRAME_HEIGHT: 120}),
        ("MSMF MJPEG", {cv2.CAP_PROP_FOURCC: mjpeg}),
        ("MSMF MJPEG 320x240", {cv2.CAP_PROP_FOURCC: mjpeg, cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
        ("MSMF 15fps", {cv2.CAP_PROP_FPS: 15}),
        ("MSMF MJPEG 15fps", {cv2.CAP_PROP_FOURCC: mjpeg, cv2.CAP_PROP_FPS: 15}),
        ("MSMF 320x240 15fps", {cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240, cv2.CAP_PROP_FPS: 15}),
        ("MSMF MJPEG 320x240 15fps", {cv2.CAP_PROP_FOURCC: mjpeg, cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240, cv2.CAP_PROP_FPS: 15}),
    ]

    results = []
    for name, props in configs:
        ok = run_test(name, cv2.CAP_MSMF, props if props else None)
        results.append((name, ok))
        time.sleep(0.5)

    return results


def test_ffmpeg():
    """Test FFmpeg backend."""
    print("\n" + "=" * 60)
    print("TEST: FFmpeg")
    print("=" * 60)

    mjpeg = cv2.VideoWriter.fourcc(*"MJPG")

    # Test by index
    configs = [
        ("FFmpeg default", {}),
        ("FFmpeg 320x240", {cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
        ("FFmpeg MJPEG", {cv2.CAP_PROP_FOURCC: mjpeg}),
        ("FFmpeg MJPEG 320x240", {cv2.CAP_PROP_FOURCC: mjpeg, cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
    ]

    results = []
    for name, props in configs:
        ok = run_test(name, cv2.CAP_FFMPEG, props if props else None)
        results.append((name, ok))
        time.sleep(0.5)

    return results


def test_gstreamer():
    """Test GStreamer backend."""
    print("\n" + "=" * 60)
    print("TEST: GStreamer")
    print("=" * 60)

    # Check if GStreamer is available
    info = cv2.getBuildInformation()
    if "gstreamer" not in info.lower() or "no" in [
        line.split(":")[-1].strip().lower()
        for line in info.split("\n")
        if "gstreamer" in line.lower()
    ]:
        print("  GStreamer not available in this OpenCV build. Skipped.")
        return []

    configs = [
        ("GStreamer default", {}),
        ("GStreamer 320x240", {cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
    ]

    results = []
    for name, props in configs:
        ok = run_test(name, cv2.CAP_GSTREAMER, props if props else None)
        results.append((name, ok))
        time.sleep(0.5)

    return results


def test_dshow_reference():
    """DSHOW as reference (expected to fail for simultaneous)."""
    print("\n" + "=" * 60)
    print("TEST: DSHOW (reference, expected fail)")
    print("=" * 60)

    mjpeg = cv2.VideoWriter.fourcc(*"MJPG")

    configs = [
        ("DSHOW default", {}),
        ("DSHOW MJPEG", {cv2.CAP_PROP_FOURCC: mjpeg}),
        ("DSHOW 320x240", {cv2.CAP_PROP_FRAME_WIDTH: 320, cv2.CAP_PROP_FRAME_HEIGHT: 240}),
    ]

    results = []
    for name, props in configs:
        ok = run_test(name, cv2.CAP_DSHOW, props if props else None)
        results.append((name, ok))
        time.sleep(0.5)

    return results


if __name__ == "__main__":
    check_backends()

    all_results = []
    all_results.extend(test_dshow_reference())
    all_results.extend(test_msmf())
    all_results.extend(test_ffmpeg())
    all_results.extend(test_gstreamer())

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = [(name, ok) for name, ok in all_results if ok]
    failed = [(name, ok) for name, ok in all_results if not ok]

    if passed:
        print("\nPASSED (simultaneous open + read):")
        for name, _ in passed:
            print("  + %s" % name)
    else:
        print("\nNo backend supports simultaneous cameras on this machine.")

    print("\nFAILED:")
    for name, _ in failed:
        print("  - %s" % name)

    if passed:
        print("\nRECOMMENDATION: Switch to '%s' backend." % passed[0][0])
        print("This would allow each arm to keep its own camera open.")
        print("No exclusive model, no global lock, no 950ms reopen needed.")
    else:
        print("\nRECOMMENDATION: Stay with exclusive model, fix capture_fresh() bug.")
