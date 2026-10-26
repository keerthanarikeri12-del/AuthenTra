import os
os.environ["AUTHENTRA_DEMO"] = "1"
import hashlib
import io
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from backend import main, uploads
from backend.storage import connect, password_hash
from backend.documents import extract_fields, analyze

class MockBlockchainRegistry:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {
        owner: "key1",
        "0x0000000000000000000000000000000000000002": "key2",
        "0x0000000000000000000000000000000000000003": "key3"
    }
    contract = type("MockContract", (), {"address": "0x1234567890123456789012345678901234567890"})()

    def __init__(self):
        self.on_chain_store = {}
        self.is_healthy = True
        self.fail_mode = None  # "revert", "timeout", "offline", "mismatch"

    def health(self):
        return self.is_healthy and self.fail_mode != "offline"

    def lookup(self, reference):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC Connection refused")
        return self.on_chain_store.get(reference.strip().upper())

    def approved(self, address):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC Connection refused")
        return True

    def get_network_info(self):
        return {
            "chain_id": 1337,
            "network_name": "Local development · chain 1337",
            "contract_address": self.contract.address,
            "explorer_template": None
        }

    def get_explorer_url(self, tx_hash):
        return None

    def register_and_verify(self, reference, file_hash, issuer):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC node unreachable")
        if self.fail_mode == "revert":
            raise ValueError("Blockchain transaction reverted.")
        if self.fail_mode == "timeout":
            raise TimeoutError("Transaction confirmation timed out.")

        ref_key = reference.strip().upper()
        if ref_key in self.on_chain_store:
            rec = self.on_chain_store[ref_key]
            if rec["file_hash"].lower() == file_hash.lower() and rec["issuer"].lower() == issuer.lower():
                return {
                    "transaction_hash": None,
                    "gas_used": 0,
                    "fee_wei": "0",
                    "block_number": None,
                    "registered_at": rec["registered_at"],
                    "contract_address": self.contract.address,
                    "network": "1337",
                    "on_chain_verified": True,
                    "idempotent": True,
                }
            raise ValueError("Certificate reference already exists on the blockchain with different parameters.")

        if self.fail_mode == "mismatch":
            # Simulate a flawed blockchain node that stores the wrong hash
            self.on_chain_store[ref_key] = {
                "file_hash": "00" * 32,
                "issuer": issuer,
                "registered_at": 1700000000,
                "revoked": False
            }
            # The read-back verification MUST detect this and fail!
            raise RuntimeError("On-chain verification failed: on-chain hash does not match expected.")

        # Successful real transaction execution & independent read-back verification
        tx_hash = "0x" + hashlib.sha256(f"{ref_key}:{file_hash}".encode()).hexdigest()
        self.on_chain_store[ref_key] = {
            "file_hash": file_hash.lower(),
            "issuer": issuer,
            "registered_at": 1700000000,
            "revoked": False
        }

        # Independent on-chain read
        verified = self.lookup(reference)
        assert verified is not None and verified["file_hash"] == file_hash.lower()

        return {
            "transaction_hash": tx_hash,
            "gas_used": 42000,
            "fee_wei": "84000000000",
            "block_number": 101,
            "registered_at": 1700000000,
            "contract_address": self.contract.address,
            "network": "1337",
            "on_chain_verified": True,
            "idempotent": False,
        }

@pytest.fixture
def reg_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "reg_test.db")
    monkeypatch.setenv("AUTHENTRA_DB", db_path)
    mock_chain = MockBlockchainRegistry()
    monkeypatch.setattr(main, "Registry", lambda: mock_chain)
    monkeypatch.setattr(main, "registry", lambda: mock_chain)
    monkeypatch.setattr(uploads, "Registry", lambda: mock_chain)
    main.LOGIN_ATTEMPTS.clear()
    with TestClient(main.app) as client:
        yield client, mock_chain, db_path

def make_cert_pdf(ref="AT-TEST-001", name="Alice Smith", course="Computer Science"):
    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.setTitle(str(uuid.uuid4()))
    c.drawString(50, 750, f"Institution: Meridian Institute of Technology")
    c.drawString(50, 720, f"Certificate ID: {ref}")
    c.drawString(50, 690, f"Recipient: {name}")
    c.drawString(50, 660, f"Course: {course}")
    c.drawString(50, 630, f"Issue Date: 2026-01-15")
    c.save()
    return stream.getvalue()

def login_as(client, role="issuer"):
    emails = {
        "issuer": "issuer@authentra.demo",
        "pending": "pending@authentra.demo",
        "verifier": "verifier@authentra.demo",
        "owner": "owner@authentra.demo",
    }
    r = client.post("/api/auth/login", json={"email": emails[role], "password": "AuthenTra-demo-2026!"})
    assert r.status_code == 200, r.text
    return r

