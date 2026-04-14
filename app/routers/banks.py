"""CRUD: bank_apps, flow_templates, bank_name_mappings"""
from fastapi import APIRouter
from app import database

router = APIRouter(prefix="/api/banks", tags=["banks"])


# === Flow Templates ===

@router.get("/templates")
async def list_templates(arm_id: int = None):
    if arm_id is not None:
        return await database.fetchall(
            "SELECT * FROM flow_templates WHERE arm_id = %s OR arm_id IS NULL "
            "ORDER BY arm_id DESC, bank_code, version DESC",
            (arm_id,))
    return await database.fetchall("SELECT * FROM flow_templates ORDER BY arm_id, bank_code, version DESC")


@router.post("/templates")
async def create_template(data: dict):
    row_id = await database.execute(
        "INSERT INTO flow_templates (bank_code, arm_id, name, total_steps, version, status, transfer_type, amount_format) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (data["bank_code"], data.get("arm_id"), data["name"], data.get("total_steps", 0), data.get("version", 1), "active",
         data.get("transfer_type") or None, data.get("amount_format") or None)
    )
    return {"success": True, "id": row_id}


@router.post("/templates/{template_id}/copy")
async def copy_template(template_id: int, data: dict):
    """Copy a flow template + all its steps.

    Accepts optional overrides:
      arm_id          — target arm (default: same arm)
      transfer_type   — target transfer type, e.g. "INTER" (default: same)
      name            — new template name (default: auto-generated)
    """
    tpl = await database.fetchone("SELECT * FROM flow_templates WHERE id = %s", (template_id,))
    if not tpl:
        return {"error": "Template not found"}

    target_arm = data.get("arm_id", tpl["arm_id"])
    target_tt = data.get("transfer_type", tpl["transfer_type"]) or tpl["transfer_type"]

    if data.get("name"):
        target_name = data["name"]
    elif target_tt != tpl["transfer_type"]:
        tt_label = {"SAME": "Same Bank", "INTER": "Interbank"}.get(target_tt, target_tt or "")
        target_name = "%s %s Transfer Flow" % (tpl["bank_code"], tt_label)
    else:
        target_name = tpl["name"]

    if target_arm == tpl["arm_id"] and target_tt == tpl["transfer_type"]:
        return {"error": "Nothing to copy — target arm and transfer_type are the same as source. Change at least one."}

    try:
        new_id = await database.execute(
            "INSERT INTO flow_templates (bank_code, arm_id, name, total_steps, version, status, transfer_type, amount_format) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (tpl["bank_code"], target_arm, target_name, tpl["total_steps"], tpl["version"], "active",
             target_tt, tpl["amount_format"])
        )
    except Exception as e:
        if "Duplicate entry" in str(e):
            return {"error": "Target already exists (same bank_code/arm/version/transfer_type)."}
        raise
    steps = await database.fetchall(
        "SELECT * FROM flow_steps WHERE flow_template_id = %s ORDER BY step_number", (template_id,))

    tt_changed = target_tt != tpl["transfer_type"]
    suffix_map = {"SAME": "_same", "INTER": "_inter"}
    new_suffix = suffix_map.get(target_tt, "")
    old_suffix = suffix_map.get(tpl["transfer_type"], "")

    for s in steps:
        name = s["step_name"]
        ui_key = s["ui_element_key"]

        if tt_changed and name and name != "done":
            if old_suffix and name.endswith(old_suffix):
                name = name[:-len(old_suffix)]
            if new_suffix and not name.endswith(new_suffix):
                name += new_suffix
            if ui_key and ui_key != "done":
                if old_suffix and ui_key.endswith(old_suffix):
                    ui_key = ui_key[:-len(old_suffix)]
                if new_suffix and not ui_key.endswith(new_suffix):
                    ui_key += new_suffix

        await database.execute(
            """INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type,
            ui_element_key, keymap_type, swipe_key, input_source, tap_count, pre_delay_ms, post_delay_ms, description)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (new_id, s["step_number"], name, s["action_type"],
             ui_key, s["keymap_type"], s["swipe_key"], s["input_source"],
             s["tap_count"], s["pre_delay_ms"], s["post_delay_ms"], s["description"])
        )
    return {"success": True, "id": new_id, "steps_copied": len(steps)}


@router.put("/templates/{template_id}")
async def update_template(template_id: int, data: dict):
    allowed = {"bank_code", "arm_id", "name", "total_steps", "version", "status", "transfer_type", "amount_format"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE flow_templates SET %s WHERE id = %%s" % sets, (*fields.values(), template_id))
    return {"success": True}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: int):
    await database.execute("DELETE FROM flow_steps WHERE flow_template_id = %s", (template_id,))
    await database.execute("DELETE FROM flow_templates WHERE id = %s", (template_id,))
    return {"success": True}


# === Bank Apps ===

@router.get("/apps")
async def list_bank_apps():
    return await database.fetchall(
        """SELECT ba.*, s.name as station_name, s.arm_id, a.name as arm_name,
        p.name as phone_name
        FROM bank_apps ba
        JOIN stations s ON ba.station_id = s.id
        JOIN arms a ON s.arm_id = a.id
        LEFT JOIN phones p ON ba.phone_id = p.id
        ORDER BY ba.station_id, ba.bank_code"""
    )


@router.get("/apps/{station_id}")
async def list_bank_apps_by_station(station_id: int):
    return await database.fetchall(
        "SELECT * FROM bank_apps WHERE station_id = %s ORDER BY bank_code", (station_id,)
    )


@router.post("/apps")
async def create_bank_app(data: dict):
    try:
        row_id = await database.execute(
            """INSERT INTO bank_apps (phone_id, station_id, bank_code, bank_name, account_no, password, pin, status) 
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data["phone_id"], data["station_id"], data["bank_code"], data["bank_name"],
             data["account_no"], data["password"], data.get("pin"), data.get("status", "active"))
        )
        return {"success": True, "id": row_id}
    except Exception as e:
        if "Duplicate" in str(e):
            return {"success": False, "error": f"Bank app already exists ({data.get('bank_code')}-{data.get('account_no')})"}
        return {"success": False, "error": str(e)}


