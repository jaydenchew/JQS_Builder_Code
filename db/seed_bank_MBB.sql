-- ============================================================
-- Flow seed for MBB (sourced from ARM-08)
-- Exported by db/export_bank_seed.py
--
-- Contains: flow_templates + flow_steps for MBB,
-- No handler flow dependencies.
-- Excludes:  ui_elements, keymaps, swipe_actions, keyboard_configs,
--            references, calibrations - all per-machine, re-capture via Builder.
--
-- DO NOT import this file directly with mysql.
-- Use the wrapper script so the target arm name is injected correctly:
--   py db/import_bank_seed.py db/seed_bank_MBB.sql <ARM_NAME>
-- e.g.: py db/import_bank_seed.py db/seed_bank_MBB.sql ARM-05
--
-- The placeholder {ARM_NAME} below is replaced by import_bank_seed.py.
-- Idempotent: drops existing MBB + handler flows on that arm, reinserts.
-- ============================================================

SET @arm_id = (SELECT id FROM arms WHERE name='{ARM_NAME}');

-- Clear any existing flows for this bank + its handler banks (if any) on this arm.
DELETE FROM flow_steps WHERE flow_template_id IN (SELECT id FROM flow_templates WHERE bank_code = 'MBB' AND arm_id = @arm_id);
DELETE FROM flow_templates WHERE bank_code = 'MBB' AND arm_id = @arm_id;

-- Template: MBB Same Bank Transfer Flow (MBB)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('MBB', @arm_id, 'MBB Same Bank Transfer Flow', 'SAME', 'no_dot', 27);
SET @tpl_1 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_1, 1, 'open_maybank_app', 'CLICK', 'open_maybank_app', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_1, 2, 'click_transfer', 'CLICK', 'click_transfer', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 3, 'type_password', 'TYPE', NULL, 'maybank_s1_password', NULL, 'password', 0, 2000, NULL),
  (@tpl_1, 4, 'confirm_login', 'CLICK', 'confirm_login', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 5, 'transfer_to_other_maybank', 'CLICK', 'transfer_to_other_maybank', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 6, 'select_bank', 'CLICK', 'select_bank', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 7, 'select_maybank', 'CLICK', 'select_maybank', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 8, 'type_account_number', 'TYPE', NULL, 'maybank_s1_accountno', NULL, 'pay_to_account_no', 0, 1000, NULL),
  (@tpl_1, 9, 'confirm_account_no', 'CLICK', 'confirm_account_no', NULL, NULL, NULL, 0, 7000, NULL),
  (@tpl_1, 10, 'type_amount', 'TYPE', NULL, 'maybank_s1_amount', NULL, 'amount', 0, 0, NULL),
  (@tpl_1, 11, 'confirm_amount', 'CLICK', 'confirm_amount', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 12, 'type_reference', 'TYPE', NULL, 'maybank_s1_reference', NULL, 'fixed_text', 0, 3000, 'Transfer'),
  (@tpl_1, 13, 'confirm_reference', 'CLICK', 'confirm_reference', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 14, 'next_1', 'CLICK', 'next_1', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 15, 'ocr_verify_before_transfer', 'OCR_VERIFY', 'ocr_verify_before_transfer', NULL, NULL, NULL, 0, 3000, '{"verify_fields":["pay_to_account_no","amount"]}'),
  (@tpl_1, 16, 'next_2', 'CLICK', 'next_2', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 17, 'approve_transaction', 'CLICK', 'approve_transaction', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 18, 'maybank_random_pin', 'TYPE', NULL, 'maybank_s1_pin', NULL, 'pin', 0, 7000, NULL),
  (@tpl_1, 19, 'ocr_verify_receipt_status', 'OCR_VERIFY', 'ocr_verify_receipt_status', NULL, NULL, NULL, 0, 2000, '{"verify_fields":[],"receipt_status":{"success":["Successful"],"review":[],"failed":[]}}'),
  (@tpl_1, 20, 'share_receipt', 'CLICK', 'share_receipt', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_1, 21, 'take_photo', 'PHOTO', 'camera_pos', NULL, NULL, NULL, 1000, 2000, NULL),
  (@tpl_1, 22, 'close_receipt', 'CLICK', 'close_receipt', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 23, 'done1', 'CLICK', 'done1', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_1, 24, 'logout', 'CLICK', 'logout', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_1, 25, 'click_all_apps', 'CLICK', 'click_all_apps', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_1, 26, 'swipe_up_close_app', 'SWIPE', NULL, NULL, 'swipe_up_close_app', NULL, 0, 1000, NULL),
  (@tpl_1, 27, 'done', 'ARM_MOVE', 'done', NULL, NULL, NULL, 0, 0, NULL);

-- Template: MBB Interbank Transfer Flow (MBB)
INSERT INTO flow_templates (bank_code, arm_id, name, transfer_type, amount_format, total_steps) VALUES
  ('MBB', @arm_id, 'MBB Interbank Transfer Flow', 'INTER', 'no_dot', 33);
