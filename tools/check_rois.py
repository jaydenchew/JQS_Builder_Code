import pymysql, json
conn = pymysql.connect(host='127.0.0.1', port=3308, user='root', password='wa_unified_2026', database='wa_db')
cur = conn.cursor(pymysql.cursors.DictCursor)
cur.execute("""SELECT fs.step_name, fs.description FROM flow_steps fs 
    JOIN flow_templates ft ON fs.flow_template_id=ft.id 
    WHERE ft.bank_code='ACLEDA' AND ft.arm_id=2 AND fs.action_type='OCR_VERIFY'""")
for r in cur.fetchall():
    desc = json.loads(r['description']) if r['description'] else {}
    fr = desc.get('field_rois', {})
    print(r['step_name'])
    for k,v in fr.items():
        print("  %s: top=%s bottom=%s left=%s right=%s" % (k, v.get('top_percent'), v.get('bottom_percent'), v.get('left_percent'), v.get('right_percent')))
conn.close()
