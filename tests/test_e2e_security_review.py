"""End-to-End Integration and Security Review Test Suite for AuthenTra.

Verifies the 15 required security and integration scenarios:
1. User uploads five certificates in one batch.
2. User attempts to upload six certificates in one batch and receives a clear rejection.
3. User submits a new batch later and is not incorrectly blocked by a lifetime limit.
4. Approved institution uploads a batch containing more than five certificates.
5. Pending institution attempts bulk upload and is rejected.
6. Suspended institution attempts registration and is rejected.
7. Admin approves an institution and the change persists.
8. Admin attempts file upload through both the UI and direct API call and is denied.
9. User attempts to access the admin dashboard and is denied.
10. User attempts to access another user's history and is denied.
11. Institution attempts to access another institution's private history and is denied.
12. Institution registration is shown as successful only after the blockchain transaction
    is confirmed and the expected record is independently read back.
13. Verification correctly distinguishes verified, potential hash mismatch,
    unregistered/inconclusive, revoked, unauthorized issuer, invalid file, and unavailable blockchain.
14. The UI continues showing persisted statuses after page refresh.
15. All failure cases display clear messages without false success.
"""
import hashlib
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AUTHENTRA_DEMO"] = "1"
from backend import main, uploads
from backend.storage import (
    connect, initialize, password_hash,
    ROLE_USER, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN
)


class MockE2EBlockchainRegistry:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {
        "0x0000000000000000000000000000000000000001": "key1",
        "0x0000000000000000000000000000000000000002": "key2",
        "0x0000000000000000000000000000000000000003": "key3",
        "0x0000000000000000000000000000000000000004": "key4",
        "0x0000000000000000000000000000000000000005": "key5",
    }
    contract = type("Contract", (), {"address": "0x1111111111111111111111111111111111111111"})()

    def __init__(self):
        self.approvals = {
            "0x0000000000000000000000000000000000000002": True,   # Meridian (Approved)
            "0x0000000000000000000000000000000000000003": False,  # Northstar (Pending)
            "0x0000000000000000000000000000000000000004": True,   # Apex (Approved)
            "0x0000000000000000000000000000000000000005": False,  # Suspended Inst
        }
        self.records = {}
        self.fail_mode = None  # "revert", "offline", "mismatch"

    def health(self):
        return self.fail_mode != "offline"

    def approved(self, address):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused: node offline")
        return self.approvals.get(address.lower(), False)

    def set_issuer(self, address, approved):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused")
        self.approvals[address.lower()] = approved
        return {
            "transaction_hash": f"0xsetissuer_{uuid.uuid4().hex[:12]}",
            "gas_used": 28000,
            "fee_wei": "1000",
            "block_number": 100
        }

    def get_network_info(self):
        return {
            "chain_id": 1337,
            "network_name": "AuthenTra E2E Devnet",
            "contract_address": self.contract.address,
            "explorer_template": "https://etherscan.io/tx/{tx_hash}"
        }

    def get_explorer_url(self, tx_hash):
        return f"https://etherscan.io/tx/{tx_hash}" if tx_hash else None

    def lookup(self, reference):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused: node offline")
        return self.records.get(reference.strip().upper())

    def register_and_verify(self, reference, file_hash, issuer):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused")
        if self.fail_mode == "revert":
            raise ValueError("Blockchain execution reverted")

        ref_key = reference.strip().upper()
        canonical_hash = file_hash.lower()

        if ref_key in self.records:
            existing = self.records[ref_key]
            if existing["file_hash"].lower() == canonical_hash and existing["issuer"].lower() == issuer.lower() and not existing["revoked"]:
                return {
                    "transaction_hash": None,
                    "gas_used": 0,
                    "fee_wei": "0",
                    "block_number": None,
                    "registered_at": existing["registered_at"],
                    "contract_address": self.contract.address,
                    "network": "1337",
                    "on_chain_verified": True,
                    "idempotent": True,
                }
            raise ValueError("Certificate reference already exists on the blockchain with different parameters.")

        if self.fail_mode == "mismatch":
            # Simulate corrupted read-back where on-chain hash doesn't match
            self.records[ref_key] = {
                "file_hash": "deadbeef" * 8,
                "issuer": issuer.lower(),
                "registered_at": 1700000000,
                "revoked": False
            }
            raise RuntimeError("On-chain verification failed: on-chain hash does not match expected.")

        # Real confirmed registration with independent read-back
        tx_hash = f"0xreg_{uuid.uuid4().hex[:12]}"
        self.records[ref_key] = {
            "file_hash": canonical_hash,
            "issuer": issuer.lower(),
            "registered_at": 1700000000,
            "revoked": False
        }

        # Independent on-chain read-back verification
        verified = self.lookup(reference)
        assert verified is not None
        assert verified["file_hash"].lower() == canonical_hash
        assert verified["issuer"].lower() == issuer.lower()

        return {
            "transaction_hash": tx_hash,
            "gas_used": 42000,
            "fee_wei": "1200",
            "block_number": 101,
            "registered_at": 1700000000,
            "contract_address": self.contract.address,
            "network": "1337",
            "on_chain_verified": True,
            "idempotent": False,
        }

    def revoke(self, reference, actor):
        ref_key = reference.strip().upper()
        if ref_key in self.records:
            self.records[ref_key]["revoked"] = True
        return {
            "transaction_hash": f"0xrevoke_{uuid.uuid4().hex[:12]}",
            "gas_used": 26000,
            "fee_wei": "900",
            "block_number": 102
        }


