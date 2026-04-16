"""Test: Can two separate PROCESSES each open their own camera simultaneously?

If DSHOW's limitation is per-process (not system-wide), this should work.
Each subprocess opens one camera independently.

Run:  python tools/camera_process_test.py
"""
import multiprocessing
import time
import sys


def camera_worker(cam_id, result_queue):
    """Run in a separate process: open one camera, read frames, report result."""
    import cv2

    pid = multiprocessing.current_process().pid
    print("[PID %d] Opening camera %d (DSHOW)..." % (pid, cam_id))

    cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[PID %d] Camera %d: FAILED to open" % (pid, cam_id))
        result_queue.put({"cam_id": cam_id, "pid": pid, "opened": False, "read": False})
        return

    print("[PID %d] Camera %d: opened OK" % (pid, cam_id))

    # Signal that camera is open
    result_queue.put({"cam_id": cam_id, "pid": pid, "opened": True, "read": None, "phase": "opened"})

    # Wait a bit for the other process to also open
    time.sleep(2)

    # Try reading
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    time.sleep(0.3)
    for _ in range(3):
        cap.read()

    ret, frame = cap.read()
    shape = str(frame.shape) if ret else "None"
    print("[PID %d] Camera %d: read=%s shape=%s" % (pid, cam_id, ret, shape))

    # Keep camera open for a few more seconds so the other process can verify
    time.sleep(3)

    cap.release()
    print("[PID %d] Camera %d: released" % (pid, cam_id))

    result_queue.put({"cam_id": cam_id, "pid": pid, "opened": True, "read": ret, "shape": shape, "phase": "done"})


def main():
    print("=" * 60)
    print("Multi-Process Camera Test")
    print("=" * 60)
    print("Main PID: %d" % multiprocessing.current_process().pid)
    print("Testing: Process A opens Camera 0, Process B opens Camera 1")
    print("If DSHOW limit is per-process, both should succeed.")
    print()

    result_queue = multiprocessing.Queue()

    p_a = multiprocessing.Process(target=camera_worker, args=(0, result_queue))
    p_b = multiprocessing.Process(target=camera_worker, args=(1, result_queue))

    # Start both at the same time
    p_a.start()
    p_b.start()

    p_a.join(timeout=15)
    p_b.join(timeout=15)

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get_nowait())

    # Show final results
    final = [r for r in results if r.get("phase") == "done"]

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    for r in final:
        status = "PASS" if r["read"] else "FAIL"
        print("  Camera %d (PID %d): open=%s read=%s  %s" % (
            r["cam_id"], r["pid"], r["opened"], r["read"], status))

    all_pass = all(r["read"] for r in final)
    print()
    if all_pass:
        print("PASS: Both cameras work in separate processes!")
        print("DSHOW limitation is per-process, not system-wide.")
        print("Process isolation could enable true parallel camera access.")
    elif len(final) < 2:
        print("INCOMPLETE: Only got %d results (timeout?)" % len(final))
    else:
        print("FAIL: Separate processes did NOT help.")
        print("DSHOW limitation is system-wide (driver/hardware level).")
        print("Fix capture_fresh() within the existing exclusive model.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
