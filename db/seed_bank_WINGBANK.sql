-- ============================================================
-- Flow seed for WINGBANK (sourced from ARM-01)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for WINGBANK,
-- No handler flow dependencies.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_WINGBANK.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_WINGBANK.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing WINGBANK + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'WINGBANK' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'WINGBANK' AND arm_id = @arm_id;

-- Template: WINGBANK Transfer Flow (WINGBANK)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('WINGBANK', @arm_id, 'WINGBANK Transfer Flow', 'SAME', 'always_decimal', 19);
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'open_app', 'CLICK', 'open_app', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 2, 'click_local_transfer', 'CLICK', 'click_local_transfer', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 3, 'enter_password', 'TYPE', NULL, 'wing_s1_password', NULL, 'password', 0, 5000, NULL),
  (@tpl_1, 4, 'to_wing', 'CLICK', 'to_wing', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 5, 'select_account', 'CLICK', 'select_account', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 6, 'select_savings_usd', 'CLICK', 'select_savings_usd', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 7, 'click_account_input', 'CLICK', 'click_account_input', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 8, 'enter_account', 'TYPE', NULL, 'wing_s1_accountno', NULL, 'pay_to_account_no', 0, 1000, NULL),
  (@tpl_1, 9, 'click_amount_input', 'CLICK', 'click_amount_input', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 10, 'enter_amount', 'TYPE', NULL, 'wing_s1_amount', NULL, 'amount', 0, 1000, NULL),
  (@tpl_1, 11, 'click_tick', 'CLICK', 'click_tick', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 12, 'click_send', 'CLICK', 'click_send', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 13, 'ocr_verify_before_transfer', 'OCR_VERIFY', 'ocr_verify_before_transfer', NULL, NULL, NULL, 0, 1000, '{"verify_fields":["pay_to_account_no","amount"],"field_rois":{"pay_to_account_no":{"top_percent":46,"bottom_percent":49,"left_percent":18,"right_percent":57},"amount":{"top_percent":57,"bottom_percent":65,"left_percent":30,"right_percent":81},"pay_to_account_name":{"top_percent":42,"bottom_percent":46,"left_percent":18,"right_percent":82}},"roi":{"top_percent":37,"bottom_percent":65,"left_percent":17,"right_percent":85}}'),
  (@tpl_1, 14, 'confirm_transfer', 'CLICK', 'confirm_transfer', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 15, 'enter_password_2', 'TYPE', NULL, 'wing_s1_password', NULL, 'pin', 0, 5000, NULL),
  (@tpl_1, 16, 'take_photo', 'PHOTO', 'take_photo', NULL, NULL, NULL, 5000, 3000, NULL),
  (@tpl_1, 17, 'click_all_apps', 'CLICK', 'click_all_apps', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 18, 'swipe_close_app', 'SWIPE', NULL, NULL, 'swipe_close_app', NULL, 0, 1000, NULL),
  (@tpl_1, 19, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- End of WINGBANK seed.
SELECT CONCAT('Imported 1 template(s) + 0 handler(s) for bank=WINGBANK') AS done;