"""Export one bank's flow skeleton (templates + steps, no coordinates) as a
portable SQL seed file that can be imported onto any machine via the companion
db/import_bank_seed.py script.

The resulting seed is idempotent and self-contained:

- Contains: flow_templates + flow_steps for the requested bank AND any handler
  flow templates referenced by CHECK_SCREEN steps in the main flows.
- Excludes: ui_elements, keymaps, swipe_actions, keyboard_configs, references,
  calibrations - all per-machine; re-capture via Builder on the target machine.
- Handler flow IDs are rewritten at import time so the CHECK_SCREEN description
  JSON always points at the correct newly-assigned template_id.
- The arm name is a placeholder {ARM_NAME} resolved at import time by
  db/import_bank_seed.py so the same SQL works for any arm (ARM-01, ARM-05 ...).

Export usage:
    py db/export_bank_seed.py <BANK_CODE> <ARM_NAME> [output_file]
    py db/export_bank_seed.py ABA ARM-01
    py db/export_bank_seed.py CIMB ARM-08 db/seed_bank_CIMB.sql

Import usage (run on new machine):
    py db/import_bank_seed.py db/seed_bank_ABA.sql ARM-05
"""
import json
import os
import re
import subprocess
import sys

CONTAINER = "wa-unified-mysql"
DB_USER = "root"
DB_PASS = "wa_unified_2026"
DB_NAME = "wa_db"


def run_mysql(query: str) -> str:
    """Run a SELECT and return stdout as tab-separated text (no headers)."""
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "mysql",
         "-u", DB_USER, "-p" + DB_PASS, "-N", "-B",
         "-e", query, DB_NAME],
        capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        print("mysql query failed: %s" % proc.stderr.decode("utf-8", errors="replace"))
        sys.exit(1)
    return proc.stdout.decode("utf-8", errors="replace")


def quote(v):
    """SQL-quote a value. Empty / None -> NULL."""
    if v is None or v == "NULL" or v == "":
        return "NULL"
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + s + "'"


def int_or_null(v):
    if v is None or v == "NULL" or v == "":
        return "NULL"
    return str(int(v))


def fetch_template(bank_code: str, arm_id: int):
    """Return list of templates (dicts) for a given bank+arm."""
    raw = run_mysql(
        "SELECT id, name, transfer_type, amount_format, total_steps "
        "FROM flow_templates WHERE bank_code='%s' AND arm_id=%d ORDER BY id;"
        % (bank_code, arm_id)
    )
    templates = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 5:
            parts.append("")
        templates.append({
            "id": int(parts[0]),
            "name": parts[1],
            "transfer_type": parts[2],
            "amount_format": parts[3],
            "total_steps": parts[4],
        })
    return templates


def fetch_steps(template_id: int):
    """Return list of flow_steps (dicts) for a given template."""
    raw = run_mysql(
        "SELECT step_number, step_name, action_type, "
        "IFNULL(ui_element_key, ''), IFNULL(keymap_type, ''), IFNULL(swipe_key, ''), "
        "IFNULL(input_source, ''), "
        "IFNULL(pre_delay_ms, 0), IFNULL(post_delay_ms, 0), "
        "IFNULL(description, '') "
        "FROM flow_steps WHERE flow_template_id=%d ORDER BY step_number;"
        % template_id
    )
    rows = []
    # mysql -N -B tab-separates and the description can contain tabs or newlines
    # (from JSON whitespace). The output ends each row with \n though, so
    # use a column-counting splitter.
    for line in raw.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", maxsplit=9)
        if len(parts) < 10:
            parts += [""] * (10 - len(parts))
        rows.append({
            "step_number": parts[0],
            "step_name": parts[1],
            "action_type": parts[2],
            "ui_element_key": parts[3],
            "keymap_type": parts[4],
            "swipe_key": parts[5],
            "input_source": parts[6],
            "pre_delay_ms": parts[7],
            "post_delay_ms": parts[8],
            "description": parts[9],
        })
    return rows


def extract_handler_flow_ref(description: str):
    """Parse description JSON; return handler_flow string or None."""
    if not description or not description.startswith("{"):
        return None
    try:
        d = json.loads(description)
    except (ValueError, TypeError):
        return None
    hf = d.get("handler_flow") if isinstance(d, dict) else None
    return hf if hf else None


