-- ============================================================
-- Flow seed for ACLEDA (sourced from ARM-01)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for ACLEDA,
-- plus 1 handler flow template(s) referenced by CHECK_SCREEN steps.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_ACLEDA.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_ACLEDA.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing ACLEDA + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'ACLEDA' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'ACLEDA' AND arm_id = @arm_id;
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'ACLEDA_AFTER_POPUP' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'ACLEDA_AFTER_POPUP' AND arm_id = @arm_id;

-- Template: ACLEDA_AFTER_POPUP Transfer Flow (ACLEDA_AFTER_POPUP)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('ACLEDA_AFTER_POPUP', @arm_id, 'ACLEDA_AFTER_POPUP Transfer Flow', NULL, NULL, 2);
SET @handler_1_id = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@handler_1_id, 1, 'tick_do_not_show_again', 'CLICK', 'tick_do_not_show_again', NULL, NULL, NULL, 0, 1000, NULL),
  (@handler_1_id, 2, 'close_popup', 'CLICK', 'close_popup', NULL, NULL, NULL, 0, 2000, NULL);

-- Template: ACLEDA Transfer Flow (ACLEDA)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('ACLEDA', @arm_id, 'ACLEDA Transfer Flow', 'SAME', 'always_decimal', 18);
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'open_app', 'CLICK', 'open_app', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 2, 'click_transfer', 'CLICK', 'click_transfer', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 3, 'enter_password', 'TYPE', NULL, 'acleda_s1_password', NULL, 'password', 0, 5000, NULL),
  (@tpl_1, 4, 'check_homepage_popup', 'CHECK_SCREEN', 'check_homepage_popup', NULL, NULL, NULL, 0, 3000, CONCAT('{"reference":"arm01_acleda_3","handler_flow":"ACLEDA_AFTER_POPUP__', @handler_1_id, '","threshold":0.8,"max_retries":3,"roi":{"top_percent":25,"bottom_percent":91,"left_percent":19,"right_percent":87}}')),
  (@tpl_1, 5, 'to_acleda', 'CLICK', 'to_acleda', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 6, 'select_account', 'CLICK', 'select_account', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 7, 'select_savings_usd', 'CLICK', 'select_savings_usd', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 8, 'click_account_input', 'CLICK', 'click_account_input', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 9, 'enter_account', 'TYPE', NULL, 'acleda_s1_accountno', NULL, 'pay_to_account_no', 0, 1000, NULL),
  (@tpl_1, 10, 'click_amount_input', 'CLICK', 'click_amount_input', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 11, 'enter_amount', 'TYPE', NULL, 'acleda_s1_amount', NULL, 'amount', 0, 2000, NULL),
  (@tpl_1, 12, 'click_ok', 'CLICK', 'click_ok', NULL, NULL, NULL, 0, 7000, NULL),
  (@tpl_1, 13, 'ocr_verify_before_transfer', 'OCR_VERIFY', 'ocr_verify_before_transfer', NULL, NULL, NULL, 0, 2000, '{"verify_fields":["pay_to_account_no","amount"],"field_rois":{"pay_to_account_no":{"top_percent":24,"bottom_percent":28,"left_percent":43,"right_percent":77},"amount":{"top_percent":30,"bottom_percent":36,"left_percent":41,"right_percent":78},"pay_to_account_name":{"top_percent":19,"bottom_percent":25,"left_percent":41,"right_percent":74}},"roi":{"top_percent":17,"bottom_percent":37,"left_percent":26,"right_percent":83}}'),
  (@tpl_1, 14, 'confirm_transfer', 'CLICK', 'confirm_transfer', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 15, 'take_photo_receipt', 'PHOTO', 'take_photo_receipt', NULL, NULL, NULL, 5000, 2000, NULL),
  (@tpl_1, 16, 'click_all_apps', 'CLICK', 'click_all_apps', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 17, 'swipe_close_app', 'SWIPE', NULL, NULL, 'swipe_close_app', NULL, 0, 2000, NULL),
  (@tpl_1, 18, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- Template: ACLEDA Interbank Transfer Flow (ACLEDA)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('ACLEDA', @arm_id, 'ACLEDA Interbank Transfer Flow', 'INTER', 'always_decimal', 24);
SET @tpl_2 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_2, 1, 'open_app_inter', 'CLICK', 'open_app_inter', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_2, 2, 'click_transfer_inter', 'CLICK', 'click_transfer_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 3, 'enter_password_inter', 'TYPE', NULL, 'acleda_s1_password', NULL, 'password', 0, 5000, NULL),
  (@tpl_2, 4, 'check_homepage_popup_inter', 'CHECK_SCREEN', 'check_homepage_popup_inter', NULL, NULL, NULL, 0, 3000, CONCAT('{"reference":"arm01_acleda_3","handler_flow":"ACLEDA_AFTER_POPUP__', @handler_1_id, '","threshold":0.8,"max_retries":3,"roi":{"top_percent":25,"bottom_percent":92,"left_percent":19,"right_percent":86}}')),
  (@tpl_2, 5, 'local_transfer_inter', 'CLICK', 'local_transfer_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 6, 'to_bank_accounts_inter', 'CLICK', 'to_bank_accounts_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 7, 'click_search_inter', 'CLICK', 'click_search_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 8, 'type_bank_name_inter', 'TYPE', NULL, 'acleda_s1_bankname', NULL, 'pay_to_bank_name', 0, 2000, NULL),
  (@tpl_2, 9, 'click_on_search_result_inter', 'CLICK', 'click_on_search_result_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 10, 'select_account_inter', 'CLICK', 'select_account_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 11, 'select_savings_usd_inter', 'CLICK', 'select_savings_usd_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 12, 'click_account_input_inter', 'CLICK', 'click_account_input_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 13, 'enter_account_inter', 'TYPE', NULL, 'acleda_s1_accountno', NULL, 'pay_to_account_no', 0, 1000, NULL),
  (@tpl_2, 14, 'click_amount_input_inter', 'CLICK', 'click_amount_input_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 15, 'enter_amount_inter', 'TYPE', NULL, 'acleda_s1_amount', NULL, 'amount', 0, 2000, NULL),
  (@tpl_2, 16, 'click_purpose_inter', 'CLICK', 'click_purpose_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 17, 'good_or_services_inter', 'CLICK', 'good_or_services_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 18, 'click_ok_inter', 'CLICK', 'click_ok_inter', NULL, NULL, NULL, 0, 7000, NULL),
  (@tpl_2, 19, 'ocr_verify_before_transfer_inter', 'OCR_VERIFY', 'ocr_verify_before_transfer_inter', NULL, NULL, NULL, 0, 2000, '{"verify_fields":["pay_to_account_no","amount"],"field_rois":{"pay_to_account_no":{"top_percent":24,"bottom_percent":29,"left_percent":41,"right_percent":78},"amount":{"top_percent":30,"bottom_percent":37,"left_percent":40,"right_percent":80},"pay_to_account_name":{"top_percent":19,"bottom_percent":25,"left_percent":41,"right_percent":80}},"roi":{"top_percent":17,"bottom_percent":38,"left_percent":26,"right_percent":82}}'),
  (@tpl_2, 20, 'confirm_transfer_inter', 'CLICK', 'confirm_transfer_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 21, 'take_photo_receipt_inter', 'PHOTO', 'take_photo_receipt_inter', NULL, NULL, NULL, 5000, 2000, NULL),
  (@tpl_2, 22, 'click_all_apps_inter', 'CLICK', 'click_all_apps_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 23, 'swipe_close_app_inter', 'SWIPE', NULL, NULL, 'swipe_close_app', NULL, 0, 2000, NULL),
  (@tpl_2, 24, 'done_inter', 'ARM_MOVE', 'done_inter', NULL, NULL, NULL, 0, 0, NULL);

-- End of ACLEDA seed.
SELECT CONCAT('Imported 2 template(s) + 1 handler(s) for bank=ACLEDA') AS done;