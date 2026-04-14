"""Export current database to seed.sql — run periodically to keep seed up to date.

Usage:
    py db/export_seed.py              # Export to db/seed.sql
    py db/export_seed.py backup.sql   # Export to custom file
"""
import subprocess
import sys
import os

CONTAINER = "wa-unified-mysql"
DB_USER = "root"
DB_PASS = "wa_unified_2026"
DB_NAME = "wa_db"

TABLES = [
    "arms", "stations", "phones", "bank_apps",
    "flow_templates", "flow_steps",
    "ui_elements", "keymaps", "swipe_actions",
    "keyboard_configs", "bank_name_mappings", "calibrations",
]

output_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "seed.sql")

print("Exporting from %s/%s ..." % (CONTAINER, DB_NAME))
print("Tables: %s" % ", ".join(TABLES))

proc = subprocess.run(
    ["docker", "exec", CONTAINER, "mysqldump",
     "-u", DB_USER, "-p" + DB_PASS,
     "--no-create-info", "--complete-insert",
     "--skip-add-locks", "--skip-lock-tables",
     DB_NAME] + TABLES,
    capture_output=True, timeout=60,
)

if proc.returncode != 0:
    print("FAILED:")
    print(proc.stderr.decode("utf-8", errors="replace"))
    sys.exit(1)

raw = proc.stdout.decode("utf-8", errors="replace")

lines = raw.split("\n")
cleaned = []
for line in lines:
    if line.startswith("mysqldump: [Warning]"):
        continue
    cleaned.append(line)

header = "-- WA Unified Seed Data — exported from %s/%s\n" % (CONTAINER, DB_NAME)

with open(output_file, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(cleaned))

row_count = sum(1 for line in cleaned if line.strip().startswith("INSERT"))
print("OK — %d INSERT statements written to %s" % (row_count, output_file))
