-- AuthenTra Database Migration 001: Three Roles & Enhanced Audit
-- Roles: USER, INSTITUTION_ADMIN, SYSTEM_ADMIN
-- Backward-compatibility aliases: verifier -> USER, institution -> INSTITUTION_ADMIN, owner -> SYSTEM_ADMIN

-- 1. Upgrade users table to support the three explicit roles
CREATE TABLE IF NOT EXISTS users_v2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  password TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('USER', 'INSTITUTION_ADMIN', 'SYSTEM_ADMIN', 'verifier', 'institution', 'owner')),
  wallet TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  approval_status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK(approval_status IN ('PENDING_APPROVAL','APPROVED','REJECTED','SUSPENDED','REVOKED')),
  institution_reference TEXT,
  verification_info TEXT,
  oauth_provider TEXT,
  oauth_id TEXT,
  email_verified INTEGER NOT NULL DEFAULT 0,
  institution_domain TEXT
);

-- Copy and normalize existing records if migrating from users table
INSERT OR IGNORE INTO users_v2(id, email, name, password, role, wallet, created_at, approval_status, institution_reference, verification_info, oauth_provider, oauth_id, email_verified, institution_domain)
SELECT id, email, name, password,
  CASE
    WHEN role = 'verifier' THEN 'USER'
    WHEN role = 'institution' THEN 'INSTITUTION_ADMIN'
    WHEN role = 'owner' THEN 'SYSTEM_ADMIN'
    ELSE role
  END,
  wallet, created_at,
  COALESCE(approval_status, 'APPROVED'),
  institution_reference, verification_info, oauth_provider, oauth_id,
  COALESCE(email_verified, 1), institution_domain
FROM users;

-- 2. Audit Trail Table with actor metadata and details
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  reference TEXT,
  transaction_hash TEXT,
  details TEXT,
  ip_address TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS audit_user_idx ON audit(user_id);
CREATE INDEX IF NOT EXISTS audit_action_idx ON audit(action);
CREATE INDEX IF NOT EXISTS audit_created_idx ON audit(created_at);
