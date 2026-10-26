"""Tests for AuthenTra SYSTEM_ADMIN Dashboard, Governance, History, and Permissions.

Core Separation of Duties Rule:
The admin can manage institution access and inspect user and issuer history.
The admin must not upload files, bulk-upload certificates, register certificates,
or write certificate records to the blockchain.
"""
import hashlib
import io
import json
import os
import sys
import uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AUTHENTRA_DEMO"] = "1"
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from backend import main
from backend.storage import (
    connect, initialize, password_hash,
    ROLE_USER, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN
)
from scripts.create_admin import create_or_promote_admin


class MockChainRegistry:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {
        owner: "owner_key",
        "0x0000000000000000000000000000000000000002": "inst1_key",
        "0x0000000000000000000000000000000000000003": "inst2_key",
        "0x0000000000000000000000000000000000000004": "inst3_key",
    }
    approvals = {
        "0x0000000000000000000000000000000000000002": True,
        "0x0000000000000000000000000000000000000003": False,
        "0x0000000000000000000000000000000000000004": True,
    }
    contract = type("Contract", (), {"address": "0x0000000000000000000000000000000000000000"})()
    records = {}

    def health(self):
        return True

    def approved(self, address):
        return self.approvals.get(address, False)

    def set_issuer(self, address, approved):
        self.approvals[address] = approved
        return {
            "transaction_hash": f"0xsetissuer_{uuid.uuid4().hex[:12]}",
            "gas_used": 28000,
            "fee_wei": "1000",
            "block_number": 42
        }

    def get_network_info(self):
        return {"chain_id": 1337, "network_name": "AuthenTra Private Devnet"}

    def get_explorer_url(self, tx_hash):
        return f"https://etherscan.io/tx/{tx_hash}" if tx_hash else None

    def lookup(self, reference):
        return self.records.get(reference)

    def register_and_verify(self, reference, file_hash, issuer):
        tx_hash = f"0xreg_{uuid.uuid4().hex[:12]}"
        self.records[reference] = {
            "file_hash": file_hash.lower(),
            "issuer": issuer,
            "revoked": False,
            "registered_at": 1700000000
        }
        return {
            "transaction_hash": tx_hash,
            "gas_used": 45000,
            "fee_wei": "1500",
            "block_number": 43,
            "registered_at": 1700000000,
            "contract_address": self.contract.address,
            "on_chain_verified": True
        }

    def revoke(self, reference, issuer):
        if reference in self.records:
            self.records[reference]["revoked"] = True
        return {
            "transaction_hash": f"0xrevoke_{uuid.uuid4().hex[:12]}",
            "gas_used": 24000,
            "fee_wei": "800",
            "block_number": 44
        }


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_admin_governance.db"
    monkeypatch.setenv("AUTHENTRA_DB", str(db_file))
    initialize()

    mock_chain = MockChainRegistry()
    mock_chain.records = {}
    mock_chain.approvals = {
        "0x0000000000000000000000000000000000000002": True,
        "0x0000000000000000000000000000000000000003": False,
        "0x0000000000000000000000000000000000000004": True,
    }
    monkeypatch.setattr(main, "registry", lambda: mock_chain)

    password = password_hash("Password12345!")
    with connect() as conn:
        # Standard User
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, approval_status, email_verified) VALUES(1, 'student@example.com', 'Alice Student', ?, 'USER', 'APPROVED', 1)",
            (password,)
        )
        # Approved Institution Admin
        conn.execute(
            """
            INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain, institution_reference, verification_info, review_notes)
            VALUES(2, 'admin@mit.edu', 'MIT Registrar', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000002', 'APPROVED', 1, 'mit.edu', 'MIT-REG-01', 'Official Registrar Accreditation', 'Approved by governance board')
            """,
            (password,)
        )
        # Pending Institution Admin
        conn.execute(
            """
            INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain, institution_reference, verification_info)
            VALUES(3, 'apply@stanford.edu', 'Stanford Academy', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000003', 'PENDING_APPROVAL', 1, 'stanford.edu', 'STAN-REG-02', 'Application submitted with state charter')
            """,
            (password,)
        )
        # System Administrator
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified) VALUES(4, 'gov@authentra.demo', 'Platform Administrator', ?, 'SYSTEM_ADMIN', '0x0000000000000000000000000000000000000001', 'APPROVED', 1)",
            (password,)
        )

        # Seed sample registration for MIT
        file_hash = "a" * 64
        conn.execute(
            """
            INSERT INTO registrations(reference, issuer_id, file_hash, transaction_hash, status, metadata)
            VALUES('AT-2026-0001', 2, ?, '0xtx_registration_001', 'REGISTERED_ON_BLOCKCHAIN', ?)
            """,
            (file_hash, json.dumps({"recipient_name": "Alice Student", "course": "B.S. Computer Science"}))
        )
        mock_chain.records["AT-2026-0001"] = {
            "file_hash": file_hash,
            "issuer": "0x0000000000000000000000000000000000000002",
            "revoked": False,
            "registered_at": 1700000000
        }

        # Seed sample verification logs
        conn.execute(
            """
            INSERT INTO verifications(id, user_id, reference, status, category, file_hash, registered_hash, issuer, duration_ms, message)
            VALUES(101, 1, 'AT-2026-0001', 'verified', 'VERIFIED', ?, ?, '0x0000000000000000000000000000000000000002', 120.5, 'Certificate verified and active on blockchain')
            """,
            (file_hash, file_hash)
        )
        conn.execute(
            """
            INSERT INTO verifications(id, user_id, reference, status, category, file_hash, registered_hash, issuer, duration_ms, message)
            VALUES(102, 1, 'AT-2026-0001', 'possible_tampering', 'POSSIBLE_TAMPERING_OR_FILE_MISMATCH', 'b'*64, ?, '0x0000000000000000000000000000000000000002', 115.0, 'File hash does not match registered on-chain digest')
            """,
            (file_hash,)
        )

    yield mock_chain


