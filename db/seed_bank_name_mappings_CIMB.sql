-- ============================================================
-- Bank name mappings seed — CIMB interbank transfers
-- 21 destination banks
--
-- Import:
--   docker exec -i wa-unified-mysql mysql -uroot -pwa_unified_2026 wa_db < db/seed_bank_name_mappings_CIMB.sql
--
-- Idempotent: deletes existing CIMB rows then reinserts.
-- ============================================================

DELETE FROM bank_name_mappings WHERE from_bank_code = 'CIMB';

INSERT INTO bank_name_mappings (from_bank_code, to_bank_code, search_text, display_name) VALUES
('CIMB','ABMB','alliance','Alliance Bank Malaysia Berhad'),
('CIMB','AFFIN','affin','Affin Bank Berhad'),
('CIMB','AGRO','agrobank','Bank Pertanian Malaysia Berhad'),
('CIMB','AMMB','ambank','AmBank (M) Berhad'),
('CIMB','BIMB','islam','Bank Islam Malaysia Berhad'),
('CIMB','BKRM','kerjasama','Bank Kerjasama Rakyat Malaysia Berhad'),
('CIMB','BMMB','mualamat','Bank Muamalat Malaysia Berhad'),
('CIMB','BOC','bank of china','Bank of China'),
('CIMB','BSN','simpanan','Bank Simpanan Nasional'),
('CIMB','CITI','citibank','Citibank Berhad'),
('CIMB','GX','gx bank','GX Bank'),
('CIMB','HLB','hong leong','Hong Leong Bank Berhad'),
('CIMB','HSBC','hsbc','Hongkong Bank Malaysia Berhad'),
('CIMB','MBB','malayan','Malayan Banking Berhad / Maybank'),
('CIMB','OCBC','ocbc','Overseas Chinese Banking Corporation / OCBC'),
('CIMB','PBE','public','Public Bank Berhad'),
('CIMB','RHB','rhb','RHB Bank'),
('CIMB','RYTB','ryt','RYT Bank'),
('CIMB','SCB','chartered','Standard Chartered Bank Malaysia Berhad'),
('CIMB','TNG','touch','Touch N Go'),
('CIMB','UOB','united','United Overseas Bank Limited');

SELECT CONCAT('Inserted ', COUNT(*), ' CIMB bank name mappings') AS done
FROM bank_name_mappings WHERE from_bank_code = 'CIMB';
