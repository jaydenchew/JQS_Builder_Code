"""Apply bundled SQL seeds (flow templates + bank name mappings) from the UI.

Seeds live in db/ next to the app:
  - seed_bank_<CODE>.sql               -> flow_templates + flow_steps for a bank.
    Carries an {ARM_NAME} placeholder substituted with the target arm's name.
  - seed_bank_name_mappings_<CODE>.sql -> bank_name_mappings (no placeholder).

All seeds are idempotent (DELETE + INSERT). Coordinates (ui_elements /
swipe_actions / keymaps) are NOT touched by seeds - they are matched to flow
steps by name, so re-importing keeps existing coordinates automatically.

Seed scripts contain multiple statements, so they run on a short-lived
dedicated connection with MULTI_STATEMENTS enabled. This does not borrow from
the shared app pool, so it cannot disturb running workers.
"""
import os
import re

import aiomysql
from pymysql.constants import CLIENT
from fastapi import APIRouter

from app import database
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

router = APIRouter(prefix="/api/seeds", tags=["seeds"])

_DB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db"
)

# seed_bank_ABA.sql -> ABA   (but NOT seed_bank_name_mappings_*.sql)
_FLOW_RE = re.compile(r"^seed_bank_(?!name_mappings_)(.+)\.sql$")
_MAPPING_RE = re.compile(r"^seed_bank_name_mappings_(.+)\.sql$")


def _discover(pattern):
    """Return {CODE: absolute_path} for seed files matching pattern in db/."""
    out = {}
    if not os.path.isdir(_DB_DIR):
        return out
    for name in os.listdir(_DB_DIR):
        m = pattern.match(name)
        if m:
            out[m.group(1)] = os.path.join(_DB_DIR, name)
    return out


async def _run_script(sql):
    """Execute a multi-statement SQL script on a dedicated connection."""
    conn = await aiomysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, db=DB_NAME,
        charset="utf8mb4", autocommit=True,
        client_flag=CLIENT.MULTI_STATEMENTS,
        connect_timeout=10,
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql)
            while await cur.nextset():
                pass
    finally:
        conn.close()


@router.get("/flows")
async def list_flow_seeds():
    return [{"code": c} for c in sorted(_discover(_FLOW_RE))]


@router.get("/mappings")
async def list_mapping_seeds():
    return [{"code": c} for c in sorted(_discover(_MAPPING_RE))]


@router.post("/flows/apply")
async def apply_flow_seed(data: dict):
    seed = (data.get("seed") or "").strip()
    arm_id = data.get("arm_id")
    if not seed or arm_id is None:
        return {"error": "seed and arm_id are required."}

    files = _discover(_FLOW_RE)
    path = files.get(seed)
    if not path:
        return {"error": "Unknown flow seed: %s" % seed}

    arm = await database.fetchone("SELECT name FROM arms WHERE id=%s", (arm_id,))
    if not arm:
        return {"error": "Arm id %s not found." % arm_id}

    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    if "{ARM_NAME}" not in sql:
        return {"error": "Seed file %s has no {ARM_NAME} placeholder." % seed}

    sql = sql.replace("{ARM_NAME}", arm["name"].replace("'", "''"))

    try:
        await _run_script(sql)
    except Exception as e:
        return {"error": "Import failed: %s" % e}

    return {"success": True, "message": "Imported %s flow for arm %s." % (seed, arm["name"])}


@router.post("/mappings/apply")
async def apply_mapping_seed(data: dict):
    seed = (data.get("seed") or "").strip()
    if not seed:
        return {"error": "seed is required."}

    files = _discover(_MAPPING_RE)
    path = files.get(seed)
    if not path:
        return {"error": "Unknown mapping seed: %s" % seed}

    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()

    try:
        await _run_script(sql)
    except Exception as e:
        return {"error": "Import failed: %s" % e}

    return {"success": True, "message": "Imported %s bank name mappings." % seed}
