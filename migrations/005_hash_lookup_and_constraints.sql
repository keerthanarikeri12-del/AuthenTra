-- AuthenTra Database Migration 005: Canonical File Hash Lookup, Linkage & Constraints
-- Ensures exact byte-matching hash lookups are indexed and uniquely mapped

-- 1. Create indexes for fast lookup and deduplication
CREATE INDEX IF NOT EXISTS registrations_file_hash_idx ON registrations(file_hash);
CREATE INDEX IF NOT EXISTS registrations_lower_file_hash_idx ON registrations(lower(file_hash));
CREATE INDEX IF NOT EXISTS registrations_ref_idx ON registrations(reference);

-- 2. Ensure verifications table stores the canonical file_hash and registered_hash
CREATE INDEX IF NOT EXISTS verifications_file_hash_idx ON verifications(file_hash);
CREATE INDEX IF NOT EXISTS verifications_registered_hash_idx ON verifications(registered_hash);

-- 3. Document canonical contract and chain constraints
COMMENT ON TABLE registrations IS 'Canonical certificate metadata linked to immutable on-chain smart contract records';