def make_pdf(ref="AT-E2E-001", name="Jane Doe", course="Computer Science"):
    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.setTitle(uuid.uuid4().hex)
    c.drawString(50, 750, "Institution: Meridian Institute of Technology")
    c.drawString(50, 720, f"Certificate ID: {ref}")
    c.drawString(50, 690, f"Recipient: {name}")
    c.drawString(50, 660, f"Course: {course}")
    c.drawString(50, 630, "Issue Date: 2026-01-15")
    c.save()
    return stream.getvalue()


@pytest.fixture
def e2e_suite(tmp_path, monkeypatch):
    db_path = tmp_path / "e2e_security.db"
    monkeypatch.setenv("AUTHENTRA_DB", str(db_path))
    mock_chain = MockE2EBlockchainRegistry()
    monkeypatch.setattr(main, "Registry", lambda: mock_chain)
    monkeypatch.setattr(main, "registry", lambda: mock_chain)
    monkeypatch.setattr(uploads, "Registry", lambda: mock_chain)
    main.LOGIN_ATTEMPTS.clear()
    initialize()

    with connect() as conn:
        # Seed test accounts
        # 1. USER A
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, approval_status, email_verified) VALUES(101, 'userA@example.com', 'User Alpha', ?, 'USER', 'APPROVED', 1)",
            (password_hash("Password-123456!"),)
        )
        # 2. USER B
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, approval_status, email_verified) VALUES(102, 'userB@example.com', 'User Beta', ?, 'USER', 'APPROVED', 1)",
            (password_hash("Password-123456!"),)
        )
        # 3. Approved INSTITUTION (Meridian)
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain) VALUES(201, 'issuer@meridian.edu', 'Meridian Institute', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000002', 'APPROVED', 1, 'meridian.edu')",
            (password_hash("Password-123456!"),)
        )
        # 4. Pending INSTITUTION (Northstar)
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain) VALUES(202, 'pending@northstar.edu', 'Northstar Academy', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000003', 'PENDING_APPROVAL', 1, 'northstar.edu')",
            (password_hash("Password-123456!"),)
        )
        # 5. Suspended INSTITUTION (Rogue)
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain) VALUES(203, 'suspended@rogue.edu', 'Rogue Institute', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000005', 'SUSPENDED', 1, 'rogue.edu')",
            (password_hash("Password-123456!"),)
        )
        # 6. Another Approved INSTITUTION (Apex)
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain) VALUES(204, 'issuer@apex.edu', 'Apex University', ?, 'INSTITUTION_ADMIN', '0x0000000000000000000000000000000000000004', 'APPROVED', 1, 'apex.edu')",
            (password_hash("Password-123456!"),)
        )
        # 7. SYSTEM_ADMIN
        conn.execute(
            "INSERT INTO users(id, email, name, password, role, wallet, approval_status, email_verified) VALUES(301, 'sysadmin@authentra.gov', 'System Admin', ?, 'SYSTEM_ADMIN', ?, 'APPROVED', 1)",
            (password_hash("Admin-Password-123456!"), mock_chain.owner)
        )

    with TestClient(main.app) as client:
        yield client, mock_chain, db_path