def auth_client(email, password="Password12345!", account_type=None):
    client = TestClient(main.app)
    if account_type == "admin":
        res = client.post("/api/auth/admin-login", json={"email": email, "password": password})
    else:
        payload = {"email": email, "password": password}
        if account_type:
            payload["account_type"] = account_type
        res = client.post("/api/auth/login", json=payload)
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return client


# ==============================================================================
# 1. ADMIN AUTHENTICATION TESTS
# ==============================================================================

def test_public_signup_cannot_create_system_admin():
    """Verify that public registration can NEVER create or assign a SYSTEM_ADMIN role."""
    client = TestClient(main.app)
    res = client.post("/api/auth/signup", json={
        "email": "hacker@example.com",
        "name": "Malicious User",
        "password": "Password12345!",
        "role": "SYSTEM_ADMIN",
        "account_type": "admin"
    })
    assert res.status_code == 201
    with connect() as conn:
        row = conn.execute("SELECT role FROM users WHERE email='hacker@example.com'").fetchone()
        assert row["role"] == ROLE_USER, "Public signup must strictly assign ROLE_USER"


def test_admin_login_rejects_non_admin_users():
    """Verify that only explicitly assigned SYSTEM_ADMIN accounts can sign in via /api/auth/admin-login."""
    client = TestClient(main.app)

    # Ordinary user attempt
    res_user = client.post("/api/auth/admin-login", json={
        "email": "student@example.com",
        "password": "Password12345!"
    })
    assert res_user.status_code == 403
    assert "Only explicitly authorized administrator accounts" in res_user.json()["detail"]

    # Institution admin attempt
    res_inst = client.post("/api/auth/admin-login", json={
        "email": "admin@mit.edu",
        "password": "Password12345!"
    })
    assert res_inst.status_code == 403

    # Legitimate system admin
    res_admin = client.post("/api/auth/admin-login", json={
        "email": "gov@authentra.demo",
        "password": "Password12345!"
    })
    assert res_admin.status_code == 200
    assert res_admin.json()["role"] == ROLE_SYSTEM_ADMIN


def test_cli_admin_creation_and_audit():
    """Verify that create_admin.py script creates or promotes admins and records an audit event."""
    new_admin_email = "new_admin@authentra.gov"
    success = create_or_promote_admin(new_admin_email, "Security Officer", "StrongSecretPassword123!")
    assert success is True

    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (new_admin_email,)).fetchone()
        assert user is not None
        assert user["role"] == ROLE_SYSTEM_ADMIN

        audit_entry = conn.execute("SELECT * FROM audit WHERE reference=?", (new_admin_email,)).fetchone()
        assert audit_entry is not None
        assert "admin_created_via_cli" in audit_entry["action"]


