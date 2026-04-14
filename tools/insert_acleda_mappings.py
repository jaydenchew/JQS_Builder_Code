import pymysql
conn = pymysql.connect(host='127.0.0.1', port=3308, user='root',
                       password='wa_unified_2026', database='wa_db')
cur = conn.cursor()

mappings = [
    ('ACLEDA', 'EMONEY', 'emoney', 'EMoney'),
    ('ACLEDA', 'TRUEMONEY', 'truemoney', 'TrueMoney Cambodia'),
    ('ACLEDA', 'ABA', 'aba', 'ABA Bank'),
    ('ACLEDA', 'AMK', 'amk', 'AMK Microfinance Plc.'),
    ('ACLEDA', 'APD', 'apd', 'APD Bank'),
    ('ACLEDA', 'ARDB', 'ardb', 'ARDB Bank'),
    ('ACLEDA', 'AEON', 'aeon', 'Aeon Specialized Bank'),
    ('ACLEDA', 'ALPHA', 'alpha', 'Alpha Commercial Bank PLC'),
    ('ACLEDA', 'AMRET', 'amret', 'Amret Plc.'),
    ('ACLEDA', 'ASIAWEI', 'asia wei luy', 'Asia Wei Luy'),
    ('ACLEDA', 'BIDC', 'bidc', 'BIDC Bank'),
    ('ACLEDA', 'BRED', 'bred', 'BRED Bank (Cambodia) Plc'),
    ('ACLEDA', 'BRIDGE', 'bridge', 'BRIDGE Bank'),
    ('ACLEDA', 'BOCHK', 'bank of china', 'Bank of China (Hong Kong)'),
    ('ACLEDA', 'BONGLOY', 'bongloy', 'BongLoy'),
    ('ACLEDA', 'BOOYOUNG', 'booyoung', 'Booyoung Khmer Bank'),
    ('ACLEDA', 'CATHAY', 'cathay', 'CATHAY UNITED BANK'),
    ('ACLEDA', 'CCU', 'ccu', 'CCU Commercial Bank PLC.'),
    ('ACLEDA', 'CIMB', 'cimb', 'CIMB'),
    ('ACLEDA', 'CAB', 'cambodia asia', 'Cambodia Asia Bank'),
    ('ACLEDA', 'CPB', 'cambodia post', 'Cambodia Post Bank Plc'),
    ('ACLEDA', 'CAMPU', 'cambodian public', 'Cambodian Public Bank Plc'),
    ('ACLEDA', 'CANADIA', 'canadia', 'Canadia Bank Plc'),
    ('ACLEDA', 'CHIEF', 'chief', 'Chief (Cambodia) Commercial'),
    ('ACLEDA', 'CHIPMONG', 'chip mong', 'Chip Mong Commercial Bank plc'),
    ('ACLEDA', 'COOLCASH', 'cool cash', 'Cool Cash Plc'),
    ('ACLEDA', 'DGB', 'dgb', 'DGB Bank'),
    ('ACLEDA', 'DARASAKOR', 'dara sakor', 'Dara Sakor Pay PLC'),
    ('ACLEDA', 'FCB', 'first commercial', 'First Commercial Bank'),
    ('ACLEDA', 'FTB', 'foreign trade', 'Foreign Trade Bank of Cambodia'),
    ('ACLEDA', 'HATTHA', 'hattha', 'Hattha Bank Plc'),
    ('ACLEDA', 'HENGFENG', 'heng feng', 'Heng Feng (Cambodia) Bank'),
    ('ACLEDA', 'HLB', 'hong leong', 'Hong Leong Bank (Cambodia)'),
    ('ACLEDA', 'IBANK', 'ibank', 'IBANK (CAMBODIA) PLC.'),
    ('ACLEDA', 'ICBC', 'icbc', 'ICBC'),
    ('ACLEDA', 'JTRUST', 'j trust', 'J Trust Royal Bank Plc.'),
    ('ACLEDA', 'KBPRASAC', 'kb prasac', 'KB PRASAC Bank Plc'),
    ('ACLEDA', 'KESS', 'kess', 'Kess Innovation Plc.'),
    ('ACLEDA', 'LOLC', 'lolc', 'LOLC (Cambodia) Plc.'),
    ('ACLEDA', 'LYHOUR', 'lyhour veluy', 'LYHOUR VELUY'),
    ('ACLEDA', 'LANTON', 'lanton', 'Lanton Pay'),
    ('ACLEDA', 'MBBANK', 'mb bank', 'MB BANK (CAMBODIA) PLC'),
    ('ACLEDA', 'MOHANOKOR', 'mohanokor', 'MOHANOKOR MFI Plc'),
    ('ACLEDA', 'MAYBANK', 'maybank', 'Maybank Cambodia Plc'),
    ('ACLEDA', 'ORIENTAL', 'oriental', 'Oriental Bank'),
    ('ACLEDA', 'PEAK', 'peak', 'PEAK WEALTH BANK PLC'),
    ('ACLEDA', 'PHILLIP', 'phillip', 'Phillip Bank Plc'),
    ('ACLEDA', 'PPCB', 'phnom penh', 'Phnom Penh Commercial Bank'),
    ('ACLEDA', 'PIPAY', 'pi pay', 'Pi Pay Plc.'),
    ('ACLEDA', 'RHB', 'rhb', 'RHB BANK(CAMBODIA) Plc.'),
    ('ACLEDA', 'SBI', 'sbi ly hour', 'SBI LY HOUR Bank Plc.'),
    ('ACLEDA', 'SACOMBANK', 'sacombank', 'Sacombank Cambodia'),
    ('ACLEDA', 'SATHAPANA', 'sathapana', 'Sathapana Bank Plc'),
    ('ACLEDA', 'SHINHAN', 'shinhan', 'Shinhan Bank Cambodia Plc'),
    ('ACLEDA', 'UPAY', 'u-pay', 'U-Pay Digital Plc'),
    ('ACLEDA', 'UCB', 'union commercial', 'Union Commercial Bank Plc'),
    ('ACLEDA', 'VATTANAC', 'vattanac', 'Vattanac Bank'),
    ('ACLEDA', 'WING', 'wing', 'WING BANK'),
    ('ACLEDA', 'WOORI', 'woori', 'Woori Bank (Cambodia) Plc.'),
]

sql = """INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name)
         VALUES (%s, %s, %s, %s)
         ON DUPLICATE KEY UPDATE search_text=VALUES(search_text), display_name=VALUES(display_name)"""

count = 0
for m in mappings:
    cur.execute(sql, m)
    count += 1

conn.commit()
print(f"Inserted/updated {count} ACLEDA bank_name_mappings")

cur.execute("SELECT COUNT(*) FROM bank_name_mappings WHERE from_bank_code='ACLEDA'")
print(f"Total ACLEDA mappings: {cur.fetchone()[0]}")

cur.close(); conn.close()
