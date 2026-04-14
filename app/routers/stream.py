"""Camera MJPEG stream endpoint — supports multi-arm camera selection.

Default (no arm_id): uses module-level default camera (backward compat with Builder).
With arm_id parameter: uses the worker's camera instance.
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from app import camera
from app.worker_manager import manager

router = APIRouter(prefix="/api", tags=["camera"])


def _get_cam(arm_id: int = None):
    if arm_id is not None:
        worker = manager.get_worker(arm_id)
        if worker:
            return worker.camera
        return None
    return camera


@router.get("/stream")
async def video_stream(arm_id: int = None):
    cam = _get_cam(arm_id)
    if cam is None:
        return JSONResponse({"error": "No worker for arm %s. Resume from Dashboard." % arm_id}, status_code=200)
    return StreamingResponse(
        cam.generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/snapshot")
async def snapshot(arm_id: int = None):
    import cv2
    import base64
    cam = _get_cam(arm_id)
    if cam is None:
        return {"error": "No worker for arm %s" % arm_id}
    frame = cam.capture_rotated()
    if frame is None:
        return {"error": "Camera not available"}
    _, buffer = cv2.imencode(".jpg", frame)
    b64 = base64.b64encode(buffer).decode("utf-8")
    return {"image": b64, "width": frame.shape[1], "height": frame.shape[0]}


@router.post("/camera/open")
async def open_camera(arm_id: int = None):
    cam = _get_cam(arm_id)
    if cam is None:
        return {"success": False, "error": "No worker for arm %s" % arm_id}
    cam.stream_start()
    return {"success": True}


@router.post("/camera/close")
async def close_camera(arm_id: int = None):
    cam = _get_cam(arm_id)
    if cam is None:
        return {"success": False, "error": "No worker for arm %s" % arm_id}
    cam.stream_stop()
    return {"success": True}


@router.get("/camera/status")
async def camera_status(arm_id: int = None):
    cam = _get_cam(arm_id)
    if cam is None:
        return {"open": False, "error": "No worker for arm %s" % arm_id}
    return {"open": cam.is_open()}
