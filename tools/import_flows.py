"""Import ACLEDA and WINGBANK flow steps from seed into live DB flow templates.
Only imports flow structure (step_name, action_type, etc). Delays reset to 0.
"""
import pymysql

conn = pymysql.connect(host='127.0.0.1', port=3308, user='root', password='wa_unified_2026', database='wa_db')
cur = conn.cursor(pymysql.cursors.DictCursor)

# Find ACLEDA and WINGBANK templates in live DB
cur.execute("SELECT id, bank_code, arm_id, name, total_steps, transfer_type FROM flow_templates WHERE bank_code IN ('ACLEDA','WINGBANK') ORDER BY id")
templates = cur.fetchall()
print("=== Existing templates ===")
for t in templates:
    print(t)

# Seed flow steps: ACLEDA template_id=6, WINGBANK template_id=7
seed_flows = {
    'ACLEDA': [
        (1,'open_app','CLICK','app_icon',None,None,None,1,0,0,None),
        (2,'click_transfer','CLICK','transfer_btn',None,None,None,1,0,0,None),
        (3,'enter_password','TYPE',None,'pwd',None,'password',1,0,0,None),
        (4,'to_acleda','CLICK','to_acleda',None,None,None,1,0,0,None),
        (5,'select_account','CLICK','select_account',None,None,None,1,0,0,None),
        (6,'select_savings_usd','CLICK','savings_usd',None,None,None,1,0,0,None),
        (7,'click_account_input','CLICK','account_input',None,None,None,1,0,0,None),
        (8,'enter_account','TYPE',None,'num',None,'pay_to_account_no',1,0,0,None),
        (9,'click_amount_input','CLICK','amount_input',None,None,None,1,0,0,None),
        (10,'enter_amount','TYPE',None,'amt',None,'amount',1,0,0,None),
        (11,'click_ok','CLICK','amount_ok',None,None,None,1,0,0,None),
        (12,'ocr_verify','OCR_VERIFY',None,None,None,None,0,0,0,'Verify account and amount before confirm'),
        (13,'confirm_transfer','CLICK','confirm_btn',None,None,None,1,0,0,None),
        (14,'take_photo','PHOTO','camera_pos',None,None,None,1,0,0,None),
        (15,'click_all_apps','CLICK','all_apps_btn',None,None,None,1,0,0,None),
        (16,'swipe_close_app','SWIPE',None,None,'close_app',None,1,0,0,None),
        (17,'done','ARM_MOVE',None,None,None,None,0,0,0,None),
    ],
    'WINGBANK': [
        (1,'open_app','CLICK','app_icon',None,None,None,1,0,0,None),
        (2,'click_local_transfer','CLICK','local_transfer',None,None,None,1,0,0,None),
        (3,'enter_password','TYPE',None,'pwd',None,'password',1,0,0,None),
        (4,'to_wing','CLICK','to_wing',None,None,None,1,0,0,None),
        (5,'select_account','CLICK','select_account',None,None,None,1,0,0,None),
        (6,'select_savings_usd','CLICK','savings_usd',None,None,None,1,0,0,None),
        (7,'click_account_input','CLICK','account_input',None,None,None,1,0,0,None),
        (8,'enter_account','TYPE',None,'num',None,'pay_to_account_no',1,0,0,None),
        (9,'click_amount_input','CLICK','amount_input',None,None,None,1,0,0,None),
        (10,'enter_amount','TYPE',None,'num',None,'amount',1,0,0,None),
        (11,'click_tick','CLICK','tick_btn',None,None,None,1,0,0,None),
        (12,'click_send','CLICK','send_btn',None,None,None,1,0,0,None),
        (13,'ocr_verify','OCR_VERIFY',None,None,None,None,0,0,0,'Verify account and amount before confirm'),
        (14,'confirm_transfer','CLICK','confirm_btn',None,None,None,1,0,0,None),
        (15,'enter_password_2','TYPE',None,'pwd',None,'password',1,0,0,None),
        (16,'take_photo','PHOTO','camera_pos',None,None,None,1,0,0,None),
        (17,'click_all_apps','CLICK','all_apps_btn',None,None,None,1,0,0,None),
        (18,'swipe_close_app','SWIPE',None,None,'close_app',None,1,0,0,None),
        (19,'done','ARM_MOVE',None,None,None,None,0,0,0,None),
    ],
}

for t in templates:
    bank = t['bank_code']
    tid = t['id']
    if bank not in seed_flows:
        print(f"  SKIP: {bank} template {tid} — no seed flow")
        continue

    # Check if steps already exist
    cur.execute("SELECT COUNT(*) as cnt FROM flow_steps WHERE flow_template_id = %s", (tid,))
    cnt = cur.fetchone()['cnt']
    if cnt > 0:
        print(f"  SKIP: {bank} template {tid} already has {cnt} steps")
        continue

    steps = seed_flows[bank]
    for s in steps:
        cur.execute(
            """INSERT INTO flow_steps 
            (flow_template_id, step_number, step_name, action_type, ui_element_key, 
             keymap_type, swipe_key, input_source, tap_count, pre_delay_ms, post_delay_ms, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (tid, s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10])
        )

    # Update total_steps
    cur.execute("UPDATE flow_templates SET total_steps = %s WHERE id = %s", (len(steps), tid))
    print(f"  INSERTED: {bank} template {tid} — {len(steps)} steps")

conn.commit()
cur.close()
conn.close()
print("\nDone!")
