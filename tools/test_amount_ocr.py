"""Test _ocr_field on historical screenshots for multiple banks."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymysql, base64, cv2, json, re
import numpy as np
from app.ocr import _ocr_field

# === CONFIG ===
ARM_ID = 2
LIMIT = 20
BANKS = {
    "ACLEDA": {
        "pay_to_account_no": (24, 28, 43, 77),
        "amount": (30, 36, 41, 78),
    },
    "WINGBANK": {
        "pay_to_account_no": (27, 33, 25, 75),  # adjust if needed
        "amount": (55, 65, 25, 75),              # adjust if needed
    },
}
# ==============

conn = pymysql.connect(host='127.0.0.1', port=3308, user='root', password='wa_unified_2026', database='wa_db')
cur = conn.cursor(pymysql.cursors.DictCursor)

# Get WINGBANK ROIs from DB to use actual config
cur.execute("""SELECT fs.description FROM flow_steps fs 
    JOIN flow_templates ft ON fs.flow_template_id=ft.id 
    WHERE ft.bank_code='WINGBANK' AND ft.arm_id=%s AND fs.action_type='OCR_VERIFY' LIMIT 1""", (ARM_ID,))
wr = cur.fetchone()
if wr and wr['description']:
    wcfg = json.loads(wr['description'])
    wfr = wcfg.get('field_rois', {})
    if 'pay_to_account_no' in wfr:
        r = wfr['pay_to_account_no']
        BANKS['WINGBANK']['pay_to_account_no'] = (r['top_percent'], r['bottom_percent'], r['left_percent'], r['right_percent'])
    if 'amount' in wfr:
        r = wfr['amount']
        BANKS['WINGBANK']['amount'] = (r['top_percent'], r['bottom_percent'], r['left_percent'], r['right_percent'])
    print("WINGBANK ROIs loaded from DB: %s\n" % BANKS['WINGBANK'])
else:
    print("WARNING: WINGBANK has no field_rois in DB, using defaults\n")

total_pass = 0
total_fail = 0
total_skip = 0

for bank, rois in BANKS.items():
    cur.execute("""SELECT tl.id, tl.screenshot_base64, t.amount, t.pay_to_account_no
        FROM transaction_logs tl
        JOIN transactions t ON tl.transaction_id=t.id
        JOIN stations s ON t.station_id=s.id
        WHERE tl.action_type='OCR_VERIFY' AND tl.screenshot_base64 IS NOT NULL
        AND t.pay_from_bank_code=%s AND s.arm_id=%s
        ORDER BY tl.id DESC LIMIT %s""", (bank, ARM_ID, LIMIT))
    rows = cur.fetchall()

    print("=" * 60)
    print("%s ARM-%02d: %d screenshots" % (bank, ARM_ID, len(rows)))
    print("  Account ROI: %s" % str(rois['pay_to_account_no']))
    print("  Amount ROI:  %s" % str(rois['amount']))
    print("=" * 60)

    bank_pass = 0
    bank_fail = 0

    for r in rows:
        img_bytes = base64.b64decode(r['screenshot_base64'])
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]

        amt_roi = rois['amount']
        y1 = int(h * amt_roi[0] / 100); y2 = int(h * amt_roi[1] / 100)
        x1 = int(w * amt_roi[2] / 100); x2 = int(w * amt_roi[3] / 100)
        amt_crop = img[y1:y2, x1:x2]
        amt_text = _ocr_field(amt_crop, "amount")

        acct_roi = rois['pay_to_account_no']
        y1a = int(h * acct_roi[0] / 100); y2a = int(h * acct_roi[1] / 100)
        x1a = int(w * acct_roi[2] / 100); x2a = int(w * acct_roi[3] / 100)
        acct_crop = img[y1a:y2a, x1a:x2a]
        acct_text = _ocr_field(acct_crop, "pay_to_account_no")

        expected_amt = str(r['amount'])
        expected_acct = str(r['pay_to_account_no'])

        nums = re.findall(r'[\d]+\.?[\d]*', amt_text)
        amt_norm = str(float(expected_amt))
        if amt_norm.endswith('.0'): amt_norm = amt_norm[:-2]
        amt_match = any((str(float(n)) if '.' in n else n) == amt_norm or n == expected_amt for n in nums)

        acct_digits = re.sub(r'[^0-9]', '', acct_text)
        acct_match = expected_acct in acct_digits or expected_acct.lstrip('0') in acct_digits
        for i in range(len(expected_acct)):
            suffix = expected_acct[i:]
            if len(suffix) >= 6 and suffix in acct_digits:
                acct_match = True
                break

        status = "PASS" if (amt_match and acct_match) else "FAIL"
        if status == "PASS":
            bank_pass += 1
        else:
            bank_fail += 1

        marker = "" if status == "PASS" else " <<<"
        print("  log_%d acct=%s amt=%s -> acct='%s' amt='%s' %s%s" % (
            r['id'], expected_acct, expected_amt, acct_text[:30], amt_text[:30], status, marker))

    print("  --- %s: %d PASS, %d FAIL ---\n" % (bank, bank_pass, bank_fail))
    total_pass += bank_pass
    total_fail += bank_fail

conn.close()
print("=== TOTAL: %d PASS, %d FAIL ===" % (total_pass, total_fail))
