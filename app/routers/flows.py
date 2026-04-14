"""CRUD: flow_steps with reorder support"""
from fastapi import APIRouter
from app import database

router = APIRouter(prefix="/api/flows", tags=["flows"])


@router.get("/{template_id}/steps")
async def list_steps(template_id: int):
    return await database.fetchall(
        "SELECT * FROM flow_steps WHERE flow_template_id = %s ORDER BY step_number", (template_id,)
    )


@router.post("/{template_id}/steps")
async def add_step(template_id: int, data: dict):
    step_number = data.get("step_number")
    if not step_number:
        row = await database.fetchone(
            "SELECT MAX(step_number) as mx FROM flow_steps WHERE flow_template_id=%s", (template_id,)
        )
        step_number = (row["mx"] or 0) + 1

    await database.execute(
        "UPDATE flow_steps SET step_number = step_number + 1 WHERE flow_template_id=%s AND step_number >= %s ORDER BY step_number DESC",
        (template_id, step_number)
    )

    row_id = await database.execute(
        """INSERT INTO flow_steps 
        (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type,
         swipe_key, input_source, tap_count, pre_delay_ms, post_delay_ms, description)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (template_id, step_number, data["step_name"], data["action_type"],
         data.get("ui_element_key"), data.get("keymap_type"), data.get("swipe_key"),
         data.get("input_source"), data.get("tap_count", 1),
         data.get("pre_delay_ms", 0), data.get("post_delay_ms", 0), data.get("description"))
    )

    count = await database.fetchone(
        "SELECT COUNT(*) as cnt FROM flow_steps WHERE flow_template_id=%s", (template_id,)
    )
    await database.execute(
        "UPDATE flow_templates SET total_steps=%s WHERE id=%s", (count["cnt"], template_id)
    )

    return {"success": True, "id": row_id, "step_number": step_number}


@router.put("/steps/{step_id}")
async def update_step(step_id: int, data: dict):
    allowed = {"step_name", "action_type", "ui_element_key", "keymap_type", "swipe_key",
               "input_source", "tap_count", "pre_delay_ms", "post_delay_ms", "description"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return {"error": "No valid fields"}
    sets = ", ".join("%s = %%s" % k for k in fields)
    await database.execute("UPDATE flow_steps SET %s WHERE id = %%s" % sets, (*fields.values(), step_id))
    return {"success": True}


@router.delete("/steps/{step_id}")
async def delete_step(step_id: int):
    step = await database.fetchone("SELECT flow_template_id, step_number FROM flow_steps WHERE id=%s", (step_id,))
    if not step:
        return {"error": "Step not found"}

    await database.execute("DELETE FROM flow_steps WHERE id = %s", (step_id,))
    await database.execute(
        "UPDATE flow_steps SET step_number = step_number - 1 WHERE flow_template_id=%s AND step_number > %s",
        (step["flow_template_id"], step["step_number"])
    )
    count = await database.fetchone(
        "SELECT COUNT(*) as cnt FROM flow_steps WHERE flow_template_id=%s", (step["flow_template_id"],)
    )
    await database.execute(
        "UPDATE flow_templates SET total_steps=%s WHERE id=%s", (count["cnt"], step["flow_template_id"])
    )
    return {"success": True}


@router.post("/{template_id}/reorder")
async def reorder_steps(template_id: int, data: dict):
    """Reorder steps: data = {"order": [step_id_1, step_id_2, ...]}"""
    order = data.get("order", [])
    for idx, step_id in enumerate(order):
        await database.execute(
            "UPDATE flow_steps SET step_number = %s WHERE id = %s AND flow_template_id = %s",
            (idx + 1, step_id, template_id)
        )
    return {"success": True}
