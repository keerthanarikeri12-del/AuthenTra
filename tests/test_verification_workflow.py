import os
os.environ["AUTHENTRA_DEMO"] = "1"
import hashlib
import io
import json
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from backend import main
from backend.storage import connect, password_hash
from backend.documents import extract_fields, analyze

class MockVerificationBlockchain:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {
        "0x0000000000000000000000000000000000000001": "key1",
        "0x0000000000000000000000000000000000000002": "key2",
        "0x0000000000000000000000000000000000000003": "key3",
    }
    contract = type("MockContract", (), {"address": "0x1234567890123456789012345678901234567890"})()

    def __init__(self):
        self.records = {}
        self.approved_issuers = {
            "0x0000000000000000000000000000000000000002": True,
            "0x0000000000000000000000000000000000000003": False, # disabled / unauthorized issuer
        }
        self.fail_mode = None # "offline", "error"

    def health(self):
        return self.fail_mode != "offline"

    def lookup(self, reference):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused: node offline")
        return self.records.get(reference.strip().upper())

    def approved(self, address):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused: node offline")
        return self.approved_issuers.get(address.lower(), False)

    def get_network_info(self):
        return {
            "chain_id": 1337,
            "network_name": "Local development · chain 1337",
            "contract_address": self.contract.address,
            "explorer_template": "https://etherscan.io/tx/{tx_hash}"
        }

    def get_explorer_url(self, tx_hash):
        if tx_hash:
            return f"https://etherscan.io/tx/{tx_hash}"
        return None

def make_test_pdf(reference="AT-2026-TEST", name="Jane Doe", course="Software Engineering", date_str="2026-01-15", extra_text=""):
    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.setTitle(str(uuid.uuid4()))
    c.drawString(50, 750, "Institution: Meridian Institute of Technology")
    c.drawString(50, 720, f"Certificate ID: {reference}")
    c.drawString(50, 690, f"Recipient: {name}")
    c.drawString(50, 660, f"Course: {course}")
    c.drawString(50, 630, f"Issue Date: {date_str}")
    if extra_text:
        c.drawString(50, 600, extra_text)
    c.save()
    return stream.getvalue()

@pytest.fixture
def v_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "verify_test.db")
    monkeypatch.setenv("AUTHENTRA_DB", db_path)
    mock_chain = MockVerificationBlockchain()
    monkeypatch.setattr(main, "Registry", lambda: mock_chain)
    monkeypatch.setattr(main, "registry", lambda: mock_chain)
    main.LOGIN_ATTEMPTS.clear()

    with TestClient(main.app) as client:
        # Pre-seed verified institutions and registrations in DB
        with connect() as conn:
            conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role, wallet, approval_status) VALUES(2, 'issuer@authentra.demo', 'Meridian Institute of Technology', 'hash', 'institution', '0x0000000000000000000000000000000000000002', 'APPROVED')")
            conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role, wallet, approval_status) VALUES(3, 'disabled@authentra.demo', 'Rogue Academy', 'hash', 'institution', '0x0000000000000000000000000000000000000003', 'SUSPENDED')")
        yield client, mock_chain, db_path

def login_verifier(client):
    r = client.post("/api/auth/login", json={"email": "verifier@authentra.demo", "password": "AuthenTra-demo-2026!", "account_type": "user"})
    assert r.status_code == 200
    return r