@router.put("/apps/{app_id}")
async def update_bank_app(app_id: int, data: dict):
    allowed = {"bank_code", "bank_name", "account_no", "password", "pin", "status"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE bank_apps SET %s WHERE id = %%s" % sets, (*fields.values(), app_id))
    return {"success": True}


@router.delete("/apps/{app_id}")
async def delete_bank_app(app_id: int):
    await database.execute("DELETE FROM bank_apps WHERE id = %s", (app_id,))
    return {"success": True}


# === Bank Name Mappings ===

@router.get("/mappings")
async def list_mappings():
    return await database.fetchall("SELECT * FROM bank_name_mappings ORDER BY from_bank_code, to_bank_code")


@router.get("/mappings/{from_bank_code}")
async def list_mappings_by_bank(from_bank_code: str):
    return await database.fetchall(
        "SELECT * FROM bank_name_mappings WHERE from_bank_code=%s ORDER BY to_bank_code",
        (from_bank_code,)
    )


@router.post("/mappings")
async def create_mapping(data: dict):
    row_id = await database.execute(
        "INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES (%s,%s,%s,%s)",
        (data["from_bank_code"], data["to_bank_code"], data["search_text"], data.get("display_name"))
    )
    return {"success": True, "id": row_id}


@router.put("/mappings/{mapping_id}")
async def update_mapping(mapping_id: int, data: dict):
    allowed = {"from_bank_code", "to_bank_code", "search_text", "display_name"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE bank_name_mappings SET %s WHERE id = %%s" % sets, (*fields.values(), mapping_id))
    return {"success": True}


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: int):
    await database.execute("DELETE FROM bank_name_mappings WHERE id = %s", (mapping_id,))
    return {"success": True}
