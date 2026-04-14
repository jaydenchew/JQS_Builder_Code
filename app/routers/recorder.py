"""Visual flow recording + arm test endpoints — supports multi-arm selection."""
from fastapi import APIRouter
from app import arm_client, calibration, database
from app.worker_manager import manager

router = APIRouter(prefix="/api/recorder", tags=["recorder"])


def _get_arm(arm_id: int = None):
    if arm_id is not None:
        worker = manager.get_worker(arm_id)
        if worker:
            return worker.arm_client
        return None
    return arm_client


def _arm_or_error(arm_id):
    a = _get_arm(arm_id)
    if a is None:
        return None, {"success": False, "error": "No worker for arm %s. Resume from Dashboard first." % arm_id}
    return a, None


@router.get("/arm/status")
async def arm_status(arm_id: int = None):
    a = _get_arm(arm_id)
    if a is None:
        return {"connected": False, "x": 0, "y": 0, "worker_status": "no_worker"}
    x, y = a.get_position() if a.is_connected() else (0, 0)
    worker_status = None
    if arm_id is not None:
        worker = manager.get_worker(arm_id)
        if worker:
            worker_status = worker.get_status()
    return {"connected": a.is_connected(), "x": x, "y": y, "worker_status": worker_status}


@router.post("/arm/connect")
async def arm_connect(arm_id: int = None):
    if arm_id is not None:
        worker = manager.get_worker(arm_id)
        if not worker:
            return {"success": False, "error": "No worker for arm %s. Resume from Dashboard first." % arm_id}
        if worker.get_status() in ("idle", "busy"):
            return {"success": False, "error": "Worker is active (%s). Pause or set offline from Dashboard first." % worker.get_status()}
    a = _get_arm(arm_id)
    if a is None:
        return {"success": False, "error": "Arm not found"}
    try:
        if a.is_connected():
            return {"success": True, "note": "Already connected"}
        a.open_port()
        a.motor_lock()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/disconnect")
async def arm_disconnect(arm_id: int = None):
    a, err = _arm_or_error(arm_id)
    if err:
        return err
    try:
        a.reset_to_origin()
        a.close_port()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/move")
