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

    def lookup_by_hash(self, file_hash):
        if self.fail_mode == "offline":
            raise RuntimeError("RPC connection refused: node offline")
        canonical = (file_hash or "").lower().removeprefix("0x")
        for ref, rec in self.records.items():
            if rec.get("file_hash", "").lower() == canonical:
                return {**rec, "reference": ref}
        return None

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

def make_test_pdf(reference="AT-2026-TEST", name="Jane Doe", course="Software Engineering", date_str="2026-01-15", institution="Meridian Institute of Technology", grade=None, venue=None, extra_text=""):
    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.setTitle(str(uuid.uuid4()))
    if institution:
        c.drawString(50, 750, f"Institution: {institution}")
    if reference:
        c.drawString(50, 720, f"Certificate ID: {reference}")
    if name:
        c.drawString(50, 690, f"Recipient: {name}")
    if course:
        c.drawString(50, 660, f"Course: {course}")
    if date_str:
        c.drawString(50, 630, f"Issue Date: {date_str}")
    if grade:
        c.drawString(50, 600, f"Grade: {grade}")
    if venue:
        c.drawString(50, 570, f"Venue: {venue}")
    if extra_text:
        c.drawString(50, 540, extra_text)
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


def test_missing_uploaded_name_is_not_copied_from_registered_metadata(v_env):
    client, chain, _ = v_env
    login_verifier(client)
    reference = "AT-NO-BACKFILL"
    original = make_test_pdf(reference, "Alice", "Physics")
    submitted = make_test_pdf(reference, "", "Physics")
    digest = hashlib.sha256(original).hexdigest()
    chain.records[reference] = {
        "file_hash": digest, "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000, "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference,issuer_id,file_hash,transaction_hash,metadata) VALUES(?,2,?,'0xtest',?)",
            (reference, digest, json.dumps({"recipient_name": "Alice", "course": "Physics"})),
        )
    response = client.post("/api/verify", files={"file": ("missing-name.pdf", submitted)})
    assert response.status_code == 200
    result = response.json()
    assert not result["fields"].get("name")
    assert result["hash_matches"] is False
    assert result["field_analysis"]["status"] == "unavailable"
    assert result["review_routing"]["requires_human_review"] is True

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
    assert data["visual_tampering"]["status"] == "not_required"
    assert data["visual_tampering"]["regions"] == []
    assert data["review_routing"]["calibrated_confidence"] is None
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

