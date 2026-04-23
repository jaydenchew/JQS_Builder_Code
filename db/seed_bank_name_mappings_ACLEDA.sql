-- ============================================================
-- Bank name mappings seed — ACLEDA interbank transfers
-- 59 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_ACLEDA.sql
--
-- Idempotent: deletes existing ACLEDA rows then reinserts.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'ACLEDA';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('ACLEDA','ABA','Aba','ABA Bank'),
('ACLEDA','AEON','Aeon','Aeon Specialized Bank'),
('ACLEDA','ALPHA','Alpha','Alpha Commercial Bank PLC'),
('ACLEDA','AMK','Amk','AMK Microfinance Plc.'),
('ACLEDA','AMRET','Amret','Amret Plc.'),
('ACLEDA','APD','Apd','APD Bank'),
('ACLEDA','ARDB','Ardb','ARDB Bank'),
('ACLEDA','ASIAWEI','Asia wei luy','Asia Wei Luy'),
('ACLEDA','BOCHK','Bank of china','Bank of China (Hong Kong)'),
('ACLEDA','BIDC','Bidc','BIDC Bank'),
('ACLEDA','BONGLOY','Bongloy','BongLoy'),
('ACLEDA','BOOYOUNG','Booyoung','Booyoung Khmer Bank'),
('ACLEDA','BRED','Bred','BRED Bank (Cambodia) Plc'),
('ACLEDA','BRIDGE','Bridge','BRIDGE Bank'),
('ACLEDA','CAB','Cambodia asia','Cambodia Asia Bank'),
('ACLEDA','CPB','Cambodia post','Cambodia Post Bank Plc'),
('ACLEDA','CAMPU','Cambodian public','Cambodian Public Bank Plc'),
('ACLEDA','CANADIA','Canadia','Canadia Bank Plc'),
('ACLEDA','CATHAY','Cathay','CATHAY UNITED BANK'),
('ACLEDA','CCU','Ccu','CCU Commercial Bank PLC.'),
('ACLEDA','CHIEF','Chief','Chief (Cambodia) Commercial'),
('ACLEDA','CHIPMONG','Chip mong','Chip Mong Commercial Bank plc'),
('ACLEDA','CIMB','Cimb','CIMB'),
('ACLEDA','COOLCASH','Cool cash','Cool Cash Plc'),
('ACLEDA','DARASAKOR','Dara sakor','Dara Sakor Pay PLC'),
('ACLEDA','DGB','Dgb','DGB Bank'),
('ACLEDA','EMONEY','Emoney','EMoney'),
('ACLEDA','FCB','First commercial','First Commercial Bank'),
('ACLEDA','FTB','Foreign trade','Foreign Trade Bank of Cambodia'),
('ACLEDA','HATTHA','Hattha','Hattha Bank Plc'),
('ACLEDA','HENGFENG','Heng feng','Heng Feng (Cambodia) Bank'),
('ACLEDA','HLB','Hong leong','Hong Leong Bank (Cambodia)'),
('ACLEDA','IBANK','Ibank','IBANK (CAMBODIA) PLC.'),
('ACLEDA','ICBC','Icbc','ICBC'),
('ACLEDA','JTRUST','J trust','J Trust Royal Bank Plc.'),
('ACLEDA','KBPRASAC','Kb prasac','KB PRASAC Bank Plc'),
('ACLEDA','KESS','Kess','Kess Innovation Plc.'),
('ACLEDA','LANTON','Lanton','Lanton Pay'),
('ACLEDA','LOLC','Lolc','LOLC (Cambodia) Plc.'),
('ACLEDA','LYHOUR','Lyhour veluy','LYHOUR VELUY'),
('ACLEDA','MAYBANK','Maybank','Maybank Cambodia Plc'),
('ACLEDA','MBBANK','Mb bank','MB BANK (CAMBODIA) PLC'),
('ACLEDA','MOHANOKOR','Mohanokor','MOHANOKOR MFI Plc'),
('ACLEDA','ORIENTAL','Oriental','Oriental Bank'),
('ACLEDA','PEAK','Peak','PEAK WEALTH BANK PLC'),
('ACLEDA','PHILLIP','Phillip','Phillip Bank Plc'),
('ACLEDA','PPCB','Phnom penh','Phnom Penh Commercial Bank'),
('ACLEDA','PIPAY','Pi pay','Pi Pay Plc.'),
('ACLEDA','RHB','Rhb','RHB BANK(CAMBODIA) Plc.'),
('ACLEDA','SACOMBANK','Sacombank','Sacombank Cambodia'),
('ACLEDA','SATHAPANA','Sathapana','Sathapana Bank Plc'),
('ACLEDA','SBI','Sbi ly hour','SBI LY HOUR Bank Plc.'),
('ACLEDA','SHINHAN','Shinhan','Shinhan Bank Cambodia Plc'),
('ACLEDA','TRUEMONEY','Truemoney','TrueMoney Cambodia'),
('ACLEDA','UPAY','Pay digital','U-Pay Digital Plc'),
('ACLEDA','UCB','Union commercial','Union Commercial Bank Plc'),
('ACLEDA','VATTANAC','Vattanac','Vattanac Bank'),
('ACLEDA','WINGBANK','Wing','WING BANK'),
('ACLEDA','WOORI','Woori','Woori Bank (Cambodia) Plc.');

SELECT CONCAT('Inserted ', COUNT(*), ' ACLEDA bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'ACLEDA';
