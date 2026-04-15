"""Camera capture + MJPEG stream — class-based for multi-instance support.

Camera class: each arm gets its own camera instance with independent device.

Concurrency design:
- _enabled  : controlled ONLY by the Worker (enable on run, disable on stop).
              Gates whether capture_frame / camera_open work.
- _streaming: controlled ONLY by the Recorder stream API.
              Gates generate_mjpeg loop; does NOT affect Worker captures.
- _init_lock: class-level (global) lock serialising cv2.VideoCapture() init
              across all Camera instances to prevent concurrent open conflicts.
- _lock     : per-instance lock protecting self._camera read/write.

Backend: DSHOW (CAP_DSHOW) — tested: all 3 cameras work individually by index,
reads are ~0.8ms (vs MSMF 2.9ms). Neither DSHOW nor MSMF can open multiple
cameras simultaneously on Windows; DSHOW is chosen for faster read performance.

Exclusive model: _active_instance tracks which Camera currently holds hardware.
camera_open() automatically releases the previous camera before opening a new
one, guaranteeing only one VideoCapture exists at any time.

Module-level functions: backward-compatible wrappers using a default instance.
"""
import cv2
import base64
import time
import logging
import threading
from app.config import CAMERA_ID, CAMERA_WARMUP

logger = logging.getLogger(__name__)

_BACKEND = cv2.CAP_DSHOW


class Camera:
    """Per-arm camera instance.  Only ONE instance holds hardware at a time."""

    _init_lock = threading.Lock()
    _active_instance = None

    def __init__(self, camera_id: int = CAMERA_ID, warmup: int = CAMERA_WARMUP):
        self.camera_id = camera_id
        self.warmup = warmup
        self._camera = None
        self._lock = threading.Lock()
        self._enabled = False
        self._streaming = False
        self._consecutive_failures = 0

    def camera_open(self):
        if not self._enabled:
            return False
        with self._lock:
            if self._camera is not None:
                return True
        with Camera._init_lock:
            with self._lock:
                if self._camera is not None:
                    return True
            prev = Camera._active_instance
            if prev is not None and prev is not self:
                logger.info("Releasing camera %d before opening camera %d",
                            prev.camera_id, self.camera_id)
                prev._release_hw()
            with self._lock:
                self._camera = cv2.VideoCapture(self.camera_id, _BACKEND)
                if not self._camera.isOpened():
                    logger.error("Cannot open camera %d", self.camera_id)
                    self._camera = None
                    return False
                self._camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                time.sleep(0.15)
                for _ in range(self.warmup):
                    self._camera.read()
                self._consecutive_failures = 0
                Camera._active_instance = self
                logger.info("Camera opened: %d (DSHOW)", self.camera_id)
                return True

    def _release_hw(self):
        """Release hardware (called internally during camera switch)."""
        with self._lock:
            if self._camera is not None:
                self._camera.release()
                self._camera = None
                logger.info("Camera %d released (switched away)", self.camera_id)

    def camera_enable(self):
        """Worker calls this once at run() start. Allows capture_frame to work."""
        self._enabled = True
        logger.info("Camera %d enabled", self.camera_id)

    def camera_disable(self):
        """Worker calls this at stop(). Releases hardware."""
        self._enabled = False
        self._streaming = False
        time.sleep(0.15)
        self.camera_close()

    def stream_start(self):
        """Recorder API: start MJPEG streaming. Ensures camera is open."""
        self._streaming = True
        if not self._enabled:
            self._enabled = True
        self.camera_open()
        logger.info("Camera %d stream started", self.camera_id)

    def stream_stop(self):
        """Recorder API: stop MJPEG streaming. Releases hardware so
        other cameras can be opened (exclusive model)."""
        self._streaming = False
        self.camera_close()
        logger.info("Camera %d stream stopped", self.camera_id)

    def capture_frame(self):
        if not self.camera_open():
            return None
        with self._lock:
            if self._camera is None:
                return None
            ret, frame = self._camera.read()
        if not ret:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 30:
                logger.error("Camera %d: %d consecutive read failures, closing for re-init",
                             self.camera_id, self._consecutive_failures)
                self.camera_close()
            return None
        self._consecutive_failures = 0
        return frame

    def capture_fresh(self):
        """Capture a guaranteed live frame by reopening the camera.
        DSHOW buffers frames internally and there is no reliable way to
        flush them, so we close + reopen to get a clean real-time frame.
        Camera is released immediately after capture to minimize the
        exclusive lock window for multi-arm concurrency."""
        with self._lock:
            if self._camera is not None:
                self._camera.release()
                self._camera = None
        with Camera._init_lock:
            with self._lock:
                self._camera = cv2.VideoCapture(self.camera_id, _BACKEND)
                if not self._camera.isOpened():
                    logger.error("Camera %d: reopen failed", self.camera_id)
                    self._camera = None
                    return None
                self._camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                time.sleep(0.15)
                for _ in range(self.warmup):
                    self._camera.read()
                ret, frame = self._camera.read()
                self._camera.release()
                self._camera = None
                Camera._active_instance = None
        if not ret:
            return None
        self._consecutive_failures = 0
        return frame

    def capture_rotated(self):
        frame = self.capture_frame()
        if frame is None:
            return None
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

    def capture_base64(self, fresh=True):
        frame = self.capture_fresh() if fresh else self.capture_frame()
        if frame is None:
            return None
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        _, buffer = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buffer).decode("utf-8")
        logger.info("Photo captured (rotated): %d bytes base64", len(b64))
        return b64

    def generate_mjpeg(self):
        fail_count = 0
        while self._streaming:
            frame = self.capture_rotated()
            if frame is None:
                fail_count += 1
                if fail_count >= 50:
                    logger.error("Camera %d: MJPEG stream stopped after %d consecutive failures",
                                 self.camera_id, fail_count)
                    self._streaming = False
                    break
                time.sleep(0.1)
                continue
            fail_count = 0
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
            time.sleep(0.05)

    def camera_close(self):
        with self._lock:
            if self._camera is not None:
                self._camera.release()
                self._camera = None
                if Camera._active_instance is self:
                    Camera._active_instance = None
                logger.info("Camera %d closed", self.camera_id)

    def is_open(self):
        return self._camera is not None


# === Module-level default instance (for Builder recorder/stream backward compat) ===

_default = Camera()


def camera_open():
    return _default.camera_open()

def camera_enable():
    return _default.camera_enable()

def camera_disable():
    return _default.camera_disable()

def stream_start():
    return _default.stream_start()

def stream_stop():
    return _default.stream_stop()

def capture_frame():
    return _default.capture_frame()

def capture_fresh():
    return _default.capture_fresh()

def capture_rotated():
    return _default.capture_rotated()

def capture_base64():
    return _default.capture_base64()

def generate_mjpeg():
    return _default.generate_mjpeg()

def camera_close():
    return _default.camera_close()

def is_open():
    return _default.is_open()