SET @tpl_2 = LAST_INSERT_ID();

INSERT INTO flow_steps (flow_template_id, step_number, step_name, action_type, ui_element_key, keymap_type, swipe_key, input_source, pre_delay_ms, post_delay_ms, description) VALUES
  (@tpl_2, 1, 'open_maybank_app_inter', 'CLICK', 'open_maybank_app_inter', NULL, NULL, NULL, 0, 10000, NULL),
  (@tpl_2, 2, 'click_transfer_inter', 'CLICK', 'click_transfer_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 3, 'type_password_inter', 'TYPE', NULL, 'maybank_s1_password', NULL, 'password', 0, 2000, NULL),
  (@tpl_2, 4, 'confirm_login_inter', 'CLICK', 'confirm_login_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 5, 'transfer_to_other_bank_inter', 'CLICK', 'transfer_to_other_bank_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 6, 'select_bank_inter', 'CLICK', 'select_bank_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 7, 'click_bank_name_textbox_inter', 'CLICK', 'click_bank_name_textbox_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 8, 'type_bank_name_inter', 'TYPE', NULL, 'maybank_s1_bankname', NULL, 'pay_to_bank_name', 0, 3000, NULL),
  (@tpl_2, 9, 'select_searched_bank_1_inter', 'CLICK', 'select_searched_bank_1_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 10, 'select_searched_bank_2_inter', 'CLICK', 'select_searched_bank_2_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 11, 'type_account_number_inter', 'TYPE', NULL, 'maybank_s1_accountno', NULL, 'pay_to_account_no', 0, 1000, NULL),
  (@tpl_2, 12, 'confirm_account_no_inter', 'CLICK', 'confirm_account_no_inter', NULL, NULL, NULL, 0, 7000, NULL),
  (@tpl_2, 13, 'select_transfer_type_inter', 'CLICK', 'select_transfer_type_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 14, 'fund_transfer_inter', 'CLICK', 'fund_transfer_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 15, 'next_1_inter', 'CLICK', 'next_1_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 16, 'type_amount_inter', 'TYPE', NULL, 'maybank_s1_amount', NULL, 'amount', 0, 0, NULL),
  (@tpl_2, 17, 'confirm_amount_inter', 'CLICK', 'confirm_amount_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 18, 'type_reference_inter', 'TYPE', NULL, 'maybank_s1_reference', NULL, 'fixed_text', 0, 3000, 'Transfer'),
  (@tpl_2, 19, 'confirm_reference_inter', 'CLICK', 'confirm_reference_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 20, 'next_2_inter', 'CLICK', 'next_2_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 21, 'ocr_verify_before_transfer_inter', 'OCR_VERIFY', 'ocr_verify_before_transfer_inter', NULL, NULL, NULL, 0, 3000, '{"verify_fields":["pay_to_account_no","amount"]}'),
  (@tpl_2, 22, 'next_3_inter', 'CLICK', 'next_3_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 23, 'approve_transaction_inter', 'CLICK', 'approve_transaction_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 24, 'maybank_random_pin_inter', 'TYPE', NULL, 'maybank_s1_pin', NULL, 'pin', 0, 7000, NULL),
  (@tpl_2, 25, 'ocr_verify_receipt_status_inter', 'OCR_VERIFY', 'ocr_verify_receipt_status_inter', NULL, NULL, NULL, 0, 2000, '{"verify_fields":[],"receipt_status":{"success":["Successful"],"review":[],"failed":[]}}'),
  (@tpl_2, 26, 'share_receipt_inter', 'CLICK', 'share_receipt_inter', NULL, NULL, NULL, 0, 3000, NULL),
  (@tpl_2, 27, 'take_photo_inter', 'PHOTO', 'take_photo_inter', NULL, NULL, NULL, 1000, 2000, NULL),
  (@tpl_2, 28, 'close_receipt_inter', 'CLICK', 'close_receipt_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 29, 'done1_inter', 'CLICK', 'done1_inter', NULL, NULL, NULL, 0, 2000, NULL),
  (@tpl_2, 30, 'logout_inter', 'CLICK', 'logout_inter', NULL, NULL, NULL, 0, 5000, NULL),
  (@tpl_2, 31, 'click_all_apps_inter', 'CLICK', 'click_all_apps_inter', NULL, NULL, NULL, 0, 1000, NULL),
  (@tpl_2, 32, 'swipe_up_close_app_inter', 'SWIPE', NULL, NULL, 'swipe_up_close_app', NULL, 0, 1000, NULL),
  (@tpl_2, 33, 'done_inter', 'ARM_MOVE', 'done_inter', NULL, NULL, NULL, 0, 0, NULL);

-- End of MBB seed.
SELECT CONCAT('Imported 2 template(s) + 0 handler(s) for bank=MBB') AS done;