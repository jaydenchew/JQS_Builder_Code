"""Copy ACLEDA + WINGBANK flow/coordinate data from ARM-01 to ARM-02 & ARM-03.

Offsets calculated from logo positions:
  ARM-01: ACLEDA=(51.8,105.8)  WINGBANK=(66.9,107.3)
  ARM-02: ACLEDA=(52,107)      WINGBANK=(68,107)
  ARM-03: ACLEDA=(54,107)      WINGBANK=(70,107)
"""
import pymysql
import json
import copy

SRC_ARM_ID = 2
SRC_STATION = 2

TARGETS = [
    {"arm_id": 3, "station_id": 3, "name": "ARM-02"},
    {"arm_id": 4, "station_id": 4, "name": "ARM-03"},
]

OFFSETS = {
    3: {"ACLEDA": (0.2, 1.2), "ACLEDA_AFTER_POPUP": (0.2, 1.2), "WINGBANK": (1.1, -0.3)},
    4: {"ACLEDA": (2.2, 1.2), "ACLEDA_AFTER_POPUP": (2.2, 1.2), "WINGBANK": (3.1, -0.3)},
}

SRC_TEMPLATES = [13, 16, 15, 14]
BANKS = ["ACLEDA", "ACLEDA_AFTER_POPUP", "WINGBANK"]


def offset_xy(x, y, dx, dy):
    if x == 0.0 and y == 0.0:
        return 0.0, 0.0
    return round(x + dx, 1), round(y + dy, 1)


def offset_json_config(cfg, dx, dy):
    cfg = copy.deepcopy(cfg)
    pages = cfg.get("pages", {})
    for page_name, page_data in pages.items():
        keys = page_data.get("keys", {})
        for key_name, coords in keys.items():
            if isinstance(coords, list) and len(coords) >= 2:
                ox, oy = offset_xy(coords[0], coords[1], dx, dy)
                coords[0] = ox
                coords[1] = oy
    return cfg