# 1. AUTHORIZATION TESTS
def test_institution_authorization_checks(reg_env):
    client, chain, _ = reg_env
    pdf_bytes = make_cert_pdf()

    # Unauthenticated rejected
    r = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-001"})
    assert r.status_code == 401

    # Verifier role rejected (403)
    login_as(client, "verifier")
    r = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-001"})
    assert r.status_code == 403

    # Pending institution rejected (403)
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": "pending@authentra.demo", "password": "AuthenTra-demo-2026!"})
    assert r.status_code == 403

    # Suspended institution rejected
    login_as(client, "issuer")
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status='SUSPENDED' WHERE email='issuer@authentra.demo'")
    r = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-001"})
    assert r.status_code == 403
    assert "suspended" in r.json()["detail"].lower()

# 2. HASHING TESTS: Original bytes & Canonical 64-char Hex
def test_exact_original_bytes_sha256_canonical(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    raw_pdf = make_cert_pdf("AT-HASH-01")
    expected_hash = hashlib.sha256(raw_pdf).hexdigest().lower()
    assert len(expected_hash) == 64

    res = client.post("/api/certificates", files={"file": ("cert.pdf", raw_pdf)}, data={"reference": "AT-HASH-01"})
    assert res.status_code == 201
    data = res.json()

    assert data["file_hash"] == expected_hash
    assert data["status"] == "registered"
    assert data["registration_status"] == "REGISTERED_ON_BLOCKCHAIN"
    assert data["on_chain_verified"] is True
    assert chain.lookup("AT-HASH-01")["file_hash"] == expected_hash

# 3. FIELD EXTRACTION & METADATA
def test_field_extraction_and_metadata_persistence(reg_env):
    client, chain, db_path = reg_env
    login_as(client, "issuer")

    pdf_bytes = make_cert_pdf("AT-META-01", "Jane Doe", "Quantum Computing")
    res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-META-01"})
    assert res.status_code == 201

    fields = res.json()["fields"]
    assert fields["name"] == "Jane Doe"
    assert fields["course"] == "Quantum Computing"
    assert fields["reference"] == "AT-META-01"
    assert fields["date_valid"] is True

    # Confirm off-chain metadata is stored in SQLite
    with connect() as conn:
        row = conn.execute("SELECT * FROM registrations WHERE reference='AT-META-01'").fetchone()
        assert row is not None
        assert row["status"] == "REGISTERED_ON_BLOCKCHAIN"
        meta = json.loads(row["metadata"])
        assert meta["recipient_name"] == "Jane Doe"
        assert meta["course"] == "Quantum Computing"

# 4. BLOCKCHAIN READ-BACK VERIFICATION REQUIRED (Never fake success)
def test_readback_verification_failure_never_returns_success(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    # When on-chain data does not match, registration must fail
    chain.fail_mode = "mismatch"
    pdf_bytes = make_cert_pdf("AT-MISMATCH-01")
    res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-MISMATCH-01"})
    assert res.status_code in (409, 500)

# 5. BLOCKCHAIN REVERTS & UNCERTAIN OUTCOMES
def test_blockchain_revert_and_offline_honestly_reported(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    # When chain reverts
    chain.fail_mode = "revert"
    pdf_bytes = make_cert_pdf("AT-REV-01")
    res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-REV-01"})
    assert res.status_code == 409
    assert "did not confirm" in res.json()["detail"] or "reverted" in res.json()["detail"].lower()

    # When blockchain is unavailable / offline
    chain.fail_mode = "offline"
    pdf_bytes2 = make_cert_pdf("AT-OFF-01")
    res2 = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes2)}, data={"reference": "AT-OFF-01"})
    assert res2.status_code == 503
    assert "blockchain is unavailable" in res2.json()["detail"].lower()

