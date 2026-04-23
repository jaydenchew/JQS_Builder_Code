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
('CIMB','BANGKOK','Bangkok','BANGKOK BANK BHD'),
('CIMB','BIMB','Bank islam','BANK ISLAM MALAYSIA BHD'),
('CIMB','BKRM','Kerjasama','BANK KERJASAMA RAKYAT MALAYSIA BHD'),
('CIMB','BMMB','Mualamat','BANK MUALAMAT MALAYSIA BHD'),
('CIMB','BOFA','America','BANK OF AMERICA MALAYSIA BHD'),
('CIMB','BOC','Of china','Bank of China (Malaysia) Berhad'),
('CIMB','BSN','Simpanan','BANK SIMPANAN NASIONAL'),
('CIMB','BEEZ','Beez','Beez Fintech Sdn Bhd'),
('CIMB','BIGPAY','Bigpay','BigPay Malaysia Sdn Bhd'),
('CIMB','BNPPARIBAS','Bnp paribas','BNP PARIBAS MALAYSIA BERHAD'),
('CIMB','BOOSTBANK','Boost bank','Boost Bank Berhad'),
('CIMB','CCBM','China construction','CHINA CONSTRUCTION BANK (MALAYSIA) BERHAD'),
('CIMB','CITI','Citibank','CITIBANK BHD'),
('CIMB','CURLEC','Curlec','Curlec Sdn Bhd'),
('CIMB','DEUTSCHE','Deutsche','DEUTSCHE BANK MALAYSIA BERHAD'),
('CIMB','FASSPAY','Fass payment','Fass Payment Solutions Sdn Bhd'),
('CIMB','FAVE','Fave','Fave Asia Technologies Sdn Bhd'),
('CIMB','FINEXUS','Finexus','Finexus Cards Sdn. Bhd.'),
('CIMB','GHL','Ghl','GHL Cardpay Sdn Bhd'),
('CIMB','GPAY','Gpay','GPay Network (M) Sdn Bhd'),
('CIMB','GX','Gx bank','GX Bank Berhad'),
('CIMB','HLB','Hong leong','HONG LEONG BANK BHD'),
('CIMB','HSBC','Hsbc','HSBC Bank Malaysia Berhad'),
('CIMB','ICBC','Industrial','INDUSTRIAL & COMMERCIAL BANK OF CHINA'),
('CIMB','IPAY88','Ipay88','iPay88 (M) Sdn Bhd'),
('CIMB','JCPACIFIC','Pacific','J & C Pacific Sdn Bhd'),
('CIMB','JPMORGAN','Jp morgan','JP MORGAN CHASE BANK BHD'),
('CIMB','KAF','Kaf','KAF Digital Bank Berhad'),
('CIMB','KFH','Kuwait','KUWAIT FINANCE HOUSE MALAYSIA BHD'),
('CIMB','MBB','Malayan','MALAYAN BANKING BHD'),
('CIMB','MBSB','Mbsb','MBSB Bank Berhad'),
('CIMB','MERCHANTRADE','Merchantrade','Merchantrade Asia Sdn Bhd'),
('CIMB','MIZUHO','Mizuho','MIZUHO BANK (M) BHD'),
('CIMB','MOBILITYONE','Mobilityone','MobilityOne Sdn Bhd'),
('CIMB','MUFG','Mufg','MUFG BANK (MALAYSIA) BERHAD'),
('CIMB','OCBC','Ocbc','OCBC BANK MALAYSIA BHD'),
('CIMB','PAYEX','Payex','Payex PLT'),
('CIMB','PBE','Public bank','PUBLIC BANK BHD'),
('CIMB','RAZERPAY','Razer','Razer Merchant Services Sdn Bhd'),
('CIMB','RHB','Rhb','RHB BANK BHD'),
('CIMB','RYTBANK','Ryt','YTL Digital Bank Berhad (Ryt Bank)'),
('CIMB','SETEL','Setel','Setel Pay Sdn Bhd'),
('CIMB','SHOPEPAY','Shopee','Shopee'),
('CIMB','SILICONNET','Siliconnet','SiliconNet Technologies Sdn Bhd'),
('CIMB','SCB','Standard chartered','STANDARD CHARTERED BANK BHD'),
('CIMB','SMBC','Sumitomo','SUMITOMO MITSUI BANK BERHAD'),
('CIMB','TNG','Touch n go','Touch N Go Digital'),
('CIMB','UNIPIN','Unipin','Unipin (M) Sdn Bhd'),
('CIMB','UOB','United overseas','UNITED OVERSEAS BANK BHD'),
('CIMB','WANNAPAY','Wannapay','Wannapay Sdn Bhd'),
('CIMB','WISE','Wise','Wise Payments Malaysia Sdn Bhd');

SELECT CONCAT('Inserted ', COUNT(*), ' CIMB bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'CIMB';
