"""CRUD: ui_elements, keymaps, swipe_actions, keyboard_configs"""
from fastapi import APIRouter
from app import database

router = APIRouter(prefix="/api/coords", tags=["coordinates"])


# === UI Elements ===

@router.get("/ui/{bank_code}/{station_id}")
async def list_ui_elements(bank_code: str, station_id: int):
    return await database.fetchall(
        "SELECT * FROM ui_elements WHERE bank_code=%s AND station_id=%s ORDER BY element_key",
        (bank_code, station_id)
    )


@router.post("/ui")
async def create_ui_element(data: dict):
    row_id = await database.execute(
        "INSERT INTO ui_elements (bank_code, station_id, element_key, x, y) VALUES (%s,%s,%s,%s,%s)",
        (data["bank_code"], data["station_id"], data["element_key"], data["x"], data["y"])
    )
    return {"success": True, "id": row_id}


@router.put("/ui/{element_id}")
async def update_ui_element(element_id: int, data: dict):
    allowed = {"bank_code", "element_key", "x", "y"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE ui_elements SET %s WHERE id = %%s" % sets, (*fields.values(), element_id))
    return {"success": True}


@router.delete("/ui/{element_id}")
async def delete_ui_element(element_id: int):
    await database.execute("DELETE FROM ui_elements WHERE id = %s", (element_id,))
    return {"success": True}


# === Keymaps ===

@router.get("/keymaps/{bank_code}/{station_id}")
async def list_keymaps(bank_code: str, station_id: int):
    return await database.fetchall(
        "SELECT * FROM keymaps WHERE bank_code=%s AND station_id=%s ORDER BY keyboard_type, key_char",
        (bank_code, station_id)
    )


@router.get("/keymaps/{bank_code}/{station_id}/{keyboard_type}")
async def list_keymap_by_type(bank_code: str, station_id: int, keyboard_type: str):
    return await database.fetchall(
        "SELECT * FROM keymaps WHERE bank_code=%s AND station_id=%s AND keyboard_type=%s ORDER BY key_char",
        (bank_code, station_id, keyboard_type)
    )


@router.post("/keymaps")
async def create_keymap(data: dict):
    row_id = await database.execute(
        "INSERT INTO keymaps (bank_code, station_id, keyboard_type, key_char, x, y) VALUES (%s,%s,%s,%s,%s,%s)",
        (data["bank_code"], data["station_id"], data["keyboard_type"], data["key_char"], data["x"], data["y"])
    )
    return {"success": True, "id": row_id}


@router.post("/keymaps/batch")
async def create_keymaps_batch(data: dict):
    bank_code = data["bank_code"]
    station_id = data["station_id"]
    keyboard_type = data["keyboard_type"]
    await database.execute(
        "DELETE FROM keymaps WHERE bank_code=%s AND station_id=%s AND keyboard_type=%s",
        (bank_code, station_id, keyboard_type)
    )
    for k in data["keys"]:
        await database.execute(
            "INSERT INTO keymaps (bank_code, station_id, keyboard_type, key_char, x, y) VALUES (%s,%s,%s,%s,%s,%s)",
            (bank_code, station_id, keyboard_type, k["char"], k["x"], k["y"])
        )
    return {"success": True, "count": len(data["keys"])}


@router.put("/keymaps/{keymap_id}")
async def update_keymap(keymap_id: int, data: dict):
    allowed = {"key_char", "x", "y"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE keymaps SET %s WHERE id = %%s" % sets, (*fields.values(), keymap_id))
    return {"success": True}


@router.delete("/keymaps/{keymap_id}")
async def delete_keymap(keymap_id: int):
    await database.execute("DELETE FROM keymaps WHERE id = %s", (keymap_id,))
    return {"success": True}


# === Swipe Actions ===

@router.get("/swipes/{bank_code}/{station_id}")
async def list_swipes(bank_code: str, station_id: int):
    return await database.fetchall(
        "SELECT * FROM swipe_actions WHERE bank_code=%s AND station_id=%s ORDER BY swipe_key",
        (bank_code, station_id)
    )


@router.post("/swipes")
async def create_swipe(data: dict):
    row_id = await database.execute(
        "INSERT INTO swipe_actions (bank_code, station_id, swipe_key, start_x, start_y, end_x, end_y) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (data["bank_code"], data["station_id"], data["swipe_key"],
         data["start_x"], data["start_y"], data["end_x"], data["end_y"])
    )
    return {"success": True, "id": row_id}


@router.put("/swipes/{swipe_id}")
async def update_swipe(swipe_id: int, data: dict):
    allowed = {"swipe_key", "start_x", "start_y", "end_x", "end_y"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE swipe_actions SET %s WHERE id = %%s" % sets, (*fields.values(), swipe_id))
    return {"success": True}


@router.delete("/swipes/{swipe_id}")
async def delete_swipe(swipe_id: int):
    await database.execute("DELETE FROM swipe_actions WHERE id = %s", (swipe_id,))
    return {"success": True}


# === Keyboard Configs ===

@router.get("/keyboard-configs/{bank_code}/{station_id}")
async def list_keyboard_configs(bank_code: str, station_id: int):
    return await database.fetchall(
        "SELECT * FROM keyboard_configs WHERE bank_code=%s AND station_id=%s ORDER BY keyboard_type",
        (bank_code, station_id)
    )


@router.get("/keyboard-configs/{bank_code}/{station_id}/{keyboard_type}")
async def get_keyboard_config(bank_code: str, station_id: int, keyboard_type: str):
    row = await database.fetchone(
        "SELECT * FROM keyboard_configs WHERE bank_code=%s AND station_id=%s AND keyboard_type=%s",
        (bank_code, station_id, keyboard_type)
    )
    return row or {"error": "Not found"}


@router.post("/keyboard-configs")
async def upsert_keyboard_config(data: dict):
    import json
    bank_code = data["bank_code"]
    station_id = data["station_id"]
    keyboard_type = data["keyboard_type"]
    config = data["config"]
    config_str = json.dumps(config) if isinstance(config, dict) else config

    existing = await database.fetchone(
        "SELECT id FROM keyboard_configs WHERE bank_code=%s AND station_id=%s AND keyboard_type=%s",
        (bank_code, station_id, keyboard_type)
    )
    if existing:
        await database.execute(
            "UPDATE keyboard_configs SET config=%s WHERE id=%s",
            (config_str, existing["id"])
        )
        return {"success": True, "id": existing["id"], "updated": True}
    else:
        row_id = await database.execute(
            "INSERT INTO keyboard_configs (bank_code, station_id, keyboard_type, config) VALUES (%s,%s,%s,%s)",
            (bank_code, station_id, keyboard_type, config_str)
        )
        return {"success": True, "id": row_id, "updated": False}


@router.delete("/keyboard-configs/{config_id}")
async def delete_keyboard_config(config_id: int):
    await database.execute("DELETE FROM keyboard_configs WHERE id = %s", (config_id,))
    return {"success": True}
