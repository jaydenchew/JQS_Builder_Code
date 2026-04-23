-- ============================================================
-- Bank name mappings seed — MBB (Maybank) interbank transfers
-- 45 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_MBB.sql
--
-- Idempotent: deletes existing MBB rows then reinserts.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'MBB';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('MBB','AEONBANK','Aeon bank','AEON BANK (M) BERHAD'),
('MBB','AFFIN','Affin','AFFIN BANK BERHAD'),
('MBB','ALRAJHI','Al rajhi','AL RAJHI BANKING & INVESTMENT CORP (M) BERHAD'),
('MBB','ABMB','Alliance','ALLIANCE BANK MALAYSIA BERHAD'),
('MBB','AMMB','Ambank','AmBANK BERHAD'),
('MBB','BIMB','Bank islam','BANK ISLAM MALAYSIA'),
('MBB','BKRM','Kerjasama','BANK KERJASAMA RAKYAT MALAYSIA BERHAD'),
('MBB','BMMB','Mualamat','BANK MUALAMAT'),
('MBB','BOFA','America','BANK OF AMERICA'),
('MBB','BOC','Of china','BANK OF CHINA (MALAYSIA) BERHAD'),
('MBB','AGRO','Agrobank','BANK PERTANIAN MALAYSIA BERHAD (AGROBANK)'),
('MBB','BSN','Simpanan','BANK SIMPANAN NASIONAL BERHAD'),
('MBB','BNPPARIBAS','Bnp paribas','BNP PARIBAS MALAYSIA'),
('MBB','BANGKOK','Bangkok','Bangkok Bank Berhad'),
('MBB','BIGPAY','Bigpay','BigPay Malaysia Sdn Bhd'),
('MBB','BOOSTBANK','Boost bank','Boost Bank Berhad'),
('MBB','BOOSTEWALLET','Boost ewallet','Boost eWallet'),
('MBB','CCBM','China const','CHINA CONST BK (M) BERHAD'),
('MBB','CIMB','Cimb','CIMB BANK BERHAD'),
('MBB','CITI','Citibank','CITIBANK BERHAD'),
('MBB','COOPBANK','Opbank','Co-opbank Pertama'),
('MBB','DEUTSCHE','Deutsche','DEUTSCHE BANK (MSIA) BERHAD'),
('MBB','FASSPAY','Fasspay','FASSPAY'),
('MBB','FINEXUS','Finexus','FINEXUS CARDS SDN. BHD.'),
('MBB','GX','Gxbank','GXBANK'),
('MBB','HLB','Hong leong','HONG LEONG BANK'),
('MBB','HSBC','Hsbc','HSBC BANK MALAYSIA BERHAD'),
('MBB','ICBC','Industrial','INDUSTRIAL & COMMERCIAL BANK OF CHINA'),
('MBB','JPMORGAN','Morgan chase','J.P. MORGAN CHASE BANK BERHAD'),
('MBB','KAF','Kaf','KAF Digital Bank'),
('MBB','KFH','Kuwait','KUWAIT FINANCE HOUSE (MALAYSIA) BHD'),
('MBB','MBSB','Mbsb','MBSB BANK'),
('MBB','MIZUHO','Mizuho','MIZUHO BANK (MALAYSIA) BERHAD'),
('MBB','MUFG','Mufg','MUFG BANK (MALAYSIA) BHD'),
('MBB','MERCHANTRADE','Merchantrade','Merchantrade'),
('MBB','OCBC','Ocbc','OCBC BANK (MALAYSIA) BHD'),
('MBB','PBE','Public bank','PUBLIC BANK'),
('MBB','RHB','Rhb','RHB BANK'),
('MBB','RYTBANK','Ryt','Ryt Bank'),
('MBB','SETEL','Setel','SETEL'),
('MBB','SCB','Standard chartered','STANDARD CHARTERED BANK'),
('MBB','SMBC','Sumitomo','SUMITOMO MITSUI BANKING CORPORATION MALAYSIA BHD'),
('MBB','SHOPEPAY','Shopeepay','ShopeePay'),
('MBB','TNG','Touch n go','TOUCH N GO eWALLET'),
('MBB','UOB','United overseas','UNITED OVERSEAS BANK BERHAD');

SELECT CONCAT('Inserted ', COUNT(*), ' MBB bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'MBB';