# 11. EXACT HASH MATCH WITH CONFLICTING SUPPLIED REFERENCE
def test_exact_hash_match_with_conflicting_supplied_reference(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    cert_bytes = make_test_pdf("AT-2026-BOUND", "Carol Danvers", "Aerospace Engineering")
    digest = hashlib.sha256(cert_bytes).hexdigest()

    chain.records["AT-2026-BOUND"] = {
        "file_hash": digest,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-2026-BOUND", digest, 2, "0x1111", "2026-01-15T00:00:00Z")
        )

    res = client.post(
        "/api/verify",
        files={"file": ("cert.pdf", cert_bytes)},
        data={"reference": "AT-2026-CONFLICTING"}
    )
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "VERIFIED"
    assert data["hash_matches"] is True
    assert data["hash_comparison_result"] == "MATCH"
    assert data["reference"] == "AT-2026-BOUND"
    assert any("conflicts with registered certificate ID" in w for w in data["warnings"])

# 12. HASH MISMATCH WITHOUT SUFFICIENT EVIDENCE IS NOT TAMPERED
def test_hash_mismatch_without_sufficient_evidence_not_tampered(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-2026-NOEVID", "David Copper", "Stage Magic")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()

    chain.records["AT-2026-NOEVID"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-2026-NOEVID", orig_hash, 2, "0x2222", "2026-01-15T00:00:00Z")
        )

    modified_bytes = make_test_pdf("AT-2026-NOEVID", "David Copper", "Stage Magic", extra_text="Re-saved copy")
    mod_hash = hashlib.sha256(modified_bytes).hexdigest()
    assert mod_hash != orig_hash

    res = client.post("/api/verify", files={"file": ("cert.pdf", modified_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
    assert data["verification_status"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
    assert data["hash_matches"] is False
    assert data["hash_comparison_result"] == "MISMATCH"
    assert "file bytes differ" in data["hash_comparison"].lower()
    assert "tampered" not in data["verification_status"].lower()
    assert "re-saving" in data["message"].lower() or "re-exporting" in data["message"].lower() or "compression" in data["message"].lower()

# 13. HASH MISMATCH WITH VERIFIED METADATA COMMITMENT CONFIRMS TAMPERING
def test_hash_mismatch_with_verified_metadata_commitment_confirms_tampering(v_env):
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from backend.fields import compute_metadata_commitment

    client, chain, _ = v_env
    login_verifier(client)

    signer = Account.from_key("02" * 32)
    chain.approved_issuers[signer.address.lower()] = True

    orig_pdf = make_test_pdf("AT-2026-TAMPER", "Alice Smith", "Data Science")
    orig_hash = hashlib.sha256(orig_pdf).hexdigest()

    confirmed = {"recipient_name": "Alice Smith", "course": "Data Science", "reference": "AT-2026-TAMPER"}
    comm = compute_metadata_commitment(confirmed, "AT-2026-TAMPER", orig_hash)
    sig = Account.sign_message(encode_defunct(hexstr=comm), signer.key).signature.hex()

    chain.records["AT-2026-TAMPER"] = {
        "file_hash": orig_hash,
        "issuer": signer.address,
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(email, name, password, role, wallet, approval_status) VALUES(?,?,?,?,?,?)",
            ("trusted_signer@authentra.demo", "Trusted Signer", "hash", "institution", signer.address, "APPROVED")
        )
        user_row = conn.execute("SELECT id FROM users WHERE lower(wallet)=lower(?)", (signer.address.lower(),)).fetchone()
        issuer_user_id = user_row["id"]
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, issuer_signature, registered_at) VALUES(?,?,?,?,?,?,?,?)",
            ("AT-2026-TAMPER", orig_hash, issuer_user_id, "0x3333", json.dumps(confirmed), comm, sig, "2026-01-15T00:00:00Z")
        )

    # Verifier uploads tampered certificate with changed name
    tampered_pdf = make_test_pdf("AT-2026-TAMPER", "Bob Smith", "Data Science")
    res = client.post("/api/verify", files={"file": ("tampered.pdf", tampered_pdf)})
    assert res.status_code == 200
    data = res.json()

    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["field_analysis"]["commitment_verified"] is True
    assert data["field_analysis"]["critical_field_changed"] is True
    assert "unauthorized change" in data["message"].lower() or "protected certificate data differs" in data["message"].lower()

# 14. CONFLICTING SUPPLIED AND EXTRACTED REFERENCE RETURNS INCONCLUSIVE
def test_conflicting_supplied_and_extracted_reference_returns_inconclusive(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    cert_bytes = make_test_pdf("AT-2026-EXTRACTED", "Eve Adams", "Cybersecurity")

    res = client.post(
        "/api/verify",
        files={"file": ("cert.pdf", cert_bytes)},
        data={"reference": "AT-2026-DIFFERENT"}
    )
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "NOT_REGISTERED_OR_INCONCLUSIVE"
    assert data["verification_status"] == "INCONCLUSIVE"
    assert data["reference"] is None
    assert data["hash_matches"] is None
    assert any("conflicting certificate identifiers" in w.lower() for w in data["warnings"])

# 15. MISSING REGISTRATION TREATED AS INCONCLUSIVE NOT TAMPERING
def test_missing_registration_treated_as_inconclusive_not_tampering(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    cert_bytes = make_test_pdf("AT-NOT-FOUND-999", "Unknown Student", "Ancient History")
    res = client.post("/api/verify", files={"file": ("cert.pdf", cert_bytes)})
    assert res.status_code == 200
    data = res.json()

    assert data["category"] == "NOT_REGISTERED_OR_INCONCLUSIVE"
    assert data["verification_status"] in ("NOT_REGISTERED", "INCONCLUSIVE")
    assert data["hash_matches"] is None
    assert "tamper" not in data["message"].lower()
    assert "does not prove that the document is forged" in data["message"].lower()
    assert "no registration exists" in data["message"].lower()

# 16. USER FACING HASH COMPARISON WORDING
def test_user_facing_hash_comparison_wording(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    # 1. Exact match wording
    exact_pdf = make_test_pdf("AT-2026-WORDING", "Frank Miller", "Graphic Arts")
    exact_hash = hashlib.sha256(exact_pdf).hexdigest()
    chain.records["AT-2026-WORDING"] = {
        "file_hash": exact_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-2026-WORDING", exact_hash, 2, "0x4444", "2026-01-15T00:00:00Z")
        )

    res_exact = client.post("/api/verify", files={"file": ("cert.pdf", exact_pdf)})
    assert res_exact.json()["hash_comparison"] == "Exact match between uploaded file hash and registered on-chain hash"
    assert res_exact.json()["hash_comparison_result"] == "MATCH"

    # 2. Mismatch wording (file bytes differ, not claimed tampered)
    resaved_pdf = make_test_pdf("AT-2026-WORDING", "Frank Miller", "Graphic Arts", extra_text="Re-saved copy")
    res_mismatch = client.post("/api/verify", files={"file": ("cert.pdf", resaved_pdf)})
    assert res_mismatch.json()["hash_comparison"] == "Uploaded file hash differs from registered on-chain hash (file bytes differ)"
    assert res_mismatch.json()["hash_comparison_result"] == "MISMATCH"

    # 3. Not registered wording
    unreg_pdf = make_test_pdf("AT-2026-UNREG", "Frank Miller", "Graphic Arts")
    res_unreg = client.post("/api/verify", files={"file": ("cert.pdf", unreg_pdf)})
    assert res_unreg.json()["hash_comparison"] == "No registered hash available for comparison"
    assert res_unreg.json()["hash_comparison_result"] == "NOT_COMPARED"


# ==============================================================================
# 14 REQUIRED TEST SCENARIOS IMPLEMENTATION
# ==============================================================================

# Scenario 1: Original registered certificate uploaded with Certificate ID -> GENUINE
def test_scenario_1_original_with_certificate_id_genuine(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    cert_bytes = make_test_pdf("AT-SCENARIO-1", "Alice Wonder", "Quantum Computing", "2026-02-10")
    file_hash = hashlib.sha256(cert_bytes).hexdigest()
    chain.records["AT-SCENARIO-1"] = {
        "file_hash": file_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-SCENARIO-1", file_hash, 2, "0x1111", "2026-02-10T00:00:00Z")
        )

    res = client.post(
        "/api/verify",
        files={"file": ("cert1.pdf", cert_bytes)},
        data={"reference": "AT-SCENARIO-1"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "VERIFIED"
    assert data["status"] == "verified"
    assert data["hash_matches"] is True
    assert data["hash_comparison_result"] == "MATCH"
    assert data["reference"] == "AT-SCENARIO-1"


# Scenario 2: Original registered certificate uploaded without Certificate ID -> GENUINE
def test_scenario_2_original_without_certificate_id_genuine(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    cert_bytes = make_test_pdf("AT-SCENARIO-2", "Bob Builder", "Civil Engineering", "2026-02-12")
    file_hash = hashlib.sha256(cert_bytes).hexdigest()
    chain.records["AT-SCENARIO-2"] = {
        "file_hash": file_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-SCENARIO-2", file_hash, 2, "0x2222", "2026-02-12T00:00:00Z")
        )

    # Upload WITHOUT reference
    res = client.post(
        "/api/verify",
        files={"file": ("cert2.pdf", cert_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "VERIFIED"
    assert data["status"] == "verified"
    assert data["hash_matches"] is True
    assert data["hash_comparison_result"] == "MATCH"
    assert data["reference"] == "AT-SCENARIO-2"
    assert data["matching_status"] in ("EXACT_HASH_MATCH", "AUTOMATIC_METADATA_MATCH")


# Scenario 3: Same registered certificate with modified recipient name and no Certificate ID -> TAMPERED
def test_scenario_3_modified_recipient_name_without_id_tampered(v_env):
    from backend.fields import compute_metadata_commitment
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-3", "Charlie Original", "Robotics", "2026-02-15")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    meta = {
        "recipient_name": "Charlie Original",
        "course": "Robotics",
        "certificate_reference": "AT-SCENARIO-3",
        "issue_date": "2026-02-15",
        "institution_name": "Meridian Institute of Technology",
    }
    comm = compute_metadata_commitment(meta, "AT-SCENARIO-3", orig_hash)

    chain.records["AT-SCENARIO-3"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, registered_at) VALUES(?,?,?,?,?,?,?)",
            ("AT-SCENARIO-3", orig_hash, 2, "0x3333", json.dumps(meta), comm, "2026-02-15T00:00:00Z")
        )

    # Verifier uploads certificate with modified name, leaving Certificate ID empty
    tampered_bytes = make_test_pdf("AT-SCENARIO-3", "Mallory Imposter", "Robotics", "2026-02-15")
    res = client.post(
        "/api/verify",
        files={"file": ("tampered_name.pdf", tampered_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["status"] == "tampering_detected"
    assert data["hash_matches"] is False
    assert data["hash_comparison_result"] == "MISMATCH"
    assert data["original_reference"] == "AT-SCENARIO-3"
    assert len(data["modified_fields"]) > 0
    name_mod = next((mf for mf in data["modified_fields"] if mf["field"] in ("recipient_name", "name")), None)
    assert name_mod is not None
    assert name_mod["original_value"] == "Charlie Original"
    assert name_mod["uploaded_value"] == "Mallory Imposter"


# Scenario 4: Same registered certificate with modified date and no Certificate ID -> TAMPERED
def test_scenario_4_modified_date_without_id_tampered(v_env):
    from backend.fields import compute_metadata_commitment
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-4", "Diana Prince", "Security Analysis", "2025-06-01")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    meta = {
        "recipient_name": "Diana Prince",
        "course": "Security Analysis",
        "certificate_reference": "AT-SCENARIO-4",
        "issue_date": "2025-06-01",
        "institution_name": "Meridian Institute of Technology",
    }
    comm = compute_metadata_commitment(meta, "AT-SCENARIO-4", orig_hash)

    chain.records["AT-SCENARIO-4"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, registered_at) VALUES(?,?,?,?,?,?,?)",
            ("AT-SCENARIO-4", orig_hash, 2, "0x4444", json.dumps(meta), comm, "2025-06-01T00:00:00Z")
        )

    # Upload with altered date, without Certificate ID
    tampered_bytes = make_test_pdf("AT-SCENARIO-4", "Diana Prince", "Security Analysis", "2026-11-20")
    res = client.post(
        "/api/verify",
        files={"file": ("tampered_date.pdf", tampered_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["status"] == "tampering_detected"
    assert data["hash_matches"] is False
    assert data["original_reference"] == "AT-SCENARIO-4"
    date_mod = next((mf for mf in data["modified_fields"] if mf["field"] in ("issue_date", "date")), None)
    assert date_mod is not None
    assert "2025-06-01" in date_mod["original_value"]
    assert "2026-11-20" in date_mod["uploaded_value"]


# Scenario 5: Same registered certificate with modified award title and no Certificate ID -> TAMPERED
def test_scenario_5_modified_award_title_without_id_tampered(v_env):
    from backend.fields import compute_metadata_commitment
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-5", "Edward Norton", "Introduction to AI", "2026-03-01")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    meta = {
        "recipient_name": "Edward Norton",
        "course": "Introduction to AI",
        "certificate_reference": "AT-SCENARIO-5",
        "issue_date": "2026-03-01",
        "institution_name": "Meridian Institute of Technology",
    }
    comm = compute_metadata_commitment(meta, "AT-SCENARIO-5", orig_hash)

    chain.records["AT-SCENARIO-5"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, registered_at) VALUES(?,?,?,?,?,?,?)",
            ("AT-SCENARIO-5", orig_hash, 2, "0x5555", json.dumps(meta), comm, "2026-03-01T00:00:00Z")
        )

    # Upload with modified course / award title
    tampered_bytes = make_test_pdf("AT-SCENARIO-5", "Edward Norton", "Advanced Ph.D. in Artificial Superintelligence", "2026-03-01")
    res = client.post(
        "/api/verify",
        files={"file": ("tampered_title.pdf", tampered_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["status"] == "tampering_detected"
    assert data["hash_matches"] is False
    assert data["original_reference"] == "AT-SCENARIO-5"
    course_mod = next((mf for mf in data["modified_fields"] if mf["field"] in ("course", "qualification", "award")), None)
    assert course_mod is not None
    assert course_mod["original_value"] == "Introduction to AI"
    assert "Superintelligence" in course_mod["uploaded_value"]


# Scenario 6: Same registered certificate with modified marks or grades and no Certificate ID -> TAMPERED
def test_scenario_6_modified_marks_grades_without_id_tampered(v_env):
    from backend.fields import compute_metadata_commitment
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-6", "Fiona Gallagher", "Finance", "2026-03-05", grade="Pass")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    meta = {
        "recipient_name": "Fiona Gallagher",
        "course": "Finance",
        "certificate_reference": "AT-SCENARIO-6",
        "issue_date": "2026-03-05",
        "institution_name": "Meridian Institute of Technology",
        "grade": "Pass",
    }
    comm = compute_metadata_commitment(meta, "AT-SCENARIO-6", orig_hash)

    chain.records["AT-SCENARIO-6"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, registered_at) VALUES(?,?,?,?,?,?,?)",
            ("AT-SCENARIO-6", orig_hash, 2, "0x6666", json.dumps(meta), comm, "2026-03-05T00:00:00Z")
        )

    # Upload with modified grade: "First Class Honours"
    tampered_bytes = make_test_pdf("AT-SCENARIO-6", "Fiona Gallagher", "Finance", "2026-03-05", grade="First Class Honours")
    res = client.post(
        "/api/verify",
        files={"file": ("tampered_grade.pdf", tampered_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["status"] == "tampering_detected"
    assert data["hash_matches"] is False
    assert data["original_reference"] == "AT-SCENARIO-6"
    grade_mod = next((mf for mf in data["modified_fields"] if mf["field"] in ("grade", "result", "marks")), None)
    assert grade_mod is not None
    assert grade_mod["original_value"] == "Pass"
    assert "First Class" in grade_mod["uploaded_value"]


# Scenario 7: Same registered certificate with modified signature or seal -> TAMPERED when reliably detected
def test_scenario_7_modified_signature_seal_tampered(v_env, monkeypatch):
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-7", "George Clark", "Art History", "2026-03-10")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    chain.records["AT-SCENARIO-7"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, registered_at) VALUES(?,?,?,?,?)",
            ("AT-SCENARIO-7", orig_hash, 2, "0x7777", "2026-03-10T00:00:00Z")
        )

    def mock_visual(*args, **kwargs):
        return {
            "status": "suspicious_regions_detected",
            "page": 1,
            "analyzed_page": 1,
            "regions": [{
                "box": [0.7, 0.8, 0.2, 0.15],
                "confidence": 0.95,
                "score": 0.95,
                "type": "model_anomaly",
                "explanation": "Visual anomaly detected in institutional seal and signature block.",
                "page": 1
            }],
            "suspicious_regions": [{
                "box": [0.7, 0.8, 0.2, 0.15],
                "confidence": 0.95,
                "score": 0.95,
                "type": "model_anomaly",
                "explanation": "Visual anomaly detected in institutional seal and signature block.",
                "page": 1
            }],
            "anomaly_score": 0.95,
            "accessible_description": "Visual anomaly detected in institutional seal and signature block.",
        }

    from backend import main as main_module
    monkeypatch.setattr(main_module, "analyze_visual_tampering", mock_visual)

    resaved_bytes = make_test_pdf("AT-SCENARIO-7", "George Clark", "Art History", "2026-03-10", extra_text="Modified seal graphic")
    res = client.post(
        "/api/verify",
        files={"file": ("tampered_seal.pdf", resaved_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "TAMPERING_DETECTED"
    assert data["status"] == "tampering_detected"
    assert data["hash_matches"] is False
    assert any("visual" in mf["field"] or "signature" in mf["field"] or "seal" in mf["field"] for mf in data["modified_fields"])


# Scenario 8: Readable certificate with no registered matching record -> UNREGISTERED / NOT VERIFIED
def test_scenario_8_readable_no_matching_record_unregistered(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    unreg_bytes = make_test_pdf("AT-SCENARIO-8-UNREG", "Harry Potter", "Defense Against Dark Arts", "2026-03-12", institution="Hogwarts School")
    res = client.post(
        "/api/verify",
        files={"file": ("unregistered.pdf", unreg_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "NOT_REGISTERED"
    assert data["status"] == "not_registered"
    assert data["label"] == "Unregistered / Not Verified"
    assert "No matching registered certificate was found in the AuthenTra database. Authenticity could not be established." in data["message"]
    assert "tamper" not in data["verification_status"].lower()


# Scenario 9: Corrupted or unreadable certificate -> INCONCLUSIVE
def test_scenario_9_corrupted_or_unreadable_inconclusive(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    corrupt_bytes = b"NotAValidPDFOrImageContentAtAll"
    res = client.post("/api/verify", files={"file": ("broken.pdf", corrupt_bytes)})
    assert res.status_code == 200
    data = res.json()
    assert data["category"] in ("INVALID_FILE", "INCONCLUSIVE")

    pdf_corrupt = b"%PDF-1.4\n" + b"\x00\xFF" * 100
    res2 = client.post("/api/verify", files={"file": ("corrupt.pdf", pdf_corrupt)})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["verification_status"] in ("INCONCLUSIVE", "INVALID_FILE")


# Scenario 10: Certificate with no usable identity fields -> INCONCLUSIVE
def test_scenario_10_no_usable_identity_fields_inconclusive(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    stream = io.BytesIO()
    c = canvas.Canvas(stream)
    c.drawString(100, 100, "Page 1 of 1")
    c.save()
    blank_bytes = stream.getvalue()

    res = client.post(
        "/api/verify",
        files={"file": ("blank.pdf", blank_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "INCONCLUSIVE"
    assert data["status"] == "inconclusive"
    assert "usable" in data["message"].lower() or "readable" in data["message"].lower() or "identity" in data["message"].lower()


# Scenario 11: Certificate with multiple possible registered matches -> MANUAL REVIEW REQUIRED
def test_scenario_11_multiple_possible_registered_matches_manual_review(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    c1 = make_test_pdf("AT-DUP-001", "Ian Duplicate", "Statistics", "2026-03-20")
    h1 = hashlib.sha256(c1).hexdigest()
    chain.records["AT-DUP-001"] = {"file_hash": h1, "issuer": "0x0000000000000000000000000000000000000002", "registered_at": 1700000000, "revoked": False}

    c2 = make_test_pdf("AT-DUP-002", "Ian Duplicate", "Statistics", "2026-03-20")
    h2 = hashlib.sha256(c2).hexdigest()
    chain.records["AT-DUP-002"] = {"file_hash": h2, "issuer": "0x0000000000000000000000000000000000000002", "registered_at": 1700000000, "revoked": False}

    meta = json.dumps({"recipient_name": "Ian Duplicate", "course": "Statistics", "issue_date": "2026-03-20", "institution_name": "Meridian Institute of Technology"})
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata) VALUES(?,?,?,? ,?)", ("AT-DUP-001", h1, 2, "0xdup1", meta))
        conn.execute("INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata) VALUES(?,?,?,? ,?)", ("AT-DUP-002", h2, 2, "0xdup2", meta))

    ambig_pdf = make_test_pdf(reference="", name="Ian Duplicate", course="Statistics", date_str="2026-03-20")
    res = client.post(
        "/api/verify",
        files={"file": ("ambig.pdf", ambig_pdf)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "MANUAL_REVIEW_REQUIRED"
    assert data["status"] == "manual_review_required"
    assert data["label"] == "Manual Review Required"
    assert "multiple" in data["message"].lower() or "manual review" in data["message"].lower()


# Scenario 12: Certificate with only PDF metadata changes and unchanged certificate content -> INTEGRITY MISMATCH / CONTENT UNCHANGED
def test_scenario_12_metadata_change_only_integrity_mismatch_content_unchanged(v_env):
    from backend.fields import compute_metadata_commitment
    client, chain, _ = v_env
    login_verifier(client)

    orig_bytes = make_test_pdf("AT-SCENARIO-12", "Julia Unaltered", "Software Architecture", "2026-03-25")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    meta = {
        "recipient_name": "Julia Unaltered",
        "course": "Software Architecture",
        "certificate_reference": "AT-SCENARIO-12",
        "issue_date": "2026-03-25",
        "institution_name": "Meridian Institute of Technology",
    }
    comm = compute_metadata_commitment(meta, "AT-SCENARIO-12", orig_hash)

    chain.records["AT-SCENARIO-12"] = {
        "file_hash": orig_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata, metadata_commitment, registered_at) VALUES(?,?,?,?,?,?,?)",
            ("AT-SCENARIO-12", orig_hash, 2, "0x1212", json.dumps(meta), comm, "2026-03-25T00:00:00Z")
        )

    reexported_bytes = make_test_pdf("AT-SCENARIO-12", "Julia Unaltered", "Software Architecture", "2026-03-25", extra_text="Re-saved digital copy")
    res = client.post(
        "/api/verify",
        files={"file": ("reexported.pdf", reexported_bytes)},
        data={"reference": ""}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
    assert data["label"] == "File Integrity Mismatch (Content Unchanged)"
    assert data["hash_matches"] is False
    assert len(data.get("modified_fields", [])) == 0


# Scenario 13: Registered certificate confirmed as revoked -> REVOKED
def test_scenario_13_confirmed_revoked_certificate(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    pdf_bytes = make_test_pdf("AT-SCENARIO-13", "Kevin Revoked", "Ethics in Computing", "2026-03-28")
    h = hashlib.sha256(pdf_bytes).hexdigest()
    chain.records["AT-SCENARIO-13"] = {
        "file_hash": h,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": True,
    }
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash) VALUES('AT-SCENARIO-13', ?, 2, '0xrev13')", (h,))

    res = client.post("/api/verify", files={"file": ("revoked.pdf", pdf_bytes)}, data={"reference": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "REVOKED"
    assert data["status"] == "revoked"
    assert data["label"] == "Revoked"
    assert "revoked" in data["message"].lower()
    assert data["checks"]["active"] is False


# Scenario 14: Registered certificate beyond its trusted validity period -> EXPIRED
def test_scenario_14_certificate_beyond_trusted_validity_period_expired(v_env):
    client, chain, _ = v_env
    login_verifier(client)

    pdf_bytes = make_test_pdf("AT-SCENARIO-14", "Laura Expired", "First Aid Certificate", "2019-01-01")
    h = hashlib.sha256(pdf_bytes).hexdigest()
    meta = {
        "recipient_name": "Laura Expired",
        "course": "First Aid Certificate",
        "certificate_reference": "AT-SCENARIO-14",
        "issue_date": "2019-01-01",
        "expiry_date": "2020-01-01",
    }
    chain.records["AT-SCENARIO-14"] = {
        "file_hash": h,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1546300800,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO registrations(reference, file_hash, issuer_id, transaction_hash, confirmed_metadata) VALUES(?,?,?,?,?)",
            ("AT-SCENARIO-14", h, 2, "0xexp14", json.dumps(meta))
        )

    res = client.post("/api/verify", files={"file": ("expired.pdf", pdf_bytes)}, data={"reference": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["verification_status"] == "EXPIRED"
    assert data["status"] == "expired"
    assert data["label"] == "Expired"
    assert "validity period" in data["message"].lower() or "expired" in data["message"].lower()
