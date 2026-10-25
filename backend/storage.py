import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def connect():
    path = Path(os.getenv("AUTHENTRA_DB", str(ROOT / ".local/authentra.db")))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()

def password_matches(password, encoded):
    salt, digest = encoded.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, digest)

def initialize():
    with connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('verifier','institution','owner')),
          wallet TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS registrations (
          reference TEXT PRIMARY KEY, issuer_id INTEGER REFERENCES users(id), file_hash TEXT NOT NULL,
          transaction_hash TEXT NOT NULL, gas_used INTEGER, fee_wei TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS verifications (
          id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), reference TEXT, status TEXT NOT NULL,
          file_hash TEXT, duration_ms REAL, ai_status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
          reference TEXT, transaction_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        ''')

        # Idempotent upgrade of existing installations; legacy issuers retain
        # application eligibility, with on-chain approval still mandatory.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for name, definition in {
            "approval_status": "TEXT NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK(approval_status IN ('PENDING_APPROVAL','APPROVED','REJECTED','SUSPENDED','REVOKED'))",
            "institution_reference": "TEXT",
            "verification_info": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                if name == "approval_status":
                    conn.execute("UPDATE users SET approval_status='APPROVED'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_wallet_unique ON users(lower(wallet)) WHERE wallet IS NOT NULL")


def seed_demo(registry):
    # This explicit development mode is never enabled implicitly in production.
    issuers = [a for a in registry.keys if a != registry.owner]
    accounts = [
        ("verifier@authentra.demo", "Alex Morgan", "verifier", None),
        ("issuer@authentra.demo", "Meridian Institute of Technology", "institution", issuers[0]),
        ("pending@authentra.demo", "Northstar Training Academy", "institution", issuers[1]),
        ("owner@authentra.demo", "Platform Administrator", "owner", registry.owner),
    ]
    with connect() as conn:
        for email, name, role, wallet in accounts:
            conn.execute("INSERT OR IGNORE INTO users(email,name,password,role,wallet,approval_status) VALUES(?,?,?,?,?,?)", (email, name, password_hash("AuthenTra-demo-2026!"), role, wallet, "PENDING_APPROVAL" if email.startswith("pending@") else "APPROVED"))

def audit(conn, user_id, action, reference=None, transaction_hash=None):
    conn.execute("INSERT INTO audit(user_id,action,reference,transaction_hash) VALUES(?,?,?,?)", (user_id, action, reference, transaction_hash))