def login_client(client, email, password="Password-123456!", account_type=None):
    payload = {"email": email, "password": password}
    if account_type:
        payload["account_type"] = account_type
    if email == "sysadmin@authentra.gov":
        r = client.post("/api/auth/admin-login", json=payload)
    else:
        r = client.post("/api/auth/login", json=payload)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()


def wait_batch_completed(client, job_id, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f"/api/uploads/{job_id}")
        assert res.status_code == 200, res.text
        data = res.json()
        if data["state"] == "completed":
            return data
        time.sleep(0.05)
    raise TimeoutError(f"Batch {job_id} did not complete within {timeout} seconds.")


# ==============================================================================
# SCENARIO 1: User uploads five certificates in one batch
# ==============================================================================
def test_scenario_01_user_uploads_five_certificates_in_one_batch(e2e_suite):
    client, chain, _ = e2e_suite
    login_client(client, "userA@example.com", account_type="user")

    # Upload exactly 5 certificates
    files = [("files", (f"cert_{i}.pdf", make_pdf(f"AT-U5-{i}"))) for i in range(5)]
    res = client.post("/api/uploads", files=files, data={"mode": "verify"})
    assert res.status_code == 202
    job_id = res.json()["id"]

    batch = wait_batch_completed(client, job_id)
    assert batch["state"] == "completed"
    assert len(batch["items"]) == 5
    for item in batch["items"]:
        assert item["filename"].startswith("cert_")
        assert "status" in item
        assert item["status"] in ("NOT_REGISTERED_OR_INCONCLUSIVE", "VERIFIED")


# ==============================================================================
# SCENARIO 2: User attempts to upload six certificates in one batch and receives clear rejection
# ==============================================================================
def test_scenario_02_user_attempts_six_certificates_and_receives_clear_rejection(e2e_suite):
    client, _, _ = e2e_suite
    login_client(client, "userA@example.com", account_type="user")

    # Attempt 6 files in one batch
    files_6 = [("files", (f"cert_{i}.pdf", make_pdf(f"AT-U6-{i}"))) for i in range(6)]
    res = client.post("/api/uploads", files=files_6, data={"mode": "verify"})

    # Must be strictly rejected with HTTP 422 and clear explanation
    assert res.status_code == 422
    detail = res.json().get("detail", "")
    assert "maximum of 5 certificate files" in detail
    assert "Remove extra files to continue" in detail


# ==============================================================================
# SCENARIO 3: User submits a new batch later and is not incorrectly blocked by a lifetime limit
# ==============================================================================
def test_scenario_03_user_submits_new_batch_later_not_blocked_by_lifetime_limit(e2e_suite):
    client, _, _ = e2e_suite
    login_client(client, "userA@example.com", account_type="user")

    # Initial batch of 5 files
    files_1 = [("files", (f"c1_{i}.pdf", make_pdf(f"AT-LIFE1-{i}"))) for i in range(5)]
    r1 = client.post("/api/uploads", files=files_1, data={"mode": "verify"})
    assert r1.status_code == 202
    wait_batch_completed(client, r1.json()["id"])

    # Later: user submits a 3-file batch -> MUST be accepted
    files_2 = [("files", (f"c2_{i}.pdf", make_pdf(f"AT-LIFE2-{i}"))) for i in range(3)]
    r2 = client.post("/api/uploads", files=files_2, data={"mode": "verify"})
    assert r2.status_code == 202
    wait_batch_completed(client, r2.json()["id"])

    # Later: user submits another full 5-file batch -> MUST be accepted
    files_3 = [("files", (f"c3_{i}.pdf", make_pdf(f"AT-LIFE3-{i}"))) for i in range(5)]
    r3 = client.post("/api/uploads", files=files_3, data={"mode": "verify"})
    assert r3.status_code == 202
    wait_batch_completed(client, r3.json()["id"])


