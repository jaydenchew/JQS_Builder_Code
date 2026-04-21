-- ============================================================
-- Flow seed for CIMB (sourced from ARM-08)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for CIMB,
-- No handler flow dependencies.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_CIMB.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_CIMB.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing CIMB + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Guard: fail loudly if arm does not exist on target machine.
SELECT IFNULL(@arm_id, (SELECT 1 FROM nonexistent_arm_check)) AS ok;

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'CIMB' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'CIMB' AND arm_id = @arm_id;

-- Template: CIMB Same Bank Transfer Flow (CIMB)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format) VALUES
  ('CIMB', @arm_id, 'CIMB Same Bank Transfer Flow', 'SAME', 'no_dot');
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'open_cimb_app', 'CLICK', 'open_cimb_app', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 2, 'check_homepage_popup', 'CHECK_SCREEN', 'check_homepage_popup', NULL, NULL, NULL, 2000, 3000, '{"reference":"","handler_flow":"","threshold":0.7,"max_retries":3,"roi":null}'),
  (@tpl_1, 3, 'login_with_password', 'CLICK', 'login_with_password', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 4, 'click_password_textbox', 'CLICK', 'click_password_textbox', NULL, NULL, NULL, 0, 0, NULL),
  (@tpl_1, 5, 'type_password', 'TYPE', NULL, 'cimb_s1_password', NULL, 'password', 2000, 2000, NULL),
  (@tpl_1, 6, 'confirm_login', 'CLICK', 'confirm_login', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 7, 'transfer_to_cimb', 'CLICK', 'transfer_to_cimb', NULL, NULL, NULL, 0, 4000, NULL),
  (@tpl_1, 8, 'select_account', 'CLICK', 'select_account', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 9, 'select_payment_mode', 'CLICK', 'select_payment_mode', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 10, 'other_cimb_account', 'CLICK', 'other_cimb_account', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 11, 'next_1', 'CLICK', 'next_1', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 12, 'new_transfer', 'CLICK', 'new_transfer', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 13, 'click_account_number_text_box', 'CLICK', 'click_account_number_text_box', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 14, 'type_account_number', 'TYPE', NULL, 'cimb_s1_accountno', NULL, 'pay_to_account_no', 0, 3000, NULL),
  (@tpl_1, 15, 'next_2', 'CLICK', 'next_2', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 16, 'next_3', 'CLICK', 'next_3', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 17, 'next_4', 'CLICK', 'next_4', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 18, 'type_amount', 'TYPE', NULL, 'cimb_s1_amount', NULL, 'amount', 1000, 2000, NULL),
  (@tpl_1, 19, 'next_5', 'CLICK', 'next_5', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 20, 'type_reference', 'TYPE', NULL, 'cimb_s1_reference', NULL, 'fixed_text', 2000, 2000, 'Transfer'),
  (@tpl_1, 21, 'next_6', 'CLICK', 'next_6', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 22, 'ocr_verify_before_transfer', 'OCR_VERIFY', 'ocr_verify_before_transfer', NULL, NULL, NULL, 0, 5000, '{"verify_fields":["pay_to_account_no","amount"]}'),
  (@tpl_1, 23, 'click_submit', 'CLICK', 'click_submit', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 24, 'approve_transaction', 'CLICK', 'approve_transaction', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 25, 'type_pin', 'TYPE', NULL, 'cimb_s1_pin', NULL, 'pin', 0, 7000, NULL),
  (@tpl_1, 26, 'click_share_receipt', 'CLICK', 'click_share_receipt', NULL, NULL, NULL, 2000, 3000, NULL),
  (@tpl_1, 27, 'ocr_verify_receipt_status', 'OCR_VERIFY', 'ocr_verify_receipt_status', NULL, NULL, NULL, 0, 2000, '{"verify_fields":[],"receipt_status":{"success":["Successful"],"review":[],"failed":[]}}'),
  (@tpl_1, 28, 'take_photo', 'PHOTO', 'camera_pos', NULL, NULL, NULL, 1000, 2000, NULL),
  (@tpl_1, 29, 'close_receipt', 'CLICK', 'close_receipt', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 30, 'close_receipt_2', 'CLICK', 'close_receipt_2', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 31, 'click_logout', 'CLICK', 'click_logout', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 32, 'confirm_logout', 'CLICK', 'confirm_logout', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 33, 'click_all_apps', 'CLICK', 'click_all_apps', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 34, 'swipe_up_close_app', 'SWIPE', NULL, NULL, 'swipe_up_close_app', NULL, 0, 1000, NULL),
  (@tpl_1, 35, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- Template: CIMB Interbank Transfer Flow (CIMB)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format) VALUES
  ('CIMB', @arm_id, 'CIMB Interbank Transfer Flow', 'INTER', 'no_dot');
