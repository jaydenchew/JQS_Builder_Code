-- ============================================================
-- Bank name mappings seed — CIMB interbank transfers
-- 58 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_CIMB.sql
--
-- Idempotent: deletes existing CIMB rows then reinserts.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'CIMB';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('CIMB','AEONBANK','Aeon bank','AEON BANK (M) BERHAD'),
('CIMB','AFFIN','Affin','AFFIN BANK BHD'),
('CIMB','AGRO','Agrobank','AGROBANK'),
('CIMB','ABMB','Alliance','ALLIANCE BANK MALAYSIA BHD'),
('CIMB','ALRAJHI','Al rajhi','AL RAJHI BANKING & INVESTMENT'),
('CIMB','AMMB','Ambank','AMBANK BERHAD'),
('CIMB','AXIATA','Axiata','Axiata Digital eCode Sdn Bhd'),
('CIMB','BANGKOK','Bangkok bank','BANGKOK BANK BHD'),
('CIMB','BIMB','Bank islam','BANK ISLAM MALAYSIA BHD'),
('CIMB','BKRM','Bank rakyat','BANK KERJASAMA RAKYAT MALAYSIA BHD'),
('CIMB','BMMB','Bank muamalat','BANK MUALAMAT MALAYSIA BHD'),
('CIMB','BOFA','Bank of america','BANK OF AMERICA MALAYSIA BHD'),
('CIMB','BOC','Bank of china malaysia','Bank of China (Malaysia) Berhad'),
('CIMB','BSN','Bsn','BANK SIMPANAN NASIONAL'),
('CIMB','BEEZ','Beez','Beez Fintech Sdn Bhd'),
('CIMB','BIGPAY','Bigpay','BigPay Malaysia Sdn Bhd'),
('CIMB','BNPPARIBAS','Bnp paribas','BNP PARIBAS MALAYSIA BERHAD'),
('CIMB','BOOSTBANK','Boost bank','Boost Bank Berhad'),
('CIMB','CCBM','China construction bank','CHINA CONSTUCTION BANK (MALAYSIA) BERHAD'),
('CIMB','CITI','Citibank','CITIBANK BHD'),
('CIMB','CURLEC','Curlec','Curlec Sdn Bhd'),
('CIMB','DEUTSCHE','Deutsche bank','DEUTSCHE BANK MALAYSIA BERHAD'),
('CIMB','FASSPAY','Fass payment','Fass Payment Solutions Sdn Bhd'),
('CIMB','FAVE','Fave','Fave Asia Technologies Sdn Bhd'),
('CIMB','FINEXUS','Finexus','Finexus Cards Sdn. Bhd.'),
('CIMB','GHL','Ghl','GHL Cardpay Sdn Bhd'),
('CIMB','GPAY','Gpay','GPay Network (M) Sdn Bhd'),
('CIMB','GX','Gxbank','GX Bank Berhad'),
('CIMB','HLB','Hong leong','HONG LEONG BANK BHD'),
('CIMB','HSBC','Hsbc','HSBC Bank Malaysia Berhad'),
('CIMB','ICBC','Icbc','INDUSTRIAL & COMMERCIAL BANK OF CHINA'),
('CIMB','IPAY88','Ipay88','iPay88 (M) Sdn Bhd'),
('CIMB','JCPACIFIC','J&c pacific','J & C Pacific Sdn Bhd'),
('CIMB','JPMORGAN','Jp morgan','JP MORGAN CHASE BANK BHD'),
('CIMB','KAF','Kaf digital','KAF Digital Bank Berhad'),
('CIMB','KFH','Kuwait finance','KUWAIT FINANCE HOUSE MALAYSIA BHD'),
('CIMB','MBB','Maybank','MALAYAN BANKING BHD'),
('CIMB','MBSB','Mbsb','MBSB Bank Berhad'),
('CIMB','MERCHANTRADE','Merchantrade','Merchantrade Asia Sdn Bhd'),
('CIMB','MIZUHO','Mizuho','MIZUHO BANK (M) BHD'),
('CIMB','MOBILITYONE','Mobilityone','MobilityOne Sdn Bhd'),
('CIMB','MUFG','Mufg','MUFG BANK (MALAYSIA) BERHAD'),
('CIMB','OCBC','Ocbc','OCBC BANK MALAYSIA BHD'),
('CIMB','PAYEX','Payex','Payex PLT'),
('CIMB','PBE','Public bank','PUBLIC BANK BHD'),
('CIMB','RAZERPAY','Razer merchant','Razer Merchant Services Sdn Bhd'),
('CIMB','RHB','Rhb','RHB BANK BHD'),
('CIMB','RYTBANK','Ryt bank','YTL Digital Bank Berhad (Ryt Bank)'),
('CIMB','SETEL','Setel','Setel Pay Sdn Bhd'),
('CIMB','SHOPEPAY','Shopee pay','Shopee'),
('CIMB','SILICONNET','Siliconnet','SiliconNet Technologies Sdn Bhd'),
('CIMB','SCB','Standard chartered','STANDARD CHARTERED BANK BHD'),
('CIMB','SMBC','Sumitomo mitsui','SUMITOMO MITSUI BANK BERHAD'),
('CIMB','TNG','Touch n go','Touch N Go Digital'),
('CIMB','UNIPIN','Unipin','Unipin (M) Sdn Bhd'),
('CIMB','UOB','Uob','UNITED OVERSEAS BANK BHD'),
('CIMB','WANNAPAY','Wannapay','Wannapay Sdn Bhd'),
('CIMB','WISE','Wise','Wise Payments Malaysia Sdn Bhd');

SELECT CONCAT('Inserted ', COUNT(*), ' CIMB bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'CIMB';
