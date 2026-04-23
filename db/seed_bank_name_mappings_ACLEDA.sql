-- ============================================================
-- Bank name mappings seed — ACLEDA interbank transfers
-- 58 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_ACLEDA.sql
--
-- Idempotent: deletes existing ACLEDA rows then reinserts.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'ACLEDA';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('ACLEDA','ABA','aba','ABA Bank'),
('ACLEDA','AEON','aeon','Aeon Specialized Bank'),
('ACLEDA','ALPHA','alpha','Alpha Commercial Bank PLC'),
('ACLEDA','AMK','amk','AMK Microfinance Plc.'),
('ACLEDA','AMRET','amret','Amret Plc.'),
('ACLEDA','APD','apd','APD Bank'),
('ACLEDA','ARDB','ardb','ARDB Bank'),
('ACLEDA','ASIAWEI','asia wei luy','Asia Wei Luy'),
('ACLEDA','BIDC','bidc','BIDC Bank'),
('ACLEDA','BOCHK','bank of china','Bank of China (Hong Kong)'),
('ACLEDA','BONGLOY','bongloy','BongLoy'),
('ACLEDA','BOOYOUNG','booyoung','Booyoung Khmer Bank'),
('ACLEDA','BRED','bred','BRED Bank (Cambodia) Plc'),
('ACLEDA','BRIDGE','bridge','BRIDGE Bank'),
('ACLEDA','CAB','cambodia asia','Cambodia Asia Bank'),
('ACLEDA','CAMPU','cambodian public','Cambodian Public Bank Plc'),
('ACLEDA','CANADIA','canadia','Canadia Bank Plc'),
('ACLEDA','CATHAY','cathay','CATHAY UNITED BANK'),
('ACLEDA','CCU','ccu','CCU Commercial Bank PLC.'),
('ACLEDA','CHIEF','chief','Chief (Cambodia) Commercial'),
('ACLEDA','CHIPMONG','chip mong','Chip Mong Commercial Bank plc'),
('ACLEDA','CIMB','cimb','CIMB'),
('ACLEDA','COOLCASH','cool cash','Cool Cash Plc'),
('ACLEDA','CPB','cambodia post','Cambodia Post Bank Plc'),
('ACLEDA','DARASAKOR','dara sakor','Dara Sakor Pay PLC'),
('ACLEDA','DGB','dgb','DGB Bank'),
('ACLEDA','EMONEY','emoney','EMoney'),
('ACLEDA','FCB','first commercial','First Commercial Bank'),
('ACLEDA','FTB','foreign trade','Foreign Trade Bank of Cambodia'),
('ACLEDA','HATTHA','hattha','Hattha Bank Plc'),
('ACLEDA','HENGFENG','heng feng','Heng Feng (Cambodia) Bank'),
('ACLEDA','HLB','hong leong','Hong Leong Bank (Cambodia)'),
('ACLEDA','IBANK','ibank','IBANK (CAMBODIA) PLC.'),
('ACLEDA','ICBC','icbc','ICBC'),
('ACLEDA','JTRUST','j trust','J Trust Royal Bank Plc.'),
('ACLEDA','KBPRASAC','kb prasac','KB PRASAC Bank Plc'),
('ACLEDA','KESS','kess','Kess Innovation Plc.'),
('ACLEDA','LANTON','lanton','Lanton Pay'),
('ACLEDA','LOLC','lolc','LOLC (Cambodia) Plc.'),
('ACLEDA','LYHOUR','lyhour veluy','LYHOUR VELUY'),
('ACLEDA','MAYBANK','maybank','Maybank Cambodia Plc'),
('ACLEDA','MBBANK','mb bank','MB BANK (CAMBODIA) PLC'),
('ACLEDA','MOHANOKOR','mohanokor','MOHANOKOR MFI Plc'),
('ACLEDA','ORIENTAL','oriental','Oriental Bank'),
('ACLEDA','PEAK','peak','PEAK WEALTH BANK PLC'),
('ACLEDA','PHILLIP','phillip','Phillip Bank Plc'),
('ACLEDA','PIPAY','pi pay','Pi Pay Plc.'),
('ACLEDA','PPCB','phnom penh','Phnom Penh Commercial Bank'),
('ACLEDA','RHB','rhb','RHB BANK(CAMBODIA) Plc.'),
('ACLEDA','SACOMBANK','sacombank','Sacombank Cambodia'),
('ACLEDA','SATHAPANA','sathapana','Sathapana Bank Plc'),
('ACLEDA','SBI','sbi ly hour','SBI LY HOUR Bank Plc.'),
('ACLEDA','SHINHAN','shinhan','Shinhan Bank Cambodia Plc'),
('ACLEDA','TRUEMONEY','truemoney','TrueMoney Cambodia'),
('ACLEDA','UCB','union commercial','Union Commercial Bank Plc'),
('ACLEDA','UPAY','u-pay','U-Pay Digital Plc'),
('ACLEDA','VATTANAC','vattanac','Vattanac Bank'),
('ACLEDA','WINGBANK','wing','WING BANK'),
('ACLEDA','WOORI','woori','Woori Bank (Cambodia) Plc.');

SELECT CONCAT('Inserted ', COUNT(*), ' ACLEDA bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'ACLEDA';
