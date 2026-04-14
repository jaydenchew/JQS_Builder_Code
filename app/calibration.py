"""Camera-to-arm coordinate calibration — database-backed.

Uses the 2x3 affine transform matrix stored in the calibrations table.
The matrix maps RAW (unrotated) camera pixels to arm coordinates,
calibrated at the park position.

Conversion flow (unchanged):
  1. Rotated pixel -> Raw pixel (undo 90 CW rotation)
  2. Raw pixel -> Arm position via matrix (as if camera at park)
  3. Adjust for actual camera position (offset from park)
"""
import numpy as np
import json
import logging
from app import database

logger = logging.getLogger(__name__)

_cache = {}


async def get_calibration(station_id: int):
    """Load calibration from DB (with in-memory cache)."""
    if station_id in _cache:
        return _cache[station_id]
    row = await database.fetchone(
        "SELECT transform_matrix, camera_park_x, camera_park_y, "
        "scale_mm_per_pixel, rotation_degrees, raw_height "
        "FROM calibrations WHERE station_id = %s",
        (station_id,)
    )
    if not row:
        return None
    matrix = row["transform_matrix"]
    if isinstance(matrix, str):
        matrix = json.loads(matrix)
    cal = {
        "transform_matrix": matrix,
        "camera_park_pos": [row["camera_park_x"], row["camera_park_y"]],
        "scale_mm_per_pixel": row["scale_mm_per_pixel"],
        "rotation_degrees": row["rotation_degrees"],
        "raw_height": row["raw_height"],
    }
    _cache[station_id] = cal
    return cal


async def save_calibration(station_id: int, data: dict):
    """Upsert calibration data to DB."""
    matrix = data.get("transform_matrix")
    matrix_json = json.dumps(matrix) if isinstance(matrix, list) else matrix
    park_pos = data.get("camera_park_pos", [91.0, 58.0])
    park_x = park_pos[0] if isinstance(park_pos, list) else data.get("camera_park_x", 91.0)
    park_y = park_pos[1] if isinstance(park_pos, list) else data.get("camera_park_y", 58.0)

    existing = await database.fetchone(
        "SELECT id FROM calibrations WHERE station_id = %s", (station_id,)
    )
    if existing:
        await database.execute(
            """UPDATE calibrations SET transform_matrix=%s, camera_park_x=%s, camera_park_y=%s,
            scale_mm_per_pixel=%s, rotation_degrees=%s, raw_height=%s WHERE station_id=%s""",
            (matrix_json, park_x, park_y,
             data.get("scale_mm_per_pixel", 0.204), data.get("rotation_degrees", 90.0),
             data.get("raw_height", 480), station_id)
        )
    else:
        await database.execute(
            """INSERT INTO calibrations (station_id, transform_matrix, camera_park_x, camera_park_y,
            scale_mm_per_pixel, rotation_degrees, raw_height)
            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (station_id, matrix_json, park_x, park_y,
             data.get("scale_mm_per_pixel", 0.204), data.get("rotation_degrees", 90.0),
             data.get("raw_height", 480))
        )
    _cache.pop(station_id, None)
    logger.info("Calibration saved for station %d", station_id)


async def is_calibrated(station_id: int):
    return (await get_calibration(station_id)) is not None


async def pixel_to_arm(station_id: int, rotated_px: float, rotated_py: float,
                       cur_arm_x: float, cur_arm_y: float):
    """Convert a click on the ROTATED browser image to arm coordinates."""
    cal = await get_calibration(station_id)
    if cal is None:
        raise ValueError("Station %d not calibrated" % station_id)

    M = np.array(cal["transform_matrix"])
    raw_height = cal.get("raw_height", 480)

    raw_x = rotated_py
    raw_y = (raw_height - 1) - rotated_px

    arm_base = M @ np.array([raw_x, raw_y, 1.0])

    park_x, park_y = cal.get("camera_park_pos", [91.0, 58.0])
    arm_x = arm_base[0] + (cur_arm_x - park_x)
    arm_y = arm_base[1] + (cur_arm_y - park_y)

    return round(float(arm_x), 1), round(float(arm_y), 1)


async def get_all_calibrations():
    """Get calibration status for all stations (from DB, not hardcoded)."""
    rows = await database.fetchall(
        "SELECT s.id as station_id, s.name, c.scale_mm_per_pixel, c.rotation_degrees "
        "FROM stations s LEFT JOIN calibrations c ON s.id = c.station_id ORDER BY s.id"
    )
    result = {}
    for r in rows:
        result[r["station_id"]] = {
            "name": r["name"],
            "calibrated": r["scale_mm_per_pixel"] is not None,
            "scale": r["scale_mm_per_pixel"],
            "rotation": r["rotation_degrees"],
        }
    return result
