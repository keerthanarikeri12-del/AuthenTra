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
    conn.execute("PRAGMA secure_delete=ON")
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

ROLE_USER = "USER"
ROLE_INSTITUTION_ADMIN = "INSTITUTION_ADMIN"
ROLE_SYSTEM_ADMIN = "SYSTEM_ADMIN"

ROLE_MAP = {
    "verifier": "USER",
    "user": "USER",
    "USER": "USER",
    "institution": "INSTITUTION_ADMIN",
    "INSTITUTION_ADMIN": "INSTITUTION_ADMIN",
    "owner": "SYSTEM_ADMIN",
    "admin": "SYSTEM_ADMIN",
    "SYSTEM_ADMIN": "SYSTEM_ADMIN",
}

def canonical_role(role_name: str) -> str:
    if not role_name:
        return ROLE_USER
    return ROLE_MAP.get(role_name, role_name)

def initialize():
    with connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('USER','INSTITUTION_ADMIN','SYSTEM_ADMIN','verifier','institution','owner')),
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
          reference TEXT, transaction_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          details TEXT, ip_address TEXT
        );
        ''')

        # Idempotent upgrade of users table columns first
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for name, definition in {
            "approval_status": "TEXT NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK(approval_status IN ('PENDING_APPROVAL','APPROVED','REJECTED','SUSPENDED','REVOKED'))",
            "institution_reference": "TEXT",
            "verification_info": "TEXT",
            "oauth_provider": "TEXT",
            "oauth_id": "TEXT",
            "email_verified": "INTEGER NOT NULL DEFAULT 0",
            "institution_domain": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                if name == "approval_status":
                    conn.execute("UPDATE users SET approval_status='APPROVED'")
                if name == "email_verified":
                    conn.execute("UPDATE users SET email_verified=1")

        # Check if users table needs migration for new role check constraints
        table_info = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if table_info and "'USER'" not in table_info[0]:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS users_new (
              id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
              password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('USER','INSTITUTION_ADMIN','SYSTEM_ADMIN','verifier','institution','owner')),
              wallet TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              approval_status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK(approval_status IN ('PENDING_APPROVAL','APPROVED','REJECTED','SUSPENDED','REVOKED')),
              institution_reference TEXT,
              verification_info TEXT,
              oauth_provider TEXT,
              oauth_id TEXT,
              email_verified INTEGER NOT NULL DEFAULT 0,
              institution_domain TEXT
            );
            INSERT INTO users_new(id, email, name, password, role, wallet, created_at, approval_status, institution_reference, verification_info, oauth_provider, oauth_id, email_verified, institution_domain)
            SELECT id, email, name, password,
              CASE
                WHEN role='verifier' THEN 'USER'
                WHEN role='institution' THEN 'INSTITUTION_ADMIN'
                WHEN role='owner' THEN 'SYSTEM_ADMIN'
                ELSE role
              END,
              wallet, created_at,
              COALESCE(approval_status, 'APPROVED'),
              institution_reference, verification_info, oauth_provider, oauth_id,
              COALESCE(email_verified, 1), institution_domain
            FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
            ''')
            conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_wallet_unique ON users(lower(wallet)) WHERE wallet IS NOT NULL")

        # Create OAuth states table
        conn.execute('''
        CREATE TABLE IF NOT EXISTS oauth_states (
          state TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        ''')

        # Create email verifications table
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS email_verifications (
          id INTEGER PRIMARY KEY,
          email TEXT NOT NULL,
          token TEXT UNIQUE NOT NULL,
          code TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS email_verifications_email ON email_verifications(email);
        ''')

        # Create institution domains registry table
        conn.execute('''
        CREATE TABLE IF NOT EXISTS institution_domains (
          domain TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          verified INTEGER NOT NULL DEFAULT 1,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        # Seed known institutional domains
        initial_domains = [
            ("authentra.demo", "Meridian Institute of Technology (Demo)"),
            ("mit.edu", "Massachusetts Institute of Technology"),
            ("stanford.edu", "Stanford University"),
            ("harvard.edu", "Harvard University"),
            ("ox.ac.uk", "University of Oxford"),
            ("cam.ac.uk", "University of Cambridge"),
            ("iitb.ac.in", "Indian Institute of Technology Bombay"),
            ("iitd.ac.in", "Indian Institute of Technology Delhi"),
            ("iitm.ac.in", "Indian Institute of Technology Madras"),
            ("iisc.ac.in", "Indian Institute of Science"),
            ("annauniv.edu", "Anna University"),
            ("college.test", "Accredited Demonstration College"),
        ]
        for dom, d_name in initial_domains:
            conn.execute("INSERT OR IGNORE INTO institution_domains(domain, name, verified) VALUES(?, ?, 1)", (dom.lower(), d_name))

        # Idempotent upgrade of registrations table
        reg_columns = {row["name"] for row in conn.execute("PRAGMA table_info(registrations)")}
        for name, definition in {
            "status": "TEXT NOT NULL DEFAULT 'REGISTERED_ON_BLOCKCHAIN'",
            "network": "TEXT DEFAULT '1337'",
            "contract_address": "TEXT",
            "block_number": "INTEGER",
            "registered_at": "TEXT",
            "metadata": "TEXT",
            "requires_review": "INTEGER DEFAULT 0",
        }.items():
            if name not in reg_columns:
                conn.execute(f"ALTER TABLE registrations ADD COLUMN {name} {definition}")

        # Idempotent upgrade of verifications table
        ver_columns = {row["name"] for row in conn.execute("PRAGMA table_info(verifications)")}
        for name, definition in {
            "category": "TEXT",
            "registered_hash": "TEXT",
            "issuer": "TEXT",
            "checks": "TEXT",
            "metadata": "TEXT",
            "message": "TEXT",
        }.items():
            if name not in ver_columns:
                conn.execute(f"ALTER TABLE verifications ADD COLUMN {name} {definition}")


        # Idempotent upgrade of audit table
        audit_cols = {row["name"] for row in conn.execute("PRAGMA table_info(audit)")}
        for name, definition in {
            "details": "TEXT",
            "ip_address": "TEXT",
        }.items():
            if name not in audit_cols:
                conn.execute(f"ALTER TABLE audit ADD COLUMN {name} {definition}")

def seed_demo(registry):
    # This explicit development mode is never enabled implicitly in production.
    issuers = [a for a in registry.keys if a != registry.owner]
    accounts = [
        ("verifier@authentra.demo", "Alex Morgan", ROLE_USER, None),
        ("issuer@authentra.demo", "Meridian Institute of Technology", ROLE_INSTITUTION_ADMIN, issuers[0]),
        ("pending@authentra.demo", "Northstar Training Academy", ROLE_INSTITUTION_ADMIN, issuers[1]),
        ("owner@authentra.demo", "Platform Administrator", ROLE_SYSTEM_ADMIN, registry.owner),
    ]
    with connect() as conn:
        for email, name, role, wallet in accounts:
            domain = "authentra.demo" if role in (ROLE_INSTITUTION_ADMIN, "institution") else None
            conn.execute(
                """
                INSERT OR IGNORE INTO users(email, name, password, role, wallet, approval_status, email_verified, institution_domain)
                VALUES(?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (email, name, password_hash("AuthenTra-demo-2026!"), role, wallet, "PENDING_APPROVAL" if email.startswith("pending@") else "APPROVED", domain)
            )
            # Ensure existing rows are updated with canonical role and marked email_verified=1
            conn.execute("UPDATE users SET role=?, email_verified=1, institution_domain=COALESCE(institution_domain, ?) WHERE email=?", (role, domain, email))

def audit(conn, user_id, action, reference=None, transaction_hash=None, details=None, ip_address=None):
    conn.execute(
        "INSERT INTO audit(user_id, action, reference, transaction_hash, details, ip_address) VALUES(?,?,?,?,?,?)",
        (user_id, action, reference, transaction_hash, details, ip_address)
    )