# 6. IDEMPOTENT DUPLICATE HANDLING
def test_idempotent_duplicate_handling(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    pdf_bytes = make_cert_pdf("AT-IDEM-01")
    res1 = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-IDEM-01"})
    assert res1.status_code == 201
    assert res1.json()["on_chain_verified"] is True

    # Re-submitting identical certificate bytes with identical ID: idempotent success!
    res2 = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-IDEM-01"})
    assert res2.status_code == 201
    assert res2.json()["idempotent"] is True
    assert res2.json()["status"] == "registered"

    # Re-using the same reference with DIFFERENT content: must reject with 409
    diff_pdf = make_cert_pdf("AT-IDEM-01", "Different Recipient")
    res3 = client.post("/api/certificates", files={"file": ("cert.pdf", diff_pdf)}, data={"reference": "AT-IDEM-01"})
    assert res3.status_code == 409

# 7. AUDIT LOGGING WITHOUT SENSITIVE CONTENTS
def test_audit_logs_contain_no_personal_data(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    secret_name = "VeryPrivateStudentName12345"
    pdf_bytes = make_cert_pdf("AT-AUDIT-01", secret_name)
    res = client.post("/api/certificates", files={"file": ("cert.pdf", pdf_bytes)}, data={"reference": "AT-AUDIT-01"})
    assert res.status_code == 201

    with connect() as conn:
        logs = conn.execute("SELECT * FROM audit WHERE reference='AT-AUDIT-01'").fetchall()
        assert len(logs) > 0
        for entry in logs:
            row_dict = dict(entry)
            assert secret_name not in str(row_dict)
            assert "Quantum" not in str(row_dict)
            assert row_dict["action"] in ("register_confirmed", "register")

# 8. HUMAN REVIEW WORKFLOW FOR MISSING OR AMBIGUOUS METADATA
def test_human_review_workflow(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    # Item with awaiting review state
    with connect() as conn:
        conn.execute("INSERT INTO upload_jobs(id, user_id, mode, state) VALUES('job-review', 2, 'register', 'processing')")
        cursor = conn.execute("""
            INSERT INTO upload_items(job_id, filename, reference, kind, state, status, data, result)
            VALUES('job-review', 'scan.png', '', 'image', 'awaiting_review', 'AWAITING_REVIEW', NULL, ?)
        """, (json.dumps({"status": "AWAITING_REVIEW", "message": "Reference missing"}),))
        item_id = cursor.lastrowid

    # Review endpoint: approve with provided reference
    review_res = client.post(f"/api/uploads/job-review/items/{item_id}/review", json={
        "action": "approve",
        "reference": "AT-REVIEWED-01",
        "name": "Bob Reviewee",
        "course": "Cybersecurity"
    })
    assert review_res.status_code == 200
    item = [i for i in review_res.json()["items"] if i["id"] == item_id][0]
    assert item["status"] == "PENDING_BLOCKCHAIN"
    assert item["reference"] == "AT-REVIEWED-01"


import time

def wait_batch(client, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f"/api/uploads/{job_id}")
        assert res.status_code == 200, res.text
        data = res.json()
        if data["state"] == "completed":
            return data
        time.sleep(0.05)
    raise TimeoutError(f"Batch {job_id} did not complete within {timeout}s")


# 9. BULK REGISTRATION WORKFLOW & FRONTEND STATUSES
def test_bulk_registration_batch_workflow_and_statuses(reg_env):
    client, chain, db_path = reg_env
    login_as(client, "issuer")

    certs = [
        ("cert1.pdf", make_cert_pdf("AT-BULK-01", "Alice Student", "Data Science")),
        ("cert2.pdf", make_cert_pdf("AT-BULK-02", "Bob Graduate", "Machine Learning")),
        ("cert3.pdf", make_cert_pdf("AT-BULK-03", "Carol Scholar", "Computer Science")),
    ]
    refs = ["AT-BULK-01", "AT-BULK-02", "AT-BULK-03"]

    upload_res = client.post(
        "/api/uploads",
        files=[("files", c) for c in certs],
        data={"mode": "register", "references": json.dumps(refs)}
    )
    assert upload_res.status_code == 202
    job_id = upload_res.json()["id"]

    batch = wait_batch(client, job_id)
    assert batch["state"] == "completed"
    assert batch["summary"]["total"] == 3
    assert batch["summary"]["successful"] == 3
    assert batch["summary"]["failed"] == 0

    for item in batch["items"]:
        assert item["status"] == "REGISTERED_ON_BLOCKCHAIN"
        assert item["state"] == "succeeded"
        assert item["result"]["on_chain_verified"] is True
        assert item["result"]["transaction_hash"] is not None
        assert chain.lookup(item["reference"]) is not None

    with connect() as conn:
        rows = conn.execute("SELECT * FROM registrations WHERE reference LIKE 'AT-BULK%'").fetchall()
        assert len(rows) == 3
        for r in rows:
            assert r["status"] == "REGISTERED_ON_BLOCKCHAIN"


# 10. PARTIAL FAILURES DO NOT FAIL THE WHOLE BATCH
def test_bulk_registration_partial_failure_does_not_fail_whole_batch(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    # Register AT-EXISTING-01 first
    raw_pdf = make_cert_pdf("AT-EXISTING-01")
    r0 = client.post("/api/certificates", files={"file": ("cert.pdf", raw_pdf)}, data={"reference": "AT-EXISTING-01"})
    assert r0.status_code == 201

    # Batch with: 1 valid new, 1 duplicate ID with different bytes, 1 invalid file content
    diff_pdf = make_cert_pdf("AT-EXISTING-01", "Different Recipient")
    valid_pdf = make_cert_pdf("AT-VALID-NEW", "David New", "Robotics")
    invalid_bytes = b"CORRUPTED_NOT_PDF"

    files = [
        ("valid.pdf", valid_pdf),
        ("dup.pdf", diff_pdf),
        ("corrupt.pdf", invalid_bytes),
    ]
    refs = ["AT-VALID-NEW", "AT-EXISTING-01", "AT-CORRUPT-01"]

    upload_res = client.post(
        "/api/uploads",
        files=[("files", f) for f in files],
        data={"mode": "register", "references": json.dumps(refs)}
    )
    assert upload_res.status_code == 202
    batch = wait_batch(client, upload_res.json()["id"])

    assert batch["state"] == "completed"
    assert batch["summary"]["total"] == 3
    assert batch["summary"]["successful"] == 1
    assert batch["summary"]["failed"] == 2

    statuses = {i["reference"]: i["status"] for i in batch["items"]}
    assert statuses["AT-VALID-NEW"] == "REGISTERED_ON_BLOCKCHAIN"
    assert statuses["AT-EXISTING-01"] == "REGISTRATION_FAILED"
    assert statuses["AT-CORRUPT-01"] == "REGISTRATION_FAILED"


# 11. UNCERTAIN TRANSACTION OUTCOME AND RETRY WORKFLOW
def test_uncertain_transaction_outcome_and_retry(reg_env):
    client, chain, _ = reg_env
    login_as(client, "issuer")

    pdf_bytes = make_cert_pdf("AT-UNCERTAIN-01")
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest().lower()

    # Configure timeout failure mode
    chain.fail_mode = "timeout"
    upload_res = client.post(
        "/api/uploads",
        files=[("files", ("cert.pdf", pdf_bytes))],
        data={"mode": "register", "references": json.dumps(["AT-UNCERTAIN-01"])}
    )
    assert upload_res.status_code == 202
    batch = wait_batch(client, upload_res.json()["id"])

    item = batch["items"][0]
    assert item["status"] == "REGISTRATION_STATUS_UNCERTAIN"
    assert "uncertain" in item["result"]["status"].lower() or "timed out" in item["result"]["error"].lower()

    # Now simulate that transaction confirmed on-chain
    chain.fail_mode = None
    chain.on_chain_store["AT-UNCERTAIN-01"] = {
        "file_hash": expected_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False
    }

    # Retry endpoint checks on-chain state and promotes to REGISTERED_ON_BLOCKCHAIN
    retry_res = client.post(f"/api/uploads/{batch['id']}/items/{item['id']}/retry")
    assert retry_res.status_code == 200
    retried_item = [i for i in retry_res.json()["items"] if i["id"] == item["id"]][0]
    assert retried_item["status"] == "REGISTERED_ON_BLOCKCHAIN"
    assert retried_item["state"] == "succeeded"


# 12. ROLE BOUNDARIES: USER AND SYSTEM_ADMIN CANNOT REGISTER OR BULK-UPLOAD
def test_system_admin_and_user_rejected_from_bulk_registration(reg_env):
    client, chain, _ = reg_env

    # 1. Ordinary USER rejected
    login_as(client, "verifier")
    pdf_bytes = make_cert_pdf("AT-FORBID-01")
    r1 = client.post("/api/uploads", files=[("files", ("c.pdf", pdf_bytes))], data={"mode": "register", "references": json.dumps(["AT-FORBID-01"])})
    assert r1.status_code == 403

    r2 = client.post("/api/certificates", files={"file": ("c.pdf", pdf_bytes)}, data={"reference": "AT-FORBID-01"})
    assert r2.status_code == 403

    # 2. SYSTEM_ADMIN rejected
    login_as(client, "owner")
    r3 = client.post("/api/uploads", files=[("files", ("c.pdf", pdf_bytes))], data={"mode": "register", "references": json.dumps(["AT-FORBID-01"])})
    assert r3.status_code == 403

    r4 = client.post("/api/certificates", files={"file": ("c.pdf", pdf_bytes)}, data={"reference": "AT-FORBID-01"})
    assert r4.status_code == 403


# 13. MISSING BLOCKCHAIN CONFIGURATION REPORTED HONESTLY
def test_missing_blockchain_configuration_reported_honestly(reg_env, monkeypatch):
    client, _, _ = reg_env
    login_as(client, "issuer")
    monkeypatch.setenv("AUTHENTRA_DEMO", "0")
    monkeypatch.delenv("RPC_URL", raising=False)
    monkeypatch.delenv("CONTRACT_ADDRESS", raising=False)

    from backend.registry import Registry
    with pytest.raises(RuntimeError) as exc_info:
        Registry()
    assert "Missing blockchain configuration" in str(exc_info.value)
    assert "RPC_URL" in str(exc_info.value)
