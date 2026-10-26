-- AuthenTra Database Migration 004: System Admin Governance & History Indexes
-- Supports Institution Access Management, User History, and Issuer Ledger

-- 1. Add review_notes column to users table if not already present
-- SQLite 3.35+ supports ALTER TABLE ADD COLUMN
-- Handled idempotently in Python backend/storage.py as well

-- 2. Indexes for fast user verification history filtering
CREATE INDEX IF NOT EXISTS verifications_user_idx ON verifications(user_id);
CREATE INDEX IF NOT EXISTS verifications_status_idx ON verifications(status);
CREATE INDEX IF NOT EXISTS verifications_category_idx ON verifications(category);
CREATE INDEX IF NOT EXISTS verifications_created_idx ON verifications(created_at);
CREATE INDEX IF NOT EXISTS verifications_ref_idx ON verifications(reference);

-- 3. Indexes for issuer history and registrations lookup
CREATE INDEX IF NOT EXISTS registrations_issuer_idx ON registrations(issuer_id);
CREATE INDEX IF NOT EXISTS registrations_created_idx ON registrations(created_at);

-- 4. Audit trail indexes for actor and target reference lookups
CREATE INDEX IF NOT EXISTS audit_user_ref_idx ON audit(user_id, reference);
