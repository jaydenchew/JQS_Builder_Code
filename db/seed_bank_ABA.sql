-- ============================================================
-- Flow seed for ABA (sourced from ARM-01)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for ABA,
-- plus 1 handler flow template(s) referenced by CHECK_SCREEN steps.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_ABA.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_ABA.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing ABA + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Guard: fail loudly if arm does not exist on target machine.
SELECT IFNULL(@arm_id, (SELECT 1 FROM nonexistent_arm_check)) AS ok;

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'ABA' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'ABA' AND arm_id = @arm_id;
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'ABA_SLIDE_RETRY' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'ABA_SLIDE_RETRY' AND arm_id = @arm_id;

-- Template: ABA_SLIDE_RETRY Transfer Flow (ABA_SLIDE_RETRY)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format) VALUES
  ('ABA_SLIDE_RETRY', @arm_id, 'ABA_SLIDE_RETRY Transfer Flow', NULL, 'always_decimal');
SET @handler_1_id = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@handler_1_id, 1, 'swipe_retry', 'SWIPE', NULL, NULL, 'swipe_retry', NULL, 0, 0, NULL);

-- Template: ABA Same Bank Transfer Flow (ABA)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format) VALUES
  ('ABA', @arm_id, 'ABA Same Bank Transfer Flow', 'SAME', 'always_decimal');
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'open_app', 'CLICK', 'open_app', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 2, 'click_send', 'CLICK', 'click_send', NULL, NULL, NULL, 0, 1500, NULL),
  (@tpl_1, 3, 'to_other_aba', 'CLICK', 'to_other_aba', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 4, 'enter_password', 'TYPE', NULL, 'aba_s1_password', NULL, 'password', 0, 8000, NULL),
  (@tpl_1, 5, 'select_account', 'CLICK', 'select_account', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 6, 'select_usd', 'CLICK', 'select_usd', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 7, 'click_account_input', 'CLICK', 'click_account_input', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 8, 'enter_account', 'TYPE', NULL, 'aba_s1_accountno', NULL, 'pay_to_account_no', 0, 500, NULL),
  (@tpl_1, 9, 'done_enter_account', 'CLICK', 'done_enter_account', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 10, 'enter_amount', 'TYPE', NULL, 'aba_s1_amount', NULL, 'amount', 0, 500, NULL),
  (@tpl_1, 11, 'click_transfer', 'CLICK', 'click_transfer', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 12, 'ocr_verify_before_transfer', 'OCR_VERIFY', 'ocr_verify_before_transfer', NULL, NULL, NULL, 1000, 3000, '{"verify_fields":["pay_to_account_no","amount"],"field_rois":{"pay_to_account_no":{"top_percent":41,"bottom_percent":48,"left_percent":27,"right_percent":81},"amount":{"top_percent":28,"bottom_percent":36,"left_percent":32,"right_percent":74},"pay_to_account_name":{"top_percent":47,"bottom_percent":55,"left_percent":32,"right_percent":77}},"roi":{"top_percent":29,"bottom_percent":59,"left_percent":18,"right_percent":87}}'),
  (@tpl_1, 13, 'slide_confirm', 'SWIPE', NULL, NULL, 'slide_confirm', NULL, 0, 500, NULL),
  (@tpl_1, 14, 'check_slide_success', 'CHECK_SCREEN', 'check_slide_success', NULL, NULL, NULL, 0, 0, CONCAT('{"reference":"check_slide_success","handler_flow":"ABA_SLIDE_RETRY__', @handler_1_id, '","threshold":0.8,"max_retries":3,"roi":{"top_percent":36,"bottom_percent":86,"left_percent":17,"right_percent":83}}')),
  (@tpl_1, 15, 'enter_password_2', 'TYPE', NULL, 'aba_s1_password', NULL, 'password', 0, 3000, NULL),
  (@tpl_1, 16, 'take_photo_receipt', 'PHOTO', 'take_photo_receipt', NULL, NULL, NULL, 5000, 500, NULL),
  (@tpl_1, 17, 'click_all_apps', 'CLICK', 'click_all_apps', NULL, NULL, NULL, 0, 200, NULL),
  (@tpl_1, 18, 'swipe_close_app', 'SWIPE', NULL, NULL, 'swipe_close_app', NULL, 0, 300, NULL),
  (@tpl_1, 19, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- End of ABA seed.
SELECT CONCAT('Imported 1 template(s) + 1 handler(s) for bank=ABA') AS done;