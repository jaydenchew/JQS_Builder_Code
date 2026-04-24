-- ============================================================
-- Bank name mappings seed — RHB interbank transfers
-- 47 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_RHB.sql
--
-- Idempotent: deletes existing RHB rows then reinserts.
-- Note: original data had COOPBANK listed twice; deduplicated to 47 rows.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'RHB';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('RHB','AEONBANK','Aeon bank','AEON BANK'),
('RHB','AFFIN','Affin','Affin Bank Berhad'),
('RHB','AGRO','Agro','AGRO Bank'),
('RHB','ALRAJHI','Rajhi','Al-Rajhi Bank'),
('RHB','ABMB','Alliance','Alliance Bank Malaysia Berhad'),
('RHB','AMMB','Ambank','AMBank'),
('RHB','BANGKOK','Bangkok','Bangkok Bank'),
('RHB','BIMB','Bank islam','Bank Islam Malaysia Berhad'),
('RHB','BKRM','Kerjasama','Bank Kerjasama Rakyat Malaysia'),
('RHB','BMMB','Mualamat','Bank Mualamat Malaysia Berhad'),
('RHB','BOFA','America','Bank of America (Malaysia) Bhd'),
('RHB','BOC','Of china','Bank of China (Malaysia) Bhd'),
('RHB','BSN','Simpanan','Bank Simpanan Malaysia'),
('RHB','BIGPAY','Bigpay','BigPay'),
('RHB','BNPPARIBAS','Bnp paribas','BNP Paribas Malaysia Berhad'),
('RHB','BOOSTBANK','Boost bank','Boost Bank'),
('RHB','BOOSTEWALLET','Boost ewallet','Boost eWallet'),
('RHB','CCBM','China construction','China Construction Bank (M) Bhd'),
('RHB','CIMB','Cimb','CIMB'),
('RHB','CITI','Citibank','Citibank Berhad'),
('RHB','COOPBANK','Opbank','Koperasi Co-opbank Pertama Malaysia Berhad'),
('RHB','DEUTSCHE','Deutsche','Deutsche Bank'),
('RHB','FASSPAY','Fass payment','Fass Payment Solutions Sdn Bhd'),
('RHB','FINEXUS','Finexus','Finexus Cards Sdn Bhd'),
('RHB','GX','Gxbank','GXBank'),
('RHB','HLB','Hong leong','Hong Leong Bank Berhad'),
('RHB','HSBC','Hsbc','HSBC Bank'),
('RHB','ICBC','Industrial','Industrial & Commercial Bank of China (ICBC)'),
('RHB','JPMORGAN','Morgan chase','J.P.Morgan Chase Bank Berhad'),
('RHB','KAF','Kaf','KAF Digital Bank'),
('RHB','KFH','Kuwait','Kuwait Finance House'),
('RHB','MBB','Maybank','Maybank'),
('RHB','MBSB','Mbsb','MBSB Bank Berhad'),
('RHB','MCASH','Mcash','MCash'),
('RHB','MERCHANTRADE','Merchantrade','Merchantrade'),
('RHB','MIZUHO','Mizuho','Mizuho Corporate Bank (M) Bhd'),
('RHB','MUFG','Mufg','MUFG Bank (Malaysia) Berhad'),
('RHB','OCBC','Ocbc','OCBC Bank Malaysia Berhad'),
('RHB','PBE','Public bank','Public Bank'),
('RHB','RYTBANK','Ryt','Ryt Bank'),
('RHB','SETEL','Setel','Setel Ventures Sdn Bhd'),
('RHB','SHOPEPAY','Shopeepay','ShopeePay'),
('RHB','SCB','Standard chartered','Standard Chartered Bank'),
('RHB','SMBC','Sumitomo','Sumitomo Mitsui Banking Corporation (M) Berhad'),
('RHB','TNG','Touch n go','Touch N Go Digital'),
('RHB','UOB','United overseas','United Overseas Bank Berhad'),
('RHB','WANPAY','Wanpay','WanPay');

SELECT CONCAT('Inserted ', COUNT(*), ' RHB bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'RHB';