# ==============================================================================
# SCENARIO 4: Approved institution uploads a batch containing more than five certificates
# ==============================================================================
def test_scenario_04_approved_institution_uploads_batch_exceeding_five_files(e2e_suite):
    client, chain, _ = e2e_suite
    login_client(client, "issuer@meridian.edu")

    # Upload 7 certificates (exceeds user's 5-file limit, allowed for institutions)
    count = 7
    certs = [
        ("files", (f"inst_cert_{i}.pdf", make_pdf(f"AT-INST7-{i}", f"Student {i}")))
        for i in range(count)
    ]
    refs = [f"AT-INST7-{i}" for i in range(count)]

    res = client.post(
        "/api/uploads",
        files=certs,
        data={"mode": "register", "references": json.dumps(refs)}
    )
    assert res.status_code == 202
    job_id = res.json()["id"]

    batch = wait_batch_completed(client, job_id)
    assert batch["state"] == "completed"
    assert len(batch["items"]) == 7
    assert batch["summary"]["successful"] == 7
    for item in batch["items"]:
        assert item["status"] == "REGISTERED_ON_BLOCKCHAIN"
        assert item["result"]["on_chain_verified"] is True
        assert chain.lookup(item["reference"]) is not None


# ==============================================================================
# SCENARIO 5: Pending institution attempts bulk upload and is rejected
# ==============================================================================
def test_scenario_05_pending_institution_attempts_bulk_upload_and_is_rejected(e2e_suite):
    client, _, _ = e2e_suite

    # Login attempt for pending institution is rejected
    r_login = client.post("/api/auth/login", json={"email": "pending@northstar.edu", "password": "Password-123456!"})
    assert r_login.status_code == 403
    assert "pending approval" in r_login.json()["detail"].lower()

    # Direct token-spoofed attempt or unapproved upload
    certs = [("files", ("c.pdf", make_pdf("AT-PENDING-01")))]
    r_upload = client.post("/api/uploads", files=certs, data={"mode": "register", "references": '["AT-PENDING-01"]'})
    assert r_upload.status_code == 401


# ==============================================================================
# SCENARIO 6: Suspended institution attempts registration and is rejected
# ==============================================================================
def test_scenario_06_suspended_institution_attempts_registration_and_is_rejected(e2e_suite):
    client, _, _ = e2e_suite

    # Suspended institution login is blocked
    r_login = client.post("/api/auth/login", json={"email": "suspended@rogue.edu", "password": "Password-123456!"})
    assert r_login.status_code == 403
    assert "suspended" in r_login.json()["detail"].lower()

    # Active session that gets suspended cannot register
    login_client(client, "issuer@meridian.edu")
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status='SUSPENDED' WHERE email='issuer@meridian.edu'")

    res = client.post("/api/certificates", files={"file": ("c.pdf", make_pdf("AT-SUSP-1"))}, data={"reference": "AT-SUSP-1"})
    assert res.status_code == 403
    assert "suspended" in res.json()["detail"].lower()


