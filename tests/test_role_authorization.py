"""Comprehensive Authorization and Security Tests for AuthenTra Roles:
- ROLE 1: USER
- ROLE 2: INSTITUTION_ADMIN
- ROLE 3: SYSTEM_ADMIN

Verifies all permissions, restrictions, limits, boundary conditions,
and audit logging across backend endpoints.
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
from backend.storage import connect, initialize, password_hash, ROLE_USER, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN


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
        return {
            "chain_id": 1337,
            "network_name": "Local development · chain 1337",
            "contract_address": self.contract.address,
            "explorer_template": None
        }

    def get_explorer_url(self, tx_hash):
        return f"https://mockscan.io/tx/{tx_hash}" if tx_hash else None

    def lookup(self, reference):
        return self.records.get(reference)

    def register_and_verify(self, reference, file_hash, issuer):
        rec = {
            "file_hash": file_hash,
            "issuer": issuer,
            "registered_at": 1700000000,
            "revoked": False
        }
        self.records[reference] = rec
        return {
            "transaction_hash": f"0xreg_{uuid.uuid4().hex[:12]}",
            "gas_used": 68000,
            "fee_wei": "2000",
            "block_number": 45,
            "registered_at": 1700000000,
            "contract_address": self.contract.address,
            "network": "1337",
            "on_chain_verified": True,
            "idempotent": False
        }

    def revoke(self, reference, actor):
        if reference in self.records:
            self.records[reference]["revoked"] = True
        return {
            "transaction_hash": f"0xrevoke_{uuid.uuid4().hex[:12]}",
            "gas_used": 31000,
            "fee_wei": "1500",
            "block_number": 48
        }


@pytest.fixture
def auth_suite(tmp_path, monkeypatch):
    db_path = tmp_path / "test_roles.db"
    monkeypatch.setenv("AUTHENTRA_DB", str(db_path))
    mock_registry = MockChainRegistry()
    mock_registry.records.clear()
    monkeypatch.setattr(main, "Registry", lambda: mock_registry)
    main.LOGIN_ATTEMPTS.clear()
    initialize()

    with connect() as conn:
        # Seed test accounts for each role
        # 1. USER
        conn.execute(
            """
            INSERT INTO users(email, name, password, role, approval_status, email_verified)
            VALUES('user@example.com', 'Standard User', ?, 'USER', 'APPROVED', 1)
            """,
            (password_hash("Password-123456!"),)
        )
        # 2. Approved INSTITUTION_ADMIN (Meridian)
        conn.execute(
            """
            INSERT INTO users(email, name, password, role, wallet, approval_status, email_verified, institution_domain)
            VALUES('issuer@meridian.edu', 'Meridian Institute', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000002', 'APPROVED', 1, 'meridian.edu')
            """,
            (password_hash("Password-123456!"),)
        )
        # 3. Pending INSTITUTION_ADMIN (Northstar)
        conn.execute(
            """
            INSERT INTO users(email, name, password, role, wallet, approval_status, email_verified, institution_domain)
            VALUES('pending@northstar.edu', 'Northstar Academy', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000003', 'PENDING_APPROVAL', 1, 'northstar.edu')
            """,
            (password_hash("Password-123456!"),)
        )
        # 4. Another approved INSTITUTION_ADMIN (Apex)
        conn.execute(
            """
            INSERT INTO users(email, name, password, role, wallet, approval_status, email_verified, institution_domain)
            VALUES('issuer@apex.edu', 'Apex University', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000004', 'APPROVED', 1, 'apex.edu')
            """,
            (password_hash("Password-123456!"),)
        )
        # 5. SYSTEM_ADMIN
        conn.execute(
            """
            INSERT INTO users(email, name, password, role, wallet, approval_status, email_verified)
            VALUES('sysadmin@authentra.gov', 'System Governance Administrator', ?, 'SYSTEM_ADMIN', ?, 'APPROVED', 1)
            """,
            (password_hash("Admin-Password-123456!"), mock_registry.owner)
        )

    with TestClient(main.app) as client:
        yield client, mock_registry


def make_pdf(ref="AT-TEST-001"):
    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.setTitle(uuid.uuid4().hex)
    c.drawString(50, 700, f"Certificate ID: {ref}")
    c.drawString(50, 680, "Awarded to Jane Doe")
    c.save()
    return stream.getvalue()


# ==============================================================================
# 1. ROLE 1: USER TESTS
# ==============================================================================

def test_user_login_and_dashboard(auth_suite):
    client, _ = auth_suite
    login_res = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password-123456!", "account_type": "user"})
    assert login_res.status_code == 200
    user = login_res.json()
    assert user["role"] == "USER"
    assert user["email"] == "user@example.com"

    # User dashboard
    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    d = dash.json()
    assert d["role"] == "USER"
    assert "total" in d
    assert "verified" in d
    assert "review" in d
    assert d["registered"] == 0


def test_user_verification_single_and_batch_limits(auth_suite):
    client, _ = auth_suite
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password-123456!", "account_type": "user"})

    # Single verify
    v_res = client.post("/api/verify", files={"file": ("cert.pdf", make_pdf("AT-USER-1"))}, data={"reference": "AT-USER-1"})
    assert v_res.status_code == 200
    data = v_res.json()
    assert "status" in data
    assert "category" in data

    # Batch verify with 5 files (allowed limit - accepted)
    files = [("files", (f"file_{i}.pdf", make_pdf(f"AT-BATCH-{i}"))) for i in range(5)]
    batch_res = client.post("/api/uploads", files=files, data={"mode": "verify"})
    assert batch_res.status_code == 202

    # Batch verify with 6 files (exceeds 5-file limit -> strictly rejected)
    files_6 = [("files", (f"file_{i}.pdf", make_pdf(f"AT-BATCH6-{i}"))) for i in range(6)]
    batch_fail = client.post("/api/uploads", files=files_6, data={"mode": "verify"})
    assert batch_fail.status_code == 422
    assert "maximum of 5 certificate files" in batch_fail.json()["detail"]

    # USER submits another valid batch later (3 files): accepted (proves no unintended lifetime limit)
    files_later = [("files", (f"file_later_{i}.pdf", make_pdf(f"AT-BATCH-LATER-{i}"))) for i in range(3)]
    batch_later = client.post("/api/uploads", files=files_later, data={"mode": "verify"})
    assert batch_later.status_code == 202
    assert "id" in batch_later.json()

    # USER submits a second full 5-file batch later: accepted
    files_full = [("files", (f"file_full_{i}.pdf", make_pdf(f"AT-BATCH-FULL-{i}"))) for i in range(5)]
    batch_full = client.post("/api/uploads", files=files_full, data={"mode": "verify"})
    assert batch_full.status_code == 202


def test_user_history_privacy(auth_suite):
    client, _ = auth_suite
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password-123456!", "account_type": "user"})

    # Perform a check
    client.post("/api/verify", files={"file": ("cert.pdf", make_pdf("AT-PRIV-1"))}, data={"reference": "AT-PRIV-1"})

    history = client.get("/api/history").json()
    assert len(history) == 1
    assert history[0]["reference"] == "AT-PRIV-1"

    # Inject a record belonging to another user ID
    with connect() as conn:
        conn.execute("INSERT INTO users(id, email, name, password, role) VALUES(999, 'other@example.com', 'Other User', 'hash', 'USER')")
        conn.execute("INSERT INTO verifications(user_id, reference, status) VALUES(999, 'OTHER-USER-CERT', 'verified')")

    # History remains scoped strictly to this user
    history2 = client.get("/api/history").json()
    assert len(history2) == 1
    assert all(r["reference"] != "OTHER-USER-CERT" for r in history2)


def test_user_cannot_register_or_revoke_or_manage_institutions(auth_suite):
    client, _ = auth_suite
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password-123456!", "account_type": "user"})

    # Cannot register certificate
    assert client.post("/api/certificates", files={"file": ("c.pdf", make_pdf())}, data={"reference": "AT-FORBIDDEN"}).status_code == 403

    # Cannot bulk register
    assert client.post("/api/certificates/bulk", files=[("files", ("c.pdf", make_pdf()))], data={"references": '["AT-FORBIDDEN"]'}).status_code == 403

    # Cannot upload in register mode
    assert client.post("/api/uploads", files=[("files", ("c.pdf", make_pdf()))], data={"mode": "register"}).status_code == 403

    # Cannot revoke certificates
    assert client.post("/api/certificates/AT-1/revoke").status_code == 403

    # Cannot access certificate registry list
    assert client.get("/api/certificates").status_code == 403

    # Cannot access institutions
    assert client.get("/api/institutions").status_code == 403
    assert client.post("/api/institutions/1/approval", json={"status": "APPROVED"}).status_code == 403

    # Cannot access admin endpoints
    assert client.get("/api/admin/verifications").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.get("/api/admin/certificates").status_code == 403


# ==============================================================================
# 2. ROLE 2: INSTITUTION_ADMIN TESTS
# ==============================================================================

def test_institution_pending_approval_cannot_operate(auth_suite):
    client, _ = auth_suite
    # Pending institution signin is rejected at login
    res = client.post("/api/auth/login", json={"email": "pending@northstar.edu", "password": "Password-123456!", "account_type": "institution"})
    assert res.status_code == 403
    assert "pending approval" in res.json()["detail"].lower()


def test_approved_institution_dashboard_and_bulk_upload_no_5_file_limit(auth_suite):
    client, _ = auth_suite
    login_res = client.post("/api/auth/login", json={"email": "issuer@meridian.edu", "password": "Password-123456!", "account_type": "institution"})
    assert login_res.status_code == 200
    user = login_res.json()
    assert user["role"] == "INSTITUTION_ADMIN"
    assert user["approval_status"] == "APPROVED"

    # Dashboard
    dash = client.get("/api/dashboard").json()
    assert dash["role"] == "INSTITUTION_ADMIN"
    assert dash["institution_name"] == "Meridian Institute"

    # Upload limits in register mode: no 5-file limit (allows up to bulk limit e.g. 100)
    limits = client.get("/api/uploads/limits?mode=register").json()
    assert limits["max_files"] >= 100

    # Bulk upload 6 files (proves NO five-file limit for institution admin)
    files = [("files", (f"cert_{i}.pdf", make_pdf(f"MERIDIAN-BULK-{i}"))) for i in range(6)]
    refs = json.dumps([f"MERIDIAN-BULK-{i}" for i in range(6)])
    bulk_res = client.post("/api/certificates/bulk", files=files, data={"references": refs})
    assert bulk_res.status_code == 202
    assert "id" in bulk_res.json()


def test_institution_registers_and_revokes_own_certificate(auth_suite):
    client, registry = auth_suite
    client.post("/api/auth/login", json={"email": "issuer@meridian.edu", "password": "Password-123456!", "account_type": "institution"})

    # Single register
    pdf_bytes = make_pdf("MERIDIAN-REG-1")
    reg_res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "MERIDIAN-REG-1"})
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["reference"] == "MERIDIAN-REG-1"
    assert reg_data["on_chain_verified"] is True
    assert reg_data["transaction_hash"].startswith("0xreg_")

    # Appears in own institution's registry
    my_certs = client.get("/api/certificates").json()
    assert any(c["reference"] == "MERIDIAN-REG-1" for c in my_certs)

    # Revoke own certificate
    revoke_res = client.post("/api/certificates/MERIDIAN-REG-1/revoke")
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # Verify on-chain status is revoked
    on_chain = registry.lookup("MERIDIAN-REG-1")
    assert on_chain["revoked"] is True


def test_institution_cannot_approve_or_revoke_other_institutions(auth_suite):
    client, _ = auth_suite
    # Register certificate as Apex
    client.post("/api/auth/login", json={"email": "issuer@apex.edu", "password": "Password-123456!", "account_type": "institution"})
    reg_res = client.post("/api/certificates", files={"file": ("apex.pdf", make_pdf("APEX-001"))}, data={"reference": "APEX-001"})
    assert reg_res.status_code == 201

    # Login as Meridian
    client.post("/api/auth/login", json={"email": "issuer@meridian.edu", "password": "Password-123456!", "account_type": "institution"})

    # Meridian CANNOT see Apex's certificates in /api/certificates
    meridian_certs = client.get("/api/certificates").json()
    assert all(c["reference"] != "APEX-001" for c in meridian_certs)

    # Meridian CANNOT revoke Apex's certificate
    assert client.post("/api/certificates/APEX-001/revoke").status_code == 403

    # Meridian CANNOT approve itself or Northstar
    assert client.post("/api/institutions/3/approval", json={"status": "APPROVED"}).status_code == 403
    assert client.get("/api/institutions").status_code == 403


# ==============================================================================
# 3. ROLE 3: SYSTEM_ADMIN TESTS
# ==============================================================================

def test_admin_login_entry_point_and_role_protection(auth_suite):
    client, _ = auth_suite

    # Non-admin attempting Admin Login receives 403 Forbidden
    user_attempt = client.post("/api/auth/admin-login", json={"email": "user@example.com", "password": "Password-123456!"})
    assert user_attempt.status_code == 403
    assert "authorized administrator" in user_attempt.json()["detail"].lower()

    inst_attempt = client.post("/api/auth/admin-login", json={"email": "issuer@meridian.edu", "password": "Password-123456!"})
    assert inst_attempt.status_code == 403

    # Authorized admin logs in successfully
    admin_res = client.post("/api/auth/admin-login", json={"email": "sysadmin@authentra.gov", "password": "Admin-Password-123456!"})
    assert admin_res.status_code == 200
    admin_data = admin_res.json()
    assert admin_data["role"] == "SYSTEM_ADMIN"
    assert admin_data["email"] == "sysadmin@authentra.gov"


def test_system_admin_strictly_forbidden_from_upload_and_registration(auth_suite):
    client, _ = auth_suite
    client.post("/api/auth/admin-login", json={"email": "sysadmin@authentra.gov", "password": "Admin-Password-123456!"})

    # Cannot verify certificate
    v_res = client.post("/api/verify", files={"file": ("c.pdf", make_pdf())}, data={"reference": "AT-ADMIN"})
    assert v_res.status_code == 403
    assert "administrators do not have certificate upload" in v_res.json()["detail"].lower()

    # Cannot upload batches
    b_res = client.post("/api/uploads", files=[("files", ("c.pdf", make_pdf()))], data={"mode": "verify"})
    assert b_res.status_code == 403

    # Cannot query upload limits
    l_res = client.get("/api/uploads/limits")
    assert l_res.status_code == 403

    # Cannot register certificate
    r_res = client.post("/api/certificates", files={"file": ("c.pdf", make_pdf())}, data={"reference": "AT-ADMIN"})
    assert r_res.status_code == 403

    # Cannot bulk register
    bk_res = client.post("/api/certificates/bulk", files=[("files", ("c.pdf", make_pdf()))], data={"references": '["AT-ADMIN"]'})
    assert bk_res.status_code == 403


def test_system_admin_governance_and_audit_logging(auth_suite):
    client, registry = auth_suite
    client.post("/api/auth/admin-login", json={"email": "sysadmin@authentra.gov", "password": "Admin-Password-123456!"})

    # Admin dashboard overview
    dash = client.get("/api/dashboard").json()
    assert dash["role"] == "SYSTEM_ADMIN"
    assert "total_institutions" in dash
    assert "pending_institutions" in dash
    assert dash["pending_institutions"] >= 1

    # View institutions
    insts = client.get("/api/institutions").json()
    northstar = next(i for i in insts if i["email"] == "pending@northstar.edu")
    assert northstar["approval_status"] == "PENDING_APPROVAL"

    # Approve Northstar
    appr_res = client.post(f"/api/institutions/{northstar['id']}/approval", json={"status": "APPROVED"})
    assert appr_res.status_code == 200
    assert appr_res.json()["approval_status"] == "APPROVED"
    assert appr_res.json()["transaction_hash"].startswith("0xsetissuer_")

    # On-chain approval verified
    assert registry.approved(northstar["wallet"]) is True

    # Suspend Northstar
    susp_res = client.post(f"/api/institutions/{northstar['id']}/approval", json={"status": "SUSPENDED"})
    assert susp_res.status_code == 200
    assert susp_res.json()["approval_status"] == "SUSPENDED"
    assert registry.approved(northstar["wallet"]) is False

    # Inspect audit trail
    audits = client.get("/api/admin/audit").json()
    assert len(audits) >= 2
    actions = [a["action"] for a in audits]
    assert "issuer_approved" in actions
    assert "issuer_suspended" in actions


def test_system_admin_oversight_verifications_and_certificates(auth_suite):
    client, _ = auth_suite

    # Create a verification check as USER
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password-123456!", "account_type": "user"})
    client.post("/api/verify", files={"file": ("c.pdf", make_pdf("AT-CHECK-99"))}, data={"reference": "AT-CHECK-99"})

    # Switch to SYSTEM_ADMIN
    client.post("/api/auth/admin-login", json={"email": "sysadmin@authentra.gov", "password": "Admin-Password-123456!"})

    # SYSTEM_ADMIN can inspect all verifications
    verifs = client.get("/api/admin/verifications").json()
    assert len(verifs) >= 1
    assert any(v["reference"] == "AT-CHECK-99" for v in verifs)

    # SYSTEM_ADMIN can inspect all certificates across institutions
    certs = client.get("/api/admin/certificates").json()
    assert isinstance(certs, list)
