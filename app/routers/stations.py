"""CRUD: arms, stations, phones — full create/read/update/delete"""
from fastapi import APIRouter
from app import database
from app.worker_manager import manager

router = APIRouter(prefix="/api/stations", tags=["stations"])


# === Arms ===

@router.get("/arms")
async def list_arms():
    return await database.fetchall("SELECT * FROM arms ORDER BY id")


@router.post("/arms")
async def create_arm(data: dict):
    row_id = await database.execute(
        """INSERT INTO arms (name, com_port, service_url, z_down, camera_id, active, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'idle')""",
        (data["name"], data["com_port"], data.get("service_url", "http://127.0.0.1:8082/MyWcfService/getstring"),
         data.get("z_down", 10), data.get("camera_id", 0), data.get("active", True))
    )
    if data.get("active", True):
        ok = await manager.add_worker(row_id)
        if not ok:
            return {"success": False, "id": row_id, "error": "Arm created in DB but worker failed to start"}
    return {"success": True, "id": row_id}


@router.put("/arms/{arm_id}")
async def update_arm(arm_id: int, data: dict):
    allowed = {"name", "com_port", "service_url", "z_down", "camera_id", "active", "status"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE arms SET %s WHERE id = %%s" % sets, (*fields.values(), arm_id))

    if "active" in fields:
        if not data["active"]:
            await manager.set_offline(arm_id)
        else:
            ok = await manager.resume(arm_id)
            if not ok:
                return {"success": False, "error": "DB updated but worker failed to start — arm not found in DB"}

    return {"success": True}


@router.delete("/arms/{arm_id}")
async def delete_arm(arm_id: int):
    stations = await database.fetchall("SELECT id FROM stations WHERE arm_id = %s", (arm_id,))
    if stations:
        return {"error": "Cannot delete arm with existing stations. Remove stations first."}

    async with manager._lock:
        await manager._remove_worker(arm_id)

    await database.execute("DELETE FROM arms WHERE id = %s", (arm_id,))
    return {"success": True}


# === Stations ===

@router.get("/")
async def list_stations():
    return await database.fetchall(
        "SELECT s.*, a.name as arm_name FROM stations s JOIN arms a ON s.arm_id = a.id ORDER BY s.id"
    )


@router.post("/")
async def create_station(data: dict):
    try:
        row_id = await database.execute(
            "INSERT INTO stations (arm_id, name, x_offset, status) VALUES (%s, %s, %s, 'active')",
            (data["arm_id"], data["name"], data.get("x_offset", 0))
        )
        return {"success": True, "id": row_id}
    except Exception as e:
        if "Duplicate" in str(e):
            return {"success": False, "error": "Station already exists (duplicate key)"}
        return {"success": False, "error": str(e)}


@router.put("/{station_id}")
async def update_station(station_id: int, data: dict):
    allowed = {"name", "x_offset", "stall_photo_x", "stall_photo_y", "status", "arm_id"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE stations SET %s WHERE id = %%s" % sets, (*fields.values(), station_id))
    return {"success": True}


@router.delete("/{station_id}")
async def delete_station(station_id: int):
    for table, col in [
        ("phones", "station_id"),
        ("bank_apps", "station_id"),
        ("ui_elements", "station_id"),
        ("keymaps", "station_id"),
        ("swipe_actions", "station_id"),
        ("keyboard_configs", "station_id"),
        ("calibrations", "station_id"),
    ]:
        rows = await database.fetchall(
            "SELECT id FROM `%s` WHERE `%s` = %%s LIMIT 1" % (table, col), (station_id,)
        )
        if rows:
            return {"error": "Cannot delete station: still referenced by table '%s'" % table}
    await database.execute("DELETE FROM stations WHERE id = %s", (station_id,))
    return {"success": True}


# === Phones ===

@router.get("/phones")
async def list_phones():
    return await database.fetchall(
        "SELECT p.*, s.name as station_name, s.arm_id, a.name as arm_name "
        "FROM phones p JOIN stations s ON p.station_id = s.id JOIN arms a ON s.arm_id = a.id ORDER BY p.id"
    )


@router.post("/phones")
async def create_phone(data: dict):
    row_id = await database.execute(
        "INSERT INTO phones (station_id, name, model, status) VALUES (%s, %s, %s, 'active')",
        (data["station_id"], data["name"], data.get("model", ""))
    )
    return {"success": True, "id": row_id}


@router.put("/phones/{phone_id}")
async def update_phone(phone_id: int, data: dict):
    allowed = {"name", "model", "status", "station_id"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE phones SET %s WHERE id = %%s" % sets, (*fields.values(), phone_id))
    return {"success": True}


@router.delete("/phones/{phone_id}")
async def delete_phone(phone_id: int):
    apps = await database.fetchall("SELECT id FROM bank_apps WHERE phone_id = %s LIMIT 1", (phone_id,))
    if apps:
        return {"error": "Cannot delete phone with existing bank apps. Remove bank apps first."}
    await database.execute("DELETE FROM phones WHERE id = %s", (phone_id,))
    return {"success": True}