def resolve_handler_template(handler_ref: str):
    """Given a ref like 'ABA_SLIDE_RETRY__27', look up the source template row
    (matches by numeric id). Returns dict with id, bank_code, name,
    transfer_type, amount_format, or None if not found."""
    parts = handler_ref.rsplit("__", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    src_id = int(parts[1])
    raw = run_mysql(
        "SELECT id, bank_code, name, IFNULL(transfer_type, ''), IFNULL(amount_format, ''), "
        "IFNULL(total_steps, 0) "
        "FROM flow_templates WHERE id=%d;" % src_id
    ).strip()
    if not raw:
        return None
    parts = raw.split("\t")
    # Pad in case trailing empty columns are dropped by mysql -B output
    while len(parts) < 6:
        parts.append("0")
    return {
        "id": int(parts[0]),
        "bank_code": parts[1],
        "name": parts[2],
        "transfer_type": parts[3],
        "amount_format": parts[4],
        "total_steps": parts[5],
    }


def build_step_values(var_name: str, step: dict, handler_var_map: dict):
    """Return the '(...)' tuple literal for one flow_steps row, rewriting the
    handler_flow field in description JSON to use the target-machine template
    variable instead of the source-machine id.

    handler_var_map: {handler_ref_string: mysql_variable_name_with_at}
    """
    description = step["description"]
    hf_ref = extract_handler_flow_ref(description)

    values_prefix = (
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        % (
            var_name,
            int_or_null(step["step_number"]),
            quote(step["step_name"]),
            quote(step["action_type"]),
            quote(step["ui_element_key"]),
            quote(step["keymap_type"]),
            quote(step["swipe_key"]),
            quote(step["input_source"]),
            int_or_null(step["pre_delay_ms"]),
            int_or_null(step["post_delay_ms"]),
        )
    )

    if hf_ref and hf_ref in handler_var_map:
        # Split the JSON string around the hf_ref and emit a CONCAT so MySQL
        # interpolates the new handler template id at import time.
        handler_var = handler_var_map[hf_ref]
        prefix, _, suffix = description.partition(hf_ref)
        # Re-slice the ref so we keep the prefix portion (e.g. "ABA_SLIDE_RETRY__")
        # and replace only the numeric id. The variable holds just the numeric id.
        bank_prefix_match = re.match(r"^(.+__)(\d+)$", hf_ref)
        if bank_prefix_match:
            name_prefix = bank_prefix_match.group(1)
            # e.g. prefix = '...handler_flow":"', then name_prefix = 'ABA_SLIDE_RETRY__'
            # So CONCAT(<prefix + name_prefix>, handler_var_number, <suffix>)
            concat_sql = (
                "CONCAT(%s, %s, %s)"
                % (
                    quote(prefix + name_prefix),
                    handler_var,
                    quote(suffix),
                )
            )
            return values_prefix + concat_sql + ")"

    # Default: plain description string.
    return values_prefix + quote(description) + ")"


def emit_template_block(lines, var_name, template, steps, handler_var_map):
    """Append SQL for one (template, steps) pair to `lines`."""
    lines.append("-- Template: %s (%s)" % (template["name"], template.get("bank_code", "")))
    lines.append(
        "INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES\n"
        "  (%s, @arm_id, %s, %s, %s, %s);"
        % (
            quote(template["bank_code"]),
            quote(template["name"]),
            quote(template["transfer_type"]),
            quote(template["amount_format"]),
            int_or_null(template.get("total_steps")),
        )
    )
    lines.append("SET %s = LAST_INSERT_ID();" % var_name)
    lines.append("")
    if not steps:
        lines.append("-- (no steps for this template)")
        lines.append("")
        return
    lines.append(
        "INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, "
        "ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, "
        "description) VALUES"
    )
    row_strs = [build_step_values(var_name, s, handler_var_map) for s in steps]
    lines.append(",\n".join("  " + r for r in row_strs) + ";")
    lines.append("")


def main():
    if len(sys.argv) < 3:
        print("Usage: py db/export_bank_seed.py <BANK_CODE> <ARM_NAME> [output_file]")
        sys.exit(1)

    bank_code = sys.argv[1]
    arm_name = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        os.path.dirname(__file__), "seed_bank_%s.sql" % bank_code
    )

    arm_row = run_mysql("SELECT id FROM arms WHERE name='%s';" % arm_name).strip()
    if not arm_row:
        print("ERROR: arm '%s' not found on source DB" % arm_name)
        sys.exit(1)
    source_arm_id = int(arm_row)

    main_templates = fetch_template(bank_code, source_arm_id)
    if not main_templates:
        print("ERROR: no flow_templates found for bank=%s arm=%s" % (bank_code, arm_name))
        sys.exit(1)

    # Attach bank_code (we already know it) + fetch steps + discover handler_flow refs.
    handler_refs: set = set()
    for t in main_templates:
        t["bank_code"] = bank_code
        t["steps"] = fetch_steps(t["id"])
        for s in t["steps"]:
            ref = extract_handler_flow_ref(s["description"])
            if ref:
                handler_refs.add(ref)

    # Resolve each handler_flow ref to the source template it points at.
    handler_templates = []
    handler_var_map: dict = {}
    for idx, ref in enumerate(sorted(handler_refs), start=1):
        resolved = resolve_handler_template(ref)
        if resolved is None:
            print("WARN: handler_flow '%s' could not be resolved on source DB" % ref)
            continue
        resolved["steps"] = fetch_steps(resolved["id"])
        handler_templates.append(resolved)
        handler_var_map[ref] = "@handler_%d_id" % idx

    print("Bank %s on %s: %d main template(s), %d handler template(s), %d step(s) total"
          % (
              bank_code,
              arm_name,
              len(main_templates),
              len(handler_templates),
              sum(len(t["steps"]) for t in main_templates)
              + sum(len(h["steps"]) for h in handler_templates),
          ))

    # Build SQL.
    lines = [
        "-- ============================================================",
        "-- Flow seed for %s (sourced from %s)" % (bank_code, arm_name),
        "-- Exported by db/export_bank_seed.py",
        "--",
        "-- Contains: flow_templates + flow_steps for %s," % bank_code,
        ("-- plus %d handler flow template(s) referenced by CHECK_SCREEN steps."
         % len(handler_templates)) if handler_templates else
        "-- No handler flow dependencies.",
        "-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,",
        "--            references, calibrations - all per-machine, re-capture via Builder.",
        "--",
        "-- DO NOT import this file directly with mysql.",
        "-- Use the wrapper script so the target arm name is injected correctly:",
        "--   py db/import_bank_seed.py db/seed_bank_%s.sql <ARM_NAME>" % bank_code,
        "-- e.g.: py db/import_bank_seed.py db/seed_bank_%s.sql ARM-05" % bank_code,
        "--",
        "-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.",
        "-- Idempotent: drops existing %s + handler flows on that arm, reinserts."
        % bank_code,
        "-- ============================================================",
        "",
        # {ARM_NAME} will be substituted by import_bank_seed.py before execution.
        "SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');",
        "",
        "-- Guard: fail loudly if arm does not exist on target machine.",
        "SELECT IFNULL(@arm_id, (SELECT 1 FROM nonexistent_arm_check)) AS ok;",
        "",
        "-- Clear any existing flows for this bank + its handler banks (if any) on this arm.",
    ]

    # Collect the distinct bank_codes we'll delete - main + each handler's bank_code.
    delete_banks = [bank_code] + sorted({h["bank_code"] for h in handler_templates})
    seen = set()
    delete_banks_unique = []
    for b in delete_banks:
        if b not in seen:
            seen.add(b)
            delete_banks_unique.append(b)
    for b in delete_banks_unique:
        lines.append(
            "DELETE FROM flow_steps WHERE flow_template_id IN ("
            "SELECT id FROM flow_templates WHERE bank_code = %s AND arm_id = @arm_id);"
            % quote(b)
        )
        lines.append(
            "DELETE FROM flow_templates WHERE bank_code = %s AND arm_id = @arm_id;"
            % quote(b)
        )
    lines.append("")

    # Emit handler templates FIRST so their variables are set before main flows
    # reference them.
    for i, h in enumerate(handler_templates, start=1):
        emit_template_block(
            lines,
            "@handler_%d_id" % i,
            h,
            h["steps"],
            handler_var_map,  # handlers themselves never reference each other in our data
        )

    # Emit main flow templates.
    for i, t in enumerate(main_templates, start=1):
        emit_template_block(
            lines,
            "@tpl_%d" % i,
            t,
            t["steps"],
            handler_var_map,
        )

    lines.append("-- End of %s seed." % bank_code)
    lines.append(
        "SELECT CONCAT('Imported %d template(s) + %d handler(s) for bank=%s') AS done;"
        % (len(main_templates), len(handler_templates), bank_code)
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("OK - written to %s" % output_file)


if __name__ == "__main__":
    main()