SET @tpl_2 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_2, 1, 'open_cimb_app_inter', 'CLICK', 'open_cimb_app_inter', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_2, 2, 'check_homepage_popup_inter', 'CHECK_SCREEN', 'check_homepage_popup_inter', NULL, NULL, NULL, 2000, 3000, '{"reference":"","handler_flow":"","threshold":0.7,"max_retries":3,"roi":null}'),
  (@tpl_2, 3, 'login_with_password_inter', 'CLICK', 'login_with_password_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 4, 'click_password_textbox_inter', 'CLICK', 'click_password_textbox_inter', NULL, NULL, NULL, 0, 0, NULL),
  (@tpl_2, 5, 'type_password_inter', 'TYPE', NULL, 'cimb_s1_password', NULL, 'password', 2000, 2000, NULL),
  (@tpl_2, 6, 'confirm_login_inter', 'CLICK', 'confirm_login_inter', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_2, 7, 'transfer_to_other_bank_inter', 'CLICK', 'transfer_to_other_bank_inter', NULL, NULL, NULL, 0, 4000, NULL),
  (@tpl_2, 8, 'select_account_inter', 'CLICK', 'select_account_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 9, 'select_payment_mode_inter', 'CLICK', 'select_payment_mode_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 10, 'duitnow_transfer_inter', 'CLICK', 'duitnow_transfer_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 11, 'next_1_inter', 'CLICK', 'next_1_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 12, 'new_transfer_inter', 'CLICK', 'new_transfer_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 13, 'select_transfer_by_accountno_inter', 'CLICK', 'select_transfer_by_accountno_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 14, 'click_bank_name_textbox_inter', 'CLICK', 'click_bank_name_textbox_inter', NULL, NULL, NULL, 0, 1500, NULL),
  (@tpl_2, 15, 'type_bank_name_inter', 'TYPE', NULL, 'cimb_s1_bankname', NULL, 'pay_to_bank_name', 0, 2000, NULL),
  (@tpl_2, 16, 'select_searched_bank_1_inter', 'CLICK', 'select_searched_bank_1_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 17, 'select_searched_bank_2_inter', 'CLICK', 'select_searched_bank_2_inter', NULL, NULL, NULL, 0, 1500, NULL),
  (@tpl_2, 18, 'type_account_number_inter', 'TYPE', NULL, 'cimb_s1_accountno', NULL, 'pay_to_account_no', 0, 3000, NULL),
  (@tpl_2, 19, 'ok_1_inter', 'CLICK', 'ok_1_inter', NULL, NULL, NULL, 0, 500, NULL),
  (@tpl_2, 20, 'select_beneficiary_resident_inter', 'CLICK', 'select_beneficiary_resident_inter', NULL, NULL, NULL, 0, 500, NULL),
  (@tpl_2, 21, 'select_malaysian_inter', 'CLICK', 'select_malaysian_inter', NULL, NULL, NULL, 0, 0, NULL),
  (@tpl_2, 22, 'next_2_inter', 'CLICK', 'next_2_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 23, 'next_3_inter', 'CLICK', 'next_3_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 24, 'type_amount_inter', 'TYPE', NULL, 'cimb_s1_amount', NULL, 'amount', 1000, 2000, NULL),
  (@tpl_2, 25, 'next_5_inter', 'CLICK', 'next_5_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 26, 'type_reference_inter', 'TYPE', NULL, 'cimb_s1_reference', NULL, 'fixed_text', 2000, 2000, 'Transfer'),
  (@tpl_2, 27, 'next_6_inter', 'CLICK', 'next_6_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 28, 'ocr_verify_before_transfer_inter', 'OCR_VERIFY', 'ocr_verify_before_transfer_inter', NULL, NULL, NULL, 0, 5000, '{"verify_fields":["pay_to_account_no","amount"]}'),
  (@tpl_2, 29, 'click_submit_inter', 'CLICK', 'click_submit_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 30, 'approve_transaction_inter', 'CLICK', 'approve_transaction_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 31, 'type_pin_inter', 'TYPE', NULL, 'cimb_s1_pin', NULL, 'pin', 0, 7000, NULL),
  (@tpl_2, 32, 'click_share_receipt_inter', 'CLICK', 'click_share_receipt_inter', NULL, NULL, NULL, 2000, 3000, NULL),
  (@tpl_2, 33, 'ocr_verify_receipt_status_inter', 'OCR_VERIFY', 'ocr_verify_receipt_status_inter', NULL, NULL, NULL, 0, 2000, '{"verify_fields":[],"receipt_status":{"success":["Successful"],"review":[],"failed":[]}}'),
  (@tpl_2, 34, 'take_photo_inter', 'PHOTO', 'take_photo_inter', NULL, NULL, NULL, 1000, 2000, NULL),
  (@tpl_2, 35, 'close_receipt_inter', 'CLICK', 'close_receipt_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 36, 'close_receipt_2_inter', 'CLICK', 'close_receipt_2_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 37, 'click_logout_inter', 'CLICK', 'click_logout_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 38, 'confirm_logout_inter', 'CLICK', 'confirm_logout_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 39, 'click_all_apps_inter', 'CLICK', 'click_all_apps_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 40, 'swipe_up_close_app_inter', 'SWIPE', NULL, NULL, 'swipe_up_close_app', NULL, 0, 1000, NULL),
  (@tpl_2, 41, 'done_inter', 'ARM_MOVE', 'done_inter', NULL, NULL, NULL, 0, 0, NULL);

-- End of CIMB seed.
SELECT CONCAT('Imported 2 template(s) + 0 handler(s) for bank=CIMB') AS done;