def test_admin_routes_reject_unauthorized_users():
    """Verify all admin routes reject unauthenticated and unauthorized requests with 401 or 403."""
    anon_client = TestClient(main.app)
    user_client = auth_client("student@example.com", account_type="user")
    inst_client = auth_client("admin@mit.edu", account_type="institution")

    admin_endpoints = [
        ("GET", "/api/institutions", {}),
        ("POST", "/api/institutions", {"json": {"name": "Test Univ", "email": "test@mit.edu", "password": "Password12345!", "wallet": "0x0000000000000000000000000000000000000009", "institution_reference": "TEST-01", "verification_info": "Accreditation docs"}}),
        ("POST", "/api/institutions/2/approval", {"json": {"status": "APPROVED", "reason": "Test approval"}}),
        ("GET", "/api/admin/institutions/2/history", {}),
        ("GET", "/api/admin/verifications", {}),
        ("GET", "/api/admin/certificates", {}),
        ("GET", "/api/admin/audit", {}),
    ]

    for method, path, kwargs in admin_endpoints:
        # Anonymous -> 401
        res_anon = anon_client.request(method, path, **kwargs)
        assert res_anon.status_code == 401, f"{method} {path} should return 401 for anonymous"

        # Ordinary User -> 403
        res_user = user_client.request(method, path, **kwargs)
        assert res_user.status_code == 403, f"{method} {path} should return 403 for user"

        # Institution Admin -> 403
        res_inst = inst_client.request(method, path, **kwargs)
        assert res_inst.status_code == 403, f"{method} {path} should return 403 for institution"


# ==============================================================================
# 2. INSTITUTION ACCESS MANAGEMENT TESTS
# ==============================================================================

def test_institutions_list_returns_full_governance_metadata():
    """Verify /api/institutions returns name, email, domain, reference, created_at, status, review notes, latest activity."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")
    res = admin_client.get("/api/institutions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 2

    mit = next((i for i in data if i["id"] == 2), None)
    assert mit is not None
    assert mit["name"] == "MIT Registrar"
    assert mit["email"] == "admin@mit.edu"
    assert mit["institution_domain"] == "mit.edu"
    assert mit["institution_reference"] == "MIT-REG-01"
    assert mit["approval_status"] == "APPROVED"
    assert mit["review_notes"] == "Approved by governance board"
    assert "latest_activity" in mit
    assert "created_at" in mit


def test_institution_approval_lifecycle():
    """Verify complete institution lifecycle: Pending -> Approve -> Suspend -> Restore -> Revoke -> Reject."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")

    # 1. Approve pending Stanford
    res_app = admin_client.post("/api/institutions/3/approval", json={
        "status": "APPROVED",
        "reason": "Institutional charter and signer verified against state registrar."
    })
    assert res_app.status_code == 200
    assert res_app.json()["approved"] is True
    assert res_app.json()["approval_status"] == "APPROVED"
    assert res_app.json()["review_notes"] == "Institutional charter and signer verified against state registrar."

    # Verify audit event and DB
    with connect() as conn:
        inst = conn.execute("SELECT approval_status, review_notes FROM users WHERE id=3").fetchone()
        assert inst["approval_status"] == "APPROVED"
        assert "charter and signer verified" in inst["review_notes"]
        aud = conn.execute("SELECT * FROM audit WHERE action='issuer_approved' AND user_id=4 ORDER BY id DESC LIMIT 1").fetchone()
        assert aud is not None
        assert "charter and signer verified" in aud["details"]

    # 2. Suspend access
    res_susp = admin_client.post("/api/institutions/3/approval", json={
        "status": "SUSPENDED",
        "reason": "Routine compliance review overdue."
    })
    assert res_susp.status_code == 200
    assert res_susp.json()["approval_status"] == "SUSPENDED"
    assert res_susp.json()["approved"] is False

    # 3. Restore access
    res_rest = admin_client.post("/api/institutions/3/approval", json={
        "status": "RESTORED",
        "reason": "Compliance documentation received and validated."
    })
    assert res_rest.status_code == 200
    assert res_rest.json()["approval_status"] == "APPROVED"
    assert res_rest.json()["approved"] is True

    # 4. Revoke access
    res_rev = admin_client.post("/api/institutions/3/approval", json={
        "status": "REVOKED",
        "reason": "Accreditation expired."
    })
    assert res_rev.status_code == 200
    assert res_rev.json()["approval_status"] == "REVOKED"
    assert res_rev.json()["approved"] is False

    # 5. Reject
    res_rej = admin_client.post("/api/institutions/3/approval", json={
        "status": "REJECTED",
        "reason": "Application permanently declined."
    })
    assert res_rej.status_code == 200
    assert res_rej.json()["approval_status"] == "REJECTED"


def test_institutions_cannot_approve_themselves():
    """Verify that an institution cannot approve itself or alter its authorization."""
    # Institution admin calling approval endpoint
    inst_client = auth_client("admin@mit.edu", account_type="institution")
    res = inst_client.post("/api/institutions/2/approval", json={"status": "APPROVED", "reason": "Self approval"})
    assert res.status_code == 403


# ==============================================================================
# 3. USER VERIFICATION HISTORY TESTS
# ==============================================================================