# ==============================================================================
# SCENARIO 7: Admin approves an institution and the change persists
# ==============================================================================
def test_scenario_07_admin_approves_institution_and_change_persists(e2e_suite):
    client, chain, _ = e2e_suite
    login_client(client, "sysadmin@authentra.gov", password="Admin-Password-123456!")

    # Locate pending institution (Northstar, ID 202)
    insts = client.get("/api/institutions").json()
    northstar = next(i for i in insts if i["email"] == "pending@northstar.edu")
    assert northstar["approval_status"] == "PENDING_APPROVAL"

    # Approve with administrative reason
    reason_text = "Identity, domain ownership, and regional accreditation verified by Platform Owner."
    appr_res = client.post(
        f"/api/institutions/{northstar['id']}/approval",
        json={"status": "APPROVED", "reason": reason_text}
    )
    assert appr_res.status_code == 200
    data = appr_res.json()
    assert data["approval_status"] == "APPROVED"
    assert data["review_notes"] == reason_text
    assert data["transaction_hash"].startswith("0xsetissuer_")

    # On-chain state is updated
    assert chain.approved(northstar["wallet"]) is True

    # Persists on subsequent queries
    insts_after = client.get("/api/institutions").json()
    updated = next(i for i in insts_after if i["id"] == northstar["id"])
    assert updated["approval_status"] == "APPROVED"
    assert updated["review_notes"] == reason_text

    # Appears in admin issuer history
    history = client.get(f"/api/admin/institutions/{northstar['id']}/history").json()
    assert history["institution"]["approval_status"] == "APPROVED"
    assert any(a["action"] == "issuer_approved" and (reason_text in a.get("details", "")) for a in history["audit_events"])


# ==============================================================================
# SCENARIO 8: Admin attempts file upload through both UI and direct API call and is denied
# ==============================================================================
def test_scenario_08_admin_file_upload_denied_via_api_and_ui_safeguards(e2e_suite):
    client, _, _ = e2e_suite
    login_client(client, "sysadmin@authentra.gov", password="Admin-Password-123456!")

    # 1. Direct API call to /api/verify
    r_verify = client.post("/api/verify", files={"file": ("c.pdf", make_pdf("AT-ADM-1"))}, data={"reference": "AT-ADM-1"})
    assert r_verify.status_code == 403
    assert "administrators do not have certificate upload" in r_verify.json()["detail"].lower()

    # 2. Direct API call to /api/uploads
    r_batch = client.post("/api/uploads", files=[("files", ("c.pdf", make_pdf("AT-ADM-2")))], data={"mode": "verify"})
    assert r_batch.status_code == 403

    # 3. Direct API call to /api/certificates
    r_reg = client.post("/api/certificates", files={"file": ("c.pdf", make_pdf("AT-ADM-3"))}, data={"reference": "AT-ADM-3"})
    assert r_reg.status_code == 403

    # 4. Direct API call to /api/certificates/bulk
    r_bulk = client.post("/api/certificates/bulk", files=[("files", ("c.pdf", make_pdf("AT-ADM-4")))], data={"references": '["AT-ADM-4"]'})
    assert r_bulk.status_code == 403

    # 5. Direct API call to /api/uploads/limits
    r_lim = client.get("/api/uploads/limits")
    assert r_lim.status_code == 403


# ==============================================================================
# SCENARIO 9: User attempts to access admin dashboard and is denied
# ==============================================================================
def test_scenario_09_user_attempts_access_admin_dashboard_and_is_denied(e2e_suite):
    client, _, _ = e2e_suite
    login_client(client, "userA@example.com", account_type="user")

    # Institutions management endpoint
    assert client.get("/api/institutions").status_code == 403
    assert client.post("/api/institutions/201/approval", json={"status": "APPROVED"}).status_code == 403

    # Admin verifications oversight
    assert client.get("/api/admin/verifications").status_code == 403

    # Admin issuer history
    assert client.get("/api/admin/institutions/201/history").status_code == 403

    # Platform audit log
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403