async def arm_move(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    try:
        a.move(data["x"], data["y"])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/click")
async def arm_click(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    try:
        a.click(data["x"], data["y"])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/swipe")
async def arm_swipe(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    try:
        a.swipe(data["start_x"], data["start_y"], data["end_x"], data["end_y"])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/click-pixel")
async def arm_click_pixel(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    station_id = data["station_id"]
    px, py = data["px"], data["py"]
    cur_x, cur_y = data["cur_arm_x"], data["cur_arm_y"]
    if not await calibration.is_calibrated(station_id):
        return {"error": "Station %d not calibrated" % station_id}
    ax, ay = await calibration.pixel_to_arm(station_id, px, py, cur_x, cur_y)
    a.click(ax, ay)
    return {"success": True, "arm_x": ax, "arm_y": ay}


@router.post("/arm/move-pixel")
async def arm_move_pixel(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    station_id = data["station_id"]
    px, py = data["px"], data["py"]
    cur_x, cur_y = data["cur_arm_x"], data["cur_arm_y"]
    if not await calibration.is_calibrated(station_id):
        return {"error": "Station %d not calibrated" % station_id}
    ax, ay = await calibration.pixel_to_arm(station_id, px, py, cur_x, cur_y)
    a.move(ax, ay)
    return {"success": True, "arm_x": ax, "arm_y": ay}


@router.post("/arm/press")
async def arm_press(arm_id: int = None):
    a, err = _arm_or_error(arm_id)
    if err:
        return err
    try:
        a.press()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/arm/lift")
async def arm_lift(arm_id: int = None):
    a, err = _arm_or_error(arm_id)
    if err:
        return err
    try:
        a.lift()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/test-step")
async def test_step(data: dict):
    a, err = _arm_or_error(data.get("arm_id"))
    if err:
        return err
    action = data["action_type"]
    try:
        if not a.is_connected():
            a.open_port()
            a.motor_lock()

        if action == "CLICK":
            a.click(data["x"], data["y"])
        elif action == "SWIPE":
            a.swipe(data["start_x"], data["start_y"], data["end_x"], data["end_y"])
        elif action == "ARM_MOVE":
            a.move(data["x"], data["y"])
        elif action == "press":
            a.press()
        elif action == "lift":
            a.lift()
        else:
            return {"success": False, "error": "Cannot test action: %s" % action}

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/record-click")
async def record_click(data: dict):
    station_id = data["station_id"]
    bank_code = data["bank_code"]
    element_key = data["element_key"]
    px, py = data["px"], data["py"]
    cur_x, cur_y = data.get("cur_arm_x", 0), data.get("cur_arm_y", 0)

    ax, ay = await calibration.pixel_to_arm(station_id, px, py, cur_x, cur_y)

    existing = await database.fetchone(
        "SELECT id FROM ui_elements WHERE bank_code=%s AND station_id=%s AND element_key=%s",
        (bank_code, station_id, element_key)
    )
    if existing:
        await database.execute("UPDATE ui_elements SET x=%s, y=%s WHERE id=%s", (ax, ay, existing["id"]))
    else:
        await database.execute(
            "INSERT INTO ui_elements (bank_code, station_id, element_key, x, y) VALUES (%s,%s,%s,%s,%s)",
            (bank_code, station_id, element_key, ax, ay)
        )

    return {"success": True, "arm_x": ax, "arm_y": ay, "element_key": element_key}


@router.post("/record-swipe")
async def record_swipe(data: dict):
    station_id = data["station_id"]
    bank_code = data["bank_code"]
    swipe_key = data["swipe_key"]
    start_px, start_py = data["start_px"], data["start_py"]
    end_px, end_py = data["end_px"], data["end_py"]
    cur_x, cur_y = data.get("cur_arm_x", 0), data.get("cur_arm_y", 0)

    sx, sy = await calibration.pixel_to_arm(station_id, start_px, start_py, cur_x, cur_y)
    ex, ey = await calibration.pixel_to_arm(station_id, end_px, end_py, cur_x, cur_y)

    existing = await database.fetchone(
        "SELECT id FROM swipe_actions WHERE bank_code=%s AND station_id=%s AND swipe_key=%s",
        (bank_code, station_id, swipe_key)
    )
    if existing:
        await database.execute(
            "UPDATE swipe_actions SET start_x=%s, start_y=%s, end_x=%s, end_y=%s WHERE id=%s",
            (sx, sy, ex, ey, existing["id"])
        )
    else:
        await database.execute(
            "INSERT INTO swipe_actions (bank_code, station_id, swipe_key, start_x, start_y, end_x, end_y) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (bank_code, station_id, swipe_key, sx, sy, ex, ey)
        )

    return {"success": True, "start": {"x": sx, "y": sy}, "end": {"x": ex, "y": ey}}


@router.post("/record-key")
async def record_key(data: dict):
    station_id = data["station_id"]
    bank_code = data["bank_code"]
    keyboard_type = data["keyboard_type"]
    key_char = data["key_char"]
    px, py = data["px"], data["py"]
    cur_x, cur_y = data.get("cur_arm_x", 0), data.get("cur_arm_y", 0)

    ax, ay = await calibration.pixel_to_arm(station_id, px, py, cur_x, cur_y)

    existing = await database.fetchone(
        "SELECT id FROM keymaps WHERE bank_code=%s AND station_id=%s AND keyboard_type=%s AND key_char=%s",
        (bank_code, station_id, keyboard_type, key_char)
    )
    if existing:
        await database.execute("UPDATE keymaps SET x=%s, y=%s WHERE id=%s", (ax, ay, existing["id"]))
    else:
        await database.execute(
            "INSERT INTO keymaps (bank_code, station_id, keyboard_type, key_char, x, y) VALUES (%s,%s,%s,%s,%s,%s)",
            (bank_code, station_id, keyboard_type, key_char, ax, ay)
        )

    return {"success": True, "arm_x": ax, "arm_y": ay, "key": key_char}