def main():
    conn = pymysql.connect(host="127.0.0.1", port=3308, user="root",
                           password="wa_unified_2026", database="wa_db")
    cur = conn.cursor(pymysql.cursors.DictCursor)

    summary = {"flow_templates": 0, "flow_steps": 0, "ui_elements": 0,
               "keymaps": 0, "keyboard_configs": 0, "swipe_actions": 0}

    try:
        for tgt in TARGETS:
            arm_id = tgt["arm_id"]
            station_id = tgt["station_id"]
            arm_name = tgt["name"]
            offsets = OFFSETS[station_id]

            print("=== %s (arm_id=%d, station_id=%d) ===" % (arm_name, arm_id, station_id))

            # --- 1. flow_templates + flow_steps ---
            for src_tpl_id in SRC_TEMPLATES:
                cur.execute("SELECT * FROM flow_templates WHERE id=%s", (src_tpl_id,))
                tpl = cur.fetchone()
                if not tpl:
                    print("  WARNING: template %d not found, skipping" % src_tpl_id)
                    continue

                cur.execute("SELECT id FROM flow_templates WHERE arm_id=%s AND bank_code=%s AND transfer_type<=>%s",
                            (arm_id, tpl["bank_code"], tpl["transfer_type"]))
                existing = cur.fetchone()
                if existing:
                    print("  SKIP template %s/%s (already exists as id=%d)" % (
                        tpl["bank_code"], tpl["transfer_type"], existing["id"]))
                    new_tpl_id = existing["id"]
                    cur.execute("DELETE FROM flow_steps WHERE flow_template_id=%s", (new_tpl_id,))
                else:
                    cur.execute(
                        """INSERT INTO flow_templates (arm_id, bank_code, name, transfer_type, total_steps, status)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                        (arm_id, tpl["bank_code"], tpl["name"], tpl["transfer_type"],
                         tpl["total_steps"], tpl["status"]))
                    new_tpl_id = cur.lastrowid
                    summary["flow_templates"] += 1
                    print("  CREATED template id=%d: %s/%s" % (new_tpl_id, tpl["bank_code"], tpl["transfer_type"]))

                cur.execute("SELECT * FROM flow_steps WHERE flow_template_id=%s ORDER BY step_number", (src_tpl_id,))
                steps = cur.fetchall()
                for s in steps:
                    cur.execute(
                        """INSERT INTO flow_steps
                        (flow_template_id, step_number, step_name, action_type, ui_element_key,
                         keymap_type, swipe_key, input_source, tap_count, pre_delay_ms, post_delay_ms, description)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (new_tpl_id, s["step_number"], s["step_name"], s["action_type"],
                         s["ui_element_key"], s["keymap_type"], s["swipe_key"], s["input_source"],
                         s["tap_count"], s["pre_delay_ms"], s["post_delay_ms"], s["description"]))
                    summary["flow_steps"] += 1
                print("    -> %d steps copied" % len(steps))

            # --- 2. ui_elements ---
            for bank in BANKS:
                dx, dy = offsets[bank]
                cur.execute("SELECT * FROM ui_elements WHERE station_id=%s AND bank_code=%s",
                            (SRC_STATION, bank))
                elements = cur.fetchall()
                for el in elements:
                    nx, ny = offset_xy(float(el["x"]), float(el["y"]), dx, dy)
                    cur.execute("SELECT id FROM ui_elements WHERE station_id=%s AND bank_code=%s AND element_key=%s",
                                (station_id, bank, el["element_key"]))
                    ex = cur.fetchone()
                    if ex:
                        cur.execute("UPDATE ui_elements SET x=%s, y=%s WHERE id=%s", (nx, ny, ex["id"]))
                    else:
                        cur.execute(
                            "INSERT INTO ui_elements (bank_code, station_id, element_key, x, y) VALUES (%s,%s,%s,%s,%s)",
                            (bank, station_id, el["element_key"], nx, ny))
                    summary["ui_elements"] += 1
                print("  ui_elements %s: %d elements (dx=%.1f, dy=%.1f)" % (bank, len(elements), dx, dy))

            # --- 3. keymaps ---
            for bank in BANKS:
                dx, dy = offsets[bank]
                cur.execute("SELECT * FROM keymaps WHERE station_id=%s AND bank_code=%s", (SRC_STATION, bank))
                keys = cur.fetchall()
                for k in keys:
                    nx, ny = offset_xy(float(k["x"]), float(k["y"]), dx, dy)
                    cur.execute(
                        "SELECT id FROM keymaps WHERE station_id=%s AND bank_code=%s AND keyboard_type=%s AND key_char=%s",
                        (station_id, bank, k["keyboard_type"], k["key_char"]))
                    ex = cur.fetchone()
                    if ex:
                        cur.execute("UPDATE keymaps SET x=%s, y=%s WHERE id=%s", (nx, ny, ex["id"]))
                    else:
                        cur.execute(
                            "INSERT INTO keymaps (bank_code, station_id, keyboard_type, key_char, x, y) VALUES (%s,%s,%s,%s,%s,%s)",
                            (bank, station_id, k["keyboard_type"], k["key_char"], nx, ny))
                    summary["keymaps"] += 1
                if keys:
                    print("  keymaps %s: %d keys" % (bank, len(keys)))

            # --- 4. keyboard_configs ---
            cur.execute("SELECT * FROM keyboard_configs WHERE station_id=%s AND bank_code IN ('ACLEDA','WINGBANK')",
                        (SRC_STATION,))
            configs = cur.fetchall()
            for c in configs:
                bank = c["bank_code"]
                dx, dy = offsets[bank]
                raw = c["config"]
                cfg = json.loads(raw) if isinstance(raw, str) else raw
                new_cfg = offset_json_config(cfg, dx, dy)
                cfg_json = json.dumps(new_cfg)

                cur.execute(
                    "SELECT id FROM keyboard_configs WHERE station_id=%s AND bank_code=%s AND keyboard_type=%s",
                    (station_id, bank, c["keyboard_type"]))
                ex = cur.fetchone()
                if ex:
                    cur.execute("UPDATE keyboard_configs SET config=%s WHERE id=%s", (cfg_json, ex["id"]))
                else:
                    cur.execute(
                        "INSERT INTO keyboard_configs (bank_code, station_id, keyboard_type, config) VALUES (%s,%s,%s,%s)",
                        (bank, station_id, c["keyboard_type"], cfg_json))
                summary["keyboard_configs"] += 1
                print("  keyboard_config %s/%s (dx=%.1f, dy=%.1f)" % (bank, c["keyboard_type"], dx, dy))

            # --- 5. swipe_actions ---
            for bank in BANKS:
                dx, dy = offsets[bank]
                cur.execute("SELECT * FROM swipe_actions WHERE station_id=%s AND bank_code=%s",
                            (SRC_STATION, bank))
                swipes = cur.fetchall()
                for sw in swipes:
                    sx, sy = offset_xy(float(sw["start_x"]), float(sw["start_y"]), dx, dy)
                    ex_, ey = offset_xy(float(sw["end_x"]), float(sw["end_y"]), dx, dy)
                    cur.execute(
                        "SELECT id FROM swipe_actions WHERE station_id=%s AND bank_code=%s AND swipe_key=%s",
                        (station_id, bank, sw["swipe_key"]))
                    exist = cur.fetchone()
                    if exist:
                        cur.execute("UPDATE swipe_actions SET start_x=%s, start_y=%s, end_x=%s, end_y=%s WHERE id=%s",
                                    (sx, sy, ex_, ey, exist["id"]))
                    else:
                        cur.execute(
                            """INSERT INTO swipe_actions (bank_code, station_id, swipe_key, start_x, start_y, end_x, end_y)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (bank, station_id, sw["swipe_key"], sx, sy, ex_, ey))
                    summary["swipe_actions"] += 1
                if swipes:
                    print("  swipe_actions %s: %d swipes" % (bank, len(swipes)))

            print()

        conn.commit()

        print("=== SUMMARY ===")
        for k, v in summary.items():
            print("  %s: %d" % (k, v))
        print("\nDone! All data committed.")

    except Exception as e:
        conn.rollback()
        print("ERROR: %s" % e)
        print("Transaction rolled back.")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
