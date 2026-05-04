-- ============================================================
-- Flow seed for STALL (sourced from ARM-04)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for STALL,
-- No handler flow dependencies.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_STALL.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_STALL.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing STALL + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'STALL' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'STALL' AND arm_id = @arm_id;

-- Template: STALL Transfer Flow (STALL)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('STALL', @arm_id, 'STALL Transfer Flow', NULL, NULL, 3);
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'all_app', 'CLICK', 'all_app', NULL, NULL, NULL, 0, 1500, NULL),
  (@tpl_1, 2, 'slide_close', 'SWIPE', NULL, NULL, 'slide_close', NULL, 0, 0, NULL),
  (@tpl_1, 3, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- End of STALL seed.
SELECT CONCAT('Imported 1 template(s) + 0 handler(s) for bank=STALL') AS done;