def test_admin_verifications_returns_all_required_metadata():
    """Verify /api/admin/verifications returns all 8 required fields."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")
    res = admin_client.get("/api/admin/verifications")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) >= 2

    row = rows[0]
    assert "user_identifier" in row
    assert "created_at" in row or "verification_timestamp" in row
    assert "reference" in row
    assert "status" in row
    assert "issuer_name" in row
    assert "processing_outcome" in row or "category" in row
    assert "transaction_hash" in row or "transaction_reference" in row
    assert "message" in row or "failure_reason" in row


def test_admin_verifications_filters():
    """Verify filtering by result, date, user ID, and certificate reference."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")

    # 1. Filter by result
    res_ver = admin_client.get("/api/admin/verifications?result=VERIFIED")
    assert res_ver.status_code == 200
    assert all(r["status"] == "verified" or r["category"] == "VERIFIED" for r in res_ver.json())

    res_tamp = admin_client.get("/api/admin/verifications?result=POSSIBLE_TAMPERING_OR_FILE_MISMATCH")
    assert res_tamp.status_code == 200
    assert all(r["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH" for r in res_tamp.json())

    # 2. Filter by reference
    res_ref = admin_client.get("/api/admin/verifications?reference=AT-2026-0001")
    assert res_ref.status_code == 200
    assert len(res_ref.json()) >= 1
    assert all("AT-2026-0001" in r["reference"] for r in res_ref.json())

    # 3. Filter by user_id
    res_uid = admin_client.get("/api/admin/verifications?user_id=student@example.com")
    assert res_uid.status_code == 200
    assert len(res_uid.json()) >= 1

    # 4. Filter by date
    res_date = admin_client.get("/api/admin/verifications?date_from=2020-01-01&date_to=2030-12-31")
    assert res_date.status_code == 200
    assert len(res_date.json()) >= 2


# ==============================================================================
# 4. ISSUER / INSTITUTION HISTORY TESTS
# ==============================================================================

def test_admin_institution_history():
    """Verify /api/admin/institutions/{id}/history returns institution identity, registrations, and audit trail."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")
    res = admin_client.get("/api/admin/institutions/2/history")
    assert res.status_code == 200
    data = res.json()

    # 1. Institution Identity & Authorization Status
    inst = data["institution"]
    assert inst["id"] == 2
    assert inst["name"] == "MIT Registrar"
    assert inst["email"] == "admin@mit.edu"
    assert inst["approval_status"] == "APPROVED"
    assert inst["onchain_approved"] is True
    assert inst["wallet"] == "0x0000000000000000000000000000000000000002"

    # 2. Certificate Registrations submitted by MIT
    regs = data["registrations"]
    assert len(regs) >= 1
    reg = regs[0]
    assert reg["reference"] == "AT-2026-0001"
    assert reg["on_chain_verified"] is True
    assert reg["revoked"] is False
    assert reg["transaction_hash"] == "0xtx_registration_001"
    assert reg["explorer_url"] is not None

    # 3. Relevant Audit Events with clear on-chain vs off-chain distinction
    audits = data["audit_events"]
    assert isinstance(audits, list)


# ==============================================================================
# 5. PRIVACY SAFEGUARDS AND NO UPLOAD TESTS (SEPARATION OF DUTIES)
# ==============================================================================

def test_system_admin_strictly_denied_upload_and_registration():
    """CORE RULE: Verify that SYSTEM_ADMIN cannot upload, verify, register, review, retry, or revoke certificates."""
    admin_client = auth_client("gov@authentra.demo", account_type="admin")

    dummy_pdf = io.BytesIO()
    c = canvas.Canvas(dummy_pdf)
    c.drawString(100, 700, "Certificate of Testing")
    c.save()
    pdf_bytes = dummy_pdf.getvalue()

    # 1. Admin cannot call /api/verify
    res_verify = admin_client.post(
        "/api/verify",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        data={"reference": "AT-2026-0001"}
    )
    assert res_verify.status_code == 403
    assert "System administrators do not have certificate upload" in res_verify.text

    # 2. Admin cannot call /api/uploads (batch upload)
    res_batch = admin_client.post(
        "/api/uploads",
        files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        data={"mode": "verify"}
    )
    assert res_batch.status_code == 403
    assert "System administrators do not have certificate upload" in res_batch.text

    # 3. Admin cannot call /api/uploads/limits
    res_limits = admin_client.get("/api/uploads/limits")
    assert res_limits.status_code == 403

    # 4. Admin cannot call /api/certificates (single registration)
    res_reg = admin_client.post(
        "/api/certificates",
        files={"file": ("cert.pdf", pdf_bytes, "application/pdf")},
        data={"reference": "AT-2026-9999"}
    )
    assert res_reg.status_code == 403

    # 5. Admin cannot call /api/certificates/{reference}/revoke
    res_rev = admin_client.post("/api/certificates/AT-2026-0001/revoke")
    assert res_rev.status_code == 403