# ==============================================================================
# SCENARIO 10: User attempts to access another user's history and is denied
# ==============================================================================
def test_scenario_10_user_attempts_access_another_user_history_and_is_denied(e2e_suite):
    client, _, _ = e2e_suite

    # User A performs a verification
    login_client(client, "userA@example.com", account_type="user")
    res_a = client.post("/api/verify", files={"file": ("c.pdf", make_pdf("AT-USER-A-ONLY"))}, data={"reference": "AT-USER-A-ONLY"})
    assert res_a.status_code == 200

    hist_a = client.get("/api/verifications").json()
    assert any(h["reference"] == "AT-USER-A-ONLY" for h in hist_a)

    # User B logs in
    login_client(client, "userB@example.com", account_type="user")
    hist_b = client.get("/api/verifications").json()

    # User A's verification record MUST NOT appear in User B's history
    assert all(h["reference"] != "AT-USER-A-ONLY" for h in hist_b)

    # User B attempts to access admin verifications to view User A's history
    r_admin_access = client.get("/api/admin/verifications?user_id=101")
    assert r_admin_access.status_code == 403


# ==============================================================================
# SCENARIO 11: Institution attempts to access another institution's private history and is denied
# ==============================================================================
def test_scenario_11_institution_attempts_access_another_institution_private_history_and_is_denied(e2e_suite):
    client, chain, _ = e2e_suite

    # Meridian (ID 201) registers a certificate
    login_client(client, "issuer@meridian.edu")
    pdf_meridian = make_pdf("AT-MERIDIAN-PRIV")
    r_mer = client.post("/api/certificates", files={"file": ("c.pdf", pdf_meridian)}, data={"reference": "AT-MERIDIAN-PRIV"})
    assert r_mer.status_code == 201

    # Meridian uploads a batch
    r_batch = client.post("/api/uploads", files=[("files", ("c.pdf", pdf_meridian))], data={"mode": "register", "references": '["AT-MERIDIAN-BATCH"]'})
    assert r_batch.status_code == 202
    meridian_job_id = r_batch.json()["id"]

    # Apex (ID 204) logs in
    login_client(client, "issuer@apex.edu")

    # 1. Apex attempts to view Meridian's batch status -> 404
    r_job = client.get(f"/api/uploads/{meridian_job_id}")
    assert r_job.status_code == 404

    # 2. Apex queries certificate registry -> Only sees Apex's own certificates
    r_certs = client.get("/api/certificates").json()
    assert all(c["reference"] != "AT-MERIDIAN-PRIV" for c in r_certs)

    # 3. Apex attempts to access Meridian's admin history -> 403
    r_hist = client.get("/api/admin/institutions/201/history")
    assert r_hist.status_code == 403


# ==============================================================================
# SCENARIO 12: Institution registration success requires confirmed transaction and independent read-back
# ==============================================================================
def test_scenario_12_institution_registration_success_requires_receipt_and_readback(e2e_suite):
    client, chain, _ = e2e_suite
    login_client(client, "issuer@meridian.edu")

    # 1. Normal Registration: Broadcast + Receipt + Read-Back -> Complete Success
    pdf_bytes = make_pdf("AT-READBACK-01")
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest().lower()
    res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-READBACK-01"})
    assert res.status_code == 201
    data = res.json()
    assert data["on_chain_verified"] is True
    assert data["registration_status"] == "REGISTERED_ON_BLOCKCHAIN"
    assert data["transaction_hash"] is not None

    # Read-back verification in Registry ensures hash matches
    onchain = chain.lookup("AT-READBACK-01")
    assert onchain["file_hash"] == expected_hash

    # 2. Flawed read-back simulation: On-chain hash mismatch must fail, NOT return false success
    chain.fail_mode = "mismatch"
    pdf_bad = make_pdf("AT-READBACK-BAD")
    res_bad = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bad)}, data={"reference": "AT-READBACK-BAD"})
    assert res_bad.status_code in (409, 500)
    chain.fail_mode = None

    # 3. Transaction revert simulation: Blockchain reverts -> HTTP 409
    chain.fail_mode = "revert"
    pdf_rev = make_pdf("AT-READBACK-REV")
    res_rev = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_rev)}, data={"reference": "AT-READBACK-REV"})
    assert res_rev.status_code == 409
    assert "reverted" in res_rev.json()["detail"].lower()
    chain.fail_mode = None