# 1. EXACT REGISTERED FILE FROM AN AUTHORIZED ISSUER -> VERIFIED
def test_exact_registered_file_verified(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    pdf_bytes = make_test_pdf("AT-2026-VERIFIED", "Alice Smith", "Data Science")
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    authorized_issuer = "0x0000000000000000000000000000000000000002"

    # Register on mock blockchain
    chain.records["AT-2026-VERIFIED"] = {
        "file_hash": file_hash,
        "issuer": authorized_issuer,
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference, issuer_id, file_hash, transaction_hash) VALUES('AT-2026-VERIFIED', 2, ?, '0xaaa111')", (file_hash,))

    res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "VERIFIED"
    assert data["status"] == "verified"
    assert data["label"] == "Verified"
    assert "matches the registered hash" in data["message"]
    assert data["hash_matches"] is True
    assert "Exact match" in data["hash_comparison"]
    assert data["issuer_authorized"] is True
    assert data["blockchain_record_status"] == "ACTIVE"
    assert data["issuer_name"] == "Meridian Institute of Technology"
    assert data["next_action"] is not None
    assert data["file_hash"] == file_hash
    assert data["registered_hash"] == file_hash
    assert data["fields"]["reference"] == "AT-2026-VERIFIED"
    assert data["explorer_url"] == "https://etherscan.io/tx/0xaaa111"

# 2. ALTERED FILE WITH KNOWN REFERENCE -> POSSIBLE_TAMPERING_OR_FILE_MISMATCH
def test_altered_file_possible_tampering(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-2026-TAMPER", "Bob Jones", "Physics")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    chain.records["AT-2026-TAMPER"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }

    # Alter the file while keeping the exact same Certificate ID
    altered_bytes = make_test_pdf("AT-2026-TAMPER", "Bob Jones (Modified Grade)", "Physics")
    altered_hash = hashlib.sha256(altered_bytes).hexdigest()
    assert altered_hash != orig_hash

    res = client.post("/api/verify", files={"file": ("cert.pdf", altered_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
    assert data["status"] == "possible_tampering"
    assert "differs from the registered original" in data["message"]
    assert "rescanning" in data["message"].lower() or "re-exporting" in data["message"].lower()
    assert data["hash_matches"] is False
    assert data["registered_hash"] == orig_hash
    assert data["file_hash"] == altered_hash
    # PROVE: Tampering is NOT labeled as absolute proof of fraud
    assert "does not prove" not in data["message"] or "fraud" not in data["message"]
    assert data["blockchain_record_status"] == "ACTIVE"

# 3. UNKNOWN CERTIFICATE REFERENCE -> NOT_REGISTERED_OR_INCONCLUSIVE
def test_unknown_reference_not_registered(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    unreg_bytes = make_test_pdf("AT-2026-UNKNOWN", "Charlie Brown", "Art")
    res = client.post("/api/verify", files={"file": ("cert.pdf", unreg_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "NOT_REGISTERED_OR_INCONCLUSIVE"
    assert data["status"] == "not_registered"
    assert "No registration exists" in data["message"]
    assert "does not prove that the document is forged" in data["message"]
    assert data["registered_hash"] is None
    assert data["hash_matches"] is None
    assert data["blockchain_record_status"] == "NOT_FOUND"

# 4. REVOKED CERTIFICATE -> REVOKED
def test_revoked_certificate(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    pdf_bytes = make_test_pdf("AT-2026-REVOKED", "David Smith", "Economics")
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    chain.records["AT-2026-REVOKED"] = {
        "file_hash": file_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": True, # Marked REVOKED on chain
    }

    res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "REVOKED"
    assert data["status"] == "revoked"
    assert "revoked this certificate" in data["message"]
    assert data["blockchain_record_status"] == "REVOKED"
    assert data["checks"]["active"] is False

# 5. UNAUTHORIZED ISSUER -> ISSUER_NOT_AUTHORIZED
def test_unauthorized_issuer(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    pdf_bytes = make_test_pdf("AT-2026-ROGUE", "Eve Hacker", "Finance")
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    chain.records["AT-2026-ROGUE"] = {
        "file_hash": file_hash,
        "issuer": "0x0000000000000000000000000000000000000003", # Disabled issuer
        "registered_at": 1700000000,
        "revoked": False,
    }

    res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "ISSUER_NOT_AUTHORIZED"
    assert data["status"] == "not_verified"
    assert "not currently approved" in data["message"]
    assert data["issuer_authorized"] is False
    assert data["blockchain_record_status"] == "ISSUER_UNAUTHORIZED"

# 6. BLOCKCHAIN RPC UNAVAILABLE -> VERIFICATION_UNAVAILABLE
def test_blockchain_rpc_unavailable(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    chain.fail_mode = "offline"
    pdf_bytes = make_test_pdf("AT-2026-OFFLINE", "Frank Offline", "History")

    res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "VERIFICATION_UNAVAILABLE"
    assert data["status"] == "unable_to_authenticate"
    assert "could not be reached" in data["message"] or "could not be read" in data["message"]
    assert data["checks"]["reference_found"] is None

# 7. CORRUPT FILE -> INVALID_FILE
def test_corrupt_file_invalid_file(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    corrupt_bytes = b"%PDF-1.4\ncorrupt garbage bytes that cannot be parsed by pypdf"
    res = client.post("/api/verify", files={"file": ("broken.pdf", corrupt_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "INVALID_FILE"
    assert "Invalid" in data["label"] or "Invalid File" in data["label"]
    assert data["file_hash"] is None

# 8. FIVE-FILE UPLOAD WITH MIXED RESULTS
def test_five_file_batch_upload_mixed_results(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    # Prepare 5 files
    f1 = make_test_pdf("AT-BATCH-001", "Student 1", "Math")
    h1 = hashlib.sha256(f1).hexdigest()
    chain.records["AT-BATCH-001"] = {"file_hash": h1, "issuer": "0x0000000000000000000000000000000000000002", "registered_at": 1700000000, "revoked": False}

    f2_orig = make_test_pdf("AT-BATCH-002", "Student 2", "Biology")
    chain.records["AT-BATCH-002"] = {"file_hash": hashlib.sha256(f2_orig).hexdigest(), "issuer": "0x0000000000000000000000000000000000000002", "registered_at": 1700000000, "revoked": False}
    f2 = make_test_pdf("AT-BATCH-002", "Student 2 (Modified)", "Biology") # Mismatched

    f3 = make_test_pdf("AT-BATCH-003", "Student 3", "Chemistry") # Unregistered

    f4 = make_test_pdf("AT-BATCH-004", "Student 4", "Law")
    chain.records["AT-BATCH-004"] = {"file_hash": hashlib.sha256(f4).hexdigest(), "issuer": "0x0000000000000000000000000000000000000002", "registered_at": 1700000000, "revoked": True} # Revoked

    f5 = b"Not a real PDF or image content" # Invalid

    upload_res = client.post("/api/uploads", files=[
        ("files", ("f1.pdf", f1, "application/pdf")),
        ("files", ("f2.pdf", f2, "application/pdf")),
        ("files", ("f3.pdf", f3, "application/pdf")),
        ("files", ("f4.pdf", f4, "application/pdf")),
        ("files", ("f5.pdf", f5, "application/pdf")),
    ], data={"mode": "verify", "references": '["","","","",""]'})
    assert upload_res.status_code == 202
    job_id = upload_res.json()["id"]

    # Poll until completed
    for _ in range(50):
        batch = client.get(f"/api/uploads/{job_id}").json()
        if batch["state"] == "completed":
            break
        time.sleep(0.1)
    assert batch["state"] == "completed"

    items = batch["items"]
    assert len(items) == 5

    # Check categories of each item
    item_cats = [i["result"]["category"] for i in items]
    assert "VERIFIED" in item_cats
    assert "POSSIBLE_TAMPERING_OR_FILE_MISMATCH" in item_cats
    assert "NOT_REGISTERED_OR_INCONCLUSIVE" in item_cats
    assert "REVOKED" in item_cats
    assert "INVALID_FILE" in item_cats

    # Check multi-file verification summary counts
    v_sum = batch.get("verification_summary")
    assert v_sum is not None
    assert v_sum["verified"] == 1
    assert v_sum["mismatched"] == 1
    assert v_sum["unregistered"] == 1
    assert v_sum["revoked"] == 1
    assert v_sum["invalid"] == 1

# 9. RE-EXPORTED CERTIFICATE WITH CHANGED HASH
def test_reexported_certificate_causes_mismatch_with_explanation(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    # Create original certificate
    orig_cert = make_test_pdf("AT-2026-REEXPORT", "Grace Hopper", "Computer Science")
    orig_hash = hashlib.sha256(orig_cert).hexdigest()

    # Register original hash
    chain.records["AT-2026-REEXPORT"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }

    # Simulate re-exporting the exact same certificate with different internal metadata/stream
    # (Visually identical metadata fields, but re-saved/re-rendered with distinct bytes)
    reexported_cert = make_test_pdf("AT-2026-REEXPORT", "Grace Hopper", "Computer Science", extra_text="Re-exported digital copy")
    reexported_hash = hashlib.sha256(reexported_cert).hexdigest()
    assert reexported_hash != orig_hash

    res = client.post("/api/verify", files={"file": ("reexported.pdf", reexported_cert)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
    assert data["hash_matches"] is False
    assert data["file_hash"] == reexported_hash
    assert data["registered_hash"] == orig_hash
    # The message MUST clearly explain that re-exporting/rescanning causes a mismatch
    assert "re-exporting" in data["message"].lower() or "re-saving" in data["message"].lower() or "scanning" in data["message"].lower()
    # The next action advises verifying the original file
    assert "original" in data["next_action"].lower()

# 10. HISTORY PERSISTENCE AND DATA PRIVACY ISOLATION
def test_verification_history_scoped_to_user(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    # Perform a check
    pdf_bytes = make_test_pdf("AT-HIST-001", "Secret Student", "Confidential Course")
    client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})

    # Fetch history as verifier
    h1 = client.get("/api/history").json()
    assert len(h1) > 0
    assert any(h["reference"] == "AT-HIST-001" for h in h1)

    # Sign in as a different user (e.g. institution)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "issuer@authentra.demo", "password": "AuthenTra-demo-2026!", "account_type": "institution"})

    # Fetch history as institution: MUST NOT see verifier's check!
    h2 = client.get("/api/history").json()
    assert not any(h["reference"] == "AT-HIST-001" for h in h2)
