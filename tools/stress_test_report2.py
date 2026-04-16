"""Stress Test Report Generator — process_id 143-195"""
import pymysql
from datetime import datetime

conn = pymysql.connect(host='127.0.0.1', port=3308, user='root', password='wa_unified_2026', database='wa_db')
cur = conn.cursor(pymysql.cursors.DictCursor)

cur.execute("""SELECT t.id, t.process_id, t.pay_from_bank_code, t.pay_to_bank_code,
    t.pay_to_account_no, t.pay_to_account_name, t.amount, t.status, t.error_message,
    t.station_id, t.created_at, t.started_at, t.finished_at, t.callback_sent_at,
    a.name as arm_name
    FROM transactions t
    LEFT JOIN stations s ON t.station_id=s.id
    LEFT JOIN arms a ON s.arm_id=a.id
    WHERE t.process_id BETWEEN 143 AND 195
    ORDER BY t.process_id""")
rows = cur.fetchall()
conn.close()

# Stats
total = len(rows)
by_status = {}
by_arm = {}
by_bank = {}
by_arm_bank = {}
stall_details = []
callback_missing = []
durations_by_bank = {}
durations_by_arm = {}
durations_by_arm_bank = {}
all_durations = []

for r in rows:
    st = r['status']
    by_status[st] = by_status.get(st, 0) + 1
    
    arm = r['arm_name'] or 'unassigned'
    by_arm.setdefault(arm, {'total':0,'success':0,'stall':0,'failed':0})
    by_arm[arm]['total'] += 1
    by_arm[arm][st] = by_arm[arm].get(st, 0) + 1
    
    bank = r['pay_from_bank_code']
    by_bank.setdefault(bank, {'total':0,'success':0,'stall':0,'failed':0})
    by_bank[bank]['total'] += 1
    by_bank[bank][st] = by_bank[bank].get(st, 0) + 1
    
    key = '%s/%s' % (arm, bank)
    by_arm_bank.setdefault(key, {'total':0,'success':0,'stall':0,'failed':0})
    by_arm_bank[key]['total'] += 1
    by_arm_bank[key][st] = by_arm_bank[key].get(st, 0) + 1
    
    if st == 'stall':
        stall_details.append(r)
    
    if r['finished_at'] and not r['callback_sent_at']:
        callback_missing.append(r['process_id'])
    
    if r['started_at'] and r['finished_at'] and st == 'success':
        d = (r['finished_at'] - r['started_at']).total_seconds()
        all_durations.append(d)
        durations_by_bank.setdefault(bank, []).append(d)
        durations_by_arm.setdefault(arm, []).append(d)
        durations_by_arm_bank.setdefault(key, []).append(d)

# Recipient summary
recipients = {}
for r in rows:
    if r['status'] == 'success':
        name = r['pay_to_account_name']
        recipients.setdefault(name, {'acct': r['pay_to_account_no'], 'txns': [], 'total': 0})
        recipients[name]['txns'].append(r)
        recipients[name]['total'] += float(r['amount'])

# Time range
first = min(r['created_at'] for r in rows if r['created_at'])
last = max(r['finished_at'] for r in rows if r['finished_at'])

# Print report
print("# Stress Test Report #2 — 2026-04-16")
print()
print("> Process ID Range: 143-195 (%d transactions)" % total)
print("> Period: %s to %s" % (first.strftime('%H:%M:%S'), last.strftime('%H:%M:%S')))
print("> Arms: %s" % ', '.join(sorted(by_arm.keys())))
print("> Banks: %s" % ', '.join(sorted(by_bank.keys())))
print()

print("## Summary")
print()
print("| Metric | Value |")
print("|--------|-------|")
print("| Total transactions | %d |" % total)
for st in ['success', 'stall', 'failed']:
    if st in by_status:
        pct = by_status[st] / total * 100
        print("| %s | %d (%.1f%%) |" % (st.capitalize(), by_status[st], pct))
executed = sum(1 for r in rows if r['status'] in ('success', 'stall'))
if executed:
    success_count = by_status.get('success', 0)
    print("| **Actual execution success rate** | **%d/%d (%.1f%%)** |" % (success_count, executed, success_count/executed*100))
