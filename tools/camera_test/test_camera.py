"""Test: Can grab() flush the DSHOW buffer and get a fresh frame?

Saves images to disk so you can visually verify stale vs fresh.

Instructions:
  1. Run the script
  2. When it says "MOVE SOMETHING IN FRONT OF CAMERA NOW", wave your hand
     or put an object in view within the 5 second window
  3. Compare the saved images:
     - flush_1_baseline.jpg     = before idle (should show original scene)
     - flush_2_stale.jpg        = direct read after idle (stale frame from buffer)
     - flush_3_after_grab.jpg   = after grab() flush (should show your hand/object if flush works)
     - flush_4_reopen.jpg       = after close+reopen (guaranteed fresh, for comparison)
"""
import cv2
import time
import os

CAM = 0
BACKEND = cv2.CAP_DSHOW
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def save(name, frame):
    path = os.path.join(OUT_DIR, name)
    cv2.imwrite(path, frame)
    print("  Saved: %s" % name)


def main():
    print("=" * 60)
    print("DSHOW Buffer Flush Test (camera %d)" % CAM)
    print("=" * 60)

    # Step 1: Open and take baseline
    print("\n[1] Opening camera and capturing baseline...")
    cap = cv2.VideoCapture(CAM, BACKEND)
    if not cap.isOpened():
        print("  FAILED to open camera %d" % CAM)
        return
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    time.sleep(0.3)
    for _ in range(5):
        cap.read()
    ret, baseline = cap.read()
    if not ret:
        print("  FAILED to read baseline")
        cap.release()
        return
    save("flush_1_baseline.jpg", baseline)

    # Step 2: Idle period — user changes the scene
    print("\n[2] >>> MOVE SOMETHING IN FRONT OF CAMERA NOW <<<")
    print("    You have 5 seconds...")
    for i in range(5, 0, -1):
        print("    %d..." % i)
        time.sleep(1)
    print("    OK, hands off. Testing reads now.\n")

    # Step 3: Direct read (should be stale — shows original scene, not hand)
    print("[3] Direct read (no flush)...")
    t0 = time.perf_counter()
    ret, stale = cap.read()
    t1 = time.perf_counter()
    print("  Time: %.1fms" % ((t1 - t0) * 1000))
    if ret:
        save("flush_2_stale.jpg", stale)

    # Step 4: Flush by grabbing until slow, then read
    print("\n[4] Flushing buffer with grab() (max 200)...")
    time.sleep(3)
    print("    (sleeping 3s to re-accumulate buffer)")

    t0 = time.perf_counter()
    flush_count = 0
    grab_times = []
    while flush_count < 200:
        gt0 = time.perf_counter()
        cap.grab()
        gt1 = time.perf_counter()
        grab_ms = (gt1 - gt0) * 1000
        grab_times.append(grab_ms)
        flush_count += 1
        # A slow grab (>15ms) means buffer is empty, waiting for real frame from sensor
        if grab_ms > 15:
            print("  Slow grab detected at frame %d: %.1fms (buffer likely empty)" % (flush_count, grab_ms))
            break

    ret, flushed = cap.read()
    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000

    fast_count = sum(1 for t in grab_times if t < 5)
    slow_count = sum(1 for t in grab_times if t >= 15)
    print("  Grabbed %d frames: %d fast (<5ms), %d slow (>15ms)" % (flush_count, fast_count, slow_count))
    print("  Total flush+read time: %.0fms" % total_ms)
    if ret:
        save("flush_3_after_grab.jpg", flushed)

    # Step 5: Close and reopen (guaranteed fresh, for visual comparison)
    print("\n[5] Close + reopen (capture_fresh approach, guaranteed fresh)...")
    cap.release()
    t0 = time.perf_counter()
    cap = cv2.VideoCapture(CAM, BACKEND)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    time.sleep(0.15)
    for _ in range(2):
        cap.read()
    ret, reopened = cap.read()
    t1 = time.perf_counter()
    print("  Time: %.0fms" % ((t1 - t0) * 1000))
    if ret:
        save("flush_4_reopen.jpg", reopened)
    cap.release()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print("Compare the images in: %s" % OUT_DIR)
    print()
    print("  flush_1_baseline.jpg   = original scene (before you moved)")
    print("  flush_2_stale.jpg      = direct read after idle (stale?)")
    print("  flush_3_after_grab.jpg = after %d grab()s (fresh?)" % flush_count)
    print("  flush_4_reopen.jpg     = after close+reopen (definitely fresh)")
    print()
    print("If flush_3 shows the CURRENT scene (same as flush_4),")
    print("then grab() flush WORKS and we can avoid the 950ms reopen.")
    print("If flush_3 looks like flush_1/flush_2 (old scene),")
    print("then grab() flush FAILED and we stay with reopen approach.")


if __name__ == "__main__":
    main()