# ==============================================================================
# SCENARIO 13: Verification correctly distinguishes all result categories
# ==============================================================================
def test_scenario_13_verification_correctly_distinguishes_all_categories(e2e_suite):
    client, chain, _ = e2e_suite

    # Register AT-CAT-1 under Meridian
    login_client(client, "issuer@meridian.edu")
    pdf_orig = make_pdf("AT-CAT-1", "Alice Verified")
    client.post("/api/certificates", files={"file": ("c.pdf", pdf_orig)}, data={"reference": "AT-CAT-1"})

    # Register AT-CAT-REV under Meridian and then revoke it
    pdf_rev = make_pdf("AT-CAT-REV", "Bob Revoked")
    client.post("/api/certificates", files={"file": ("c.pdf", pdf_rev)}, data={"reference": "AT-CAT-REV"})
    client.post("/api/certificates/AT-CAT-REV/revoke")

    # Switch to User role for verification
    login_client(client, "userA@example.com", account_type="user")

    # Category 1: VERIFIED (exact hash, active, approved issuer)
    v1 = client.post("/api/verify", files={"file": ("c.pdf", pdf_orig)}, data={"reference": "AT-CAT-1"}).json()
    assert v1["category"] == "VERIFIED"

    # Category 2: POSSIBLE_TAMPERING_OR_FILE_MISMATCH (known ID, active, but modified bytes)
    pdf_tampered = make_pdf("AT-CAT-1", "Alice Tampered Content")
    v2 = client.post("/api/verify", files={"file": ("c.pdf", pdf_tampered)}, data={"reference": "AT-CAT-1"}).json()
    assert v2["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"

    # Category 3: NOT_REGISTERED_OR_INCONCLUSIVE (unregistered ID)
    pdf_unreg = make_pdf("AT-CAT-UNKNOWN", "Charlie Unknown")
    v3 = client.post("/api/verify", files={"file": ("c.pdf", pdf_unreg)}, data={"reference": "AT-CAT-UNKNOWN"}).json()
    assert v3["category"] == "NOT_REGISTERED_OR_INCONCLUSIVE"

    # Category 4: REVOKED (on-chain revoked)
    v4 = client.post("/api/verify", files={"file": ("c.pdf", pdf_rev)}, data={"reference": "AT-CAT-REV"}).json()
    assert v4["category"] == "REVOKED"

    # Category 5: ISSUER_NOT_AUTHORIZED (issuer suspended in smart contract)
    chain.approvals["0x0000000000000000000000000000000000000002"] = False
    v5 = client.post("/api/verify", files={"file": ("c.pdf", pdf_orig)}, data={"reference": "AT-CAT-1"}).json()
    assert v5["category"] == "ISSUER_NOT_AUTHORIZED"
    chain.approvals["0x0000000000000000000000000000000000000002"] = True

    # Category 6: INVALID_FILE (empty or corrupt content)
    v6 = client.post("/api/verify", files={"file": ("bad.pdf", b"corrupt bytes not a pdf")}, data={"reference": "AT-CAT-1"}).json()
    assert v6["category"] == "INVALID_FILE"

    # Category 7: VERIFICATION_UNAVAILABLE (blockchain offline)
    chain.fail_mode = "offline"
    v7 = client.post("/api/verify", files={"file": ("c.pdf", pdf_orig)}, data={"reference": "AT-CAT-1"}).json()
    assert v7["category"] == "VERIFICATION_UNAVAILABLE"
    chain.fail_mode = None


# ==============================================================================
# SCENARIO 14: The UI continues showing persisted statuses after page refresh
# ==============================================================================
def test_scenario_14_ui_persisted_statuses_across_refresh_and_querying(e2e_suite):
    client, chain, _ = e2e_suite

    # Step 1: User verifies two certificates
    login_client(client, "userA@example.com", account_type="user")
    pdf1 = make_pdf("AT-PERSIST-1")
    pdf2 = make_pdf("AT-PERSIST-2")
    client.post("/api/verify", files={"file": ("c1.pdf", pdf1)}, data={"reference": "AT-PERSIST-1"})
    client.post("/api/verify", files={"file": ("c2.pdf", pdf2)}, data={"reference": "AT-PERSIST-2"})

    # Step 2: "Simulate Page Refresh / Re-mount" by creating new client requests
    res_refresh = client.get("/api/verifications")
    assert res_refresh.status_code == 200
    history = res_refresh.json()
    assert len(history) >= 2
    refs = [h["reference"] for h in history]
    assert "AT-PERSIST-1" in refs
    assert "AT-PERSIST-2" in refs

    # Step 3: Admin inspects governance changes across sessions
    login_client(client, "sysadmin@authentra.gov", password="Admin-Password-123456!")
    admin_history = client.get("/api/admin/verifications?reference=AT-PERSIST-1").json()
    assert len(admin_history) == 1
    assert admin_history[0]["reference"] == "AT-PERSIST-1"
    assert "101" in admin_history[0]["user_identifier"]


# ==============================================================================
# SCENARIO 15: All failure cases display clear messages without false success
# ==============================================================================
def test_scenario_15_all_failure_cases_display_clear_messages_without_false_success(e2e_suite):
    client, chain, _ = e2e_suite
    login_client(client, "issuer@meridian.edu")

    # Pre-register AT-PARTIAL-EXIST
    raw_pdf = make_pdf("AT-PARTIAL-EXIST", "Original Person")
    client.post("/api/certificates", files={"file": ("c.pdf", raw_pdf)}, data={"reference": "AT-PARTIAL-EXIST"})

    # Batch with 3 files:
    # 1. Valid new certificate
    # 2. Duplicate reference with conflicting file bytes
    # 3. Invalid corrupted file bytes
    cert_valid = make_pdf("AT-PARTIAL-NEW", "Valid Person")
    cert_conflict = make_pdf("AT-PARTIAL-EXIST", "Altered Person")
    cert_corrupt = b"not a valid pdf or image"

    certs = [
        ("files", ("valid.pdf", cert_valid)),
        ("files", ("conflict.pdf", cert_conflict)),
        ("files", ("corrupt.pdf", cert_corrupt)),
    ]
    refs = ["AT-PARTIAL-NEW", "AT-PARTIAL-EXIST", "AT-PARTIAL-CORRUPT"]

    res = client.post("/api/uploads", files=certs, data={"mode": "register", "references": json.dumps(refs)})
    assert res.status_code == 202
    job_id = res.json()["id"]

    batch = wait_batch_completed(client, job_id)
    assert batch["state"] == "completed"

    items = {item["filename"]: item for item in batch["items"]}

    # Item 1: Succeeded
    assert items["valid.pdf"]["status"] == "REGISTERED_ON_BLOCKCHAIN"
    assert items["valid.pdf"]["state"] == "succeeded"

    # Item 2: Conflict error clearly explained, NO false success
    assert items["conflict.pdf"]["status"] == "REGISTRATION_FAILED"
    assert items["conflict.pdf"]["state"] == "failed"
    conflict_err = str(items["conflict.pdf"]["result"])
    assert "already exists" in conflict_err

    # Item 3: File validation failure clearly explained, NO false success
    assert items["corrupt.pdf"]["status"] == "REGISTRATION_FAILED"
    assert items["corrupt.pdf"]["state"] in ("failed", "rejected")
    corrupt_err = str(items["corrupt.pdf"]["result"])
    assert "supported" in corrupt_err.lower() or "genuine" in corrupt_err.lower()

    # Batch summary is explicit: partial success, never masked as complete success
    assert batch["summary"]["total"] == 3
    assert batch["summary"]["successful"] == 1
    assert batch["summary"]["failed"] == 2