print("| Callbacks sent | %d/%d |" % (total - len(callback_missing), total))
print()

print("## Performance — Execution Duration (successful only)")
print()
if all_durations:
    print("| Metric | Value |")
    print("|--------|-------|")
    print("| Average | %.1fs |" % (sum(all_durations)/len(all_durations)))
    print("| Median | %.1fs |" % sorted(all_durations)[len(all_durations)//2])
    print("| Min | %.1fs |" % min(all_durations))
    print("| Max | %.1fs |" % max(all_durations))
    print("| Total successful | %d |" % len(all_durations))
print()

print("### Average Duration by Bank")
print()
print("| Bank | Avg Duration | Count |")
print("|------|-------------|-------|")
for bank in sorted(durations_by_bank.keys()):
    d = durations_by_bank[bank]
    print("| %s | %.1fs | %d |" % (bank, sum(d)/len(d), len(d)))
print()

print("### Average Duration by ARM")
print()
print("| ARM | Avg Duration | Count |")
print("|-----|-------------|-------|")
for arm in sorted(durations_by_arm.keys()):
    d = durations_by_arm[arm]
    print("| %s | %.1fs | %d |" % (arm, sum(d)/len(d), len(d)))
print()

print("### Average Duration by ARM + Bank")
print()
print("| ARM / Bank | Avg Duration | Count | Success Rate |")
print("|------------|-------------|-------|-------------|")
for key in sorted(by_arm_bank.keys()):
    ab = by_arm_bank[key]
    d = durations_by_arm_bank.get(key, [])
    avg = "%.1fs" % (sum(d)/len(d)) if d else "-"
    rate = ab.get('success',0)/ab['total']*100 if ab['total'] else 0
    print("| %s | %s | %d/%d | %.0f%% |" % (key, avg, ab.get('success',0), ab['total'], rate))
print()

print("## Stall Analysis (%d incidents)" % len(stall_details))
print()
if stall_details:
    print("| PID | ARM | Bank | Error |")
    print("|-----|-----|------|-------|")
    for s in stall_details:
        bank = s['pay_from_bank_code']
        if bank != s['pay_to_bank_code']:
            bank = '%s->%s' % (bank, s['pay_to_bank_code'])
        print("| %d | %s | %s | %s |" % (s['process_id'], s['arm_name'], bank, (s['error_message'] or '')[:60]))
print()

print("## Successful Transfers by Recipient")
print()
print("| Recipient | Account | Txns | Total Received |")
print("|-----------|---------|------|----------------|")
total_amt = 0
total_txns = 0
for name in sorted(recipients.keys()):
    rec = recipients[name]
    print("| %s | %s | %d | $%.2f |" % (name, rec['acct'], len(rec['txns']), rec['total']))
    total_amt += rec['total']
    total_txns += len(rec['txns'])
print("| **Total** | | **%d** | **$%.2f** |" % (total_txns, total_amt))
print()

print("## All Transactions (%d)" % total)
print()
print("| PID | ARM | Bank | Amount | To Account | To Name | Status | Duration | Note |")
print("|-----|-----|------|--------|------------|---------|--------|----------|------|")
for r in rows:
    arm = (r['arm_name'] or '-')
    bank = r['pay_from_bank_code']
    if bank != r['pay_to_bank_code']:
        bank = '%s->%s' % (bank, r['pay_to_bank_code'])
    
    dur = ''
    if r['started_at'] and r['finished_at']:
        dur = '%.0fs' % (r['finished_at'] - r['started_at']).total_seconds()
    
    note = ''
    if r['status'] == 'stall':
        note = r['error_message'][:40] if r['error_message'] else ''
    elif r['status'] == 'failed':
        note = 'auto-rejected'
    
    print("| %d | %s | %s | $%.2f | %s | %s | %s | %s | %s |" % (
        r['process_id'], arm, bank, float(r['amount']),
        r['pay_to_account_no'], r['pay_to_account_name'][:15],
        r['status'], dur, note))
