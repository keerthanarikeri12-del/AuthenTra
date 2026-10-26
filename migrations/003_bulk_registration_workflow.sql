-- AuthenTra Database Migration 003: Institutional Bulk Certificate Registration Workflow
-- Durable batch jobs, per-item statuses, extracted metadata, and blockchain receipts

-- 1. Ensure registrations table has all columns for blockchain verification & metadata
CREATE TABLE IF NOT EXISTS registrations (
  reference TEXT PRIMARY KEY,
  issuer_id INTEGER REFERENCES users(id),
  file_hash TEXT NOT NULL,
  transaction_hash TEXT NOT NULL,
  gas_used INTEGER,
  fee_wei TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL DEFAULT 'REGISTERED_ON_BLOCKCHAIN',
  network TEXT DEFAULT '1337',
  contract_address TEXT,
  block_number INTEGER,
  registered_at TEXT,
  metadata TEXT,
  requires_review INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS registrations_issuer_idx ON registrations(issuer_id);
CREATE INDEX IF NOT EXISTS registrations_hash_idx ON registrations(file_hash);
CREATE INDEX IF NOT EXISTS registrations_issuer_hash_idx ON registrations(issuer_id, file_hash);
CREATE INDEX IF NOT EXISTS registrations_status_idx ON registrations(status);

-- 2. Upload jobs table for asynchronous batch processing
CREATE TABLE IF NOT EXISTS upload_jobs (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  mode TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS upload_jobs_owner ON upload_jobs(user_id, mode, created_at);
CREATE INDEX IF NOT EXISTS upload_jobs_state ON upload_jobs(state);

-- 3. Upload items table for individual certificate tracking
-- Statuses: QUEUED, VALIDATING, OCR_PROCESSING, AWAITING_REVIEW,
--           PENDING_BLOCKCHAIN, REGISTERED_ON_BLOCKCHAIN, REGISTRATION_FAILED, REGISTRATION_STATUS_UNCERTAIN
CREATE TABLE IF NOT EXISTS upload_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES upload_jobs(id),
  filename TEXT NOT NULL,
  reference TEXT NOT NULL,
  kind TEXT,
  state TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  ocr_confidence REAL,
  metadata TEXT,
  data BLOB,
  result TEXT
);

CREATE INDEX IF NOT EXISTS upload_items_job ON upload_items(job_id);
CREATE INDEX IF NOT EXISTS upload_items_state ON upload_items(state, id);
CREATE INDEX IF NOT EXISTS upload_items_status ON upload_items(status);
