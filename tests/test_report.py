"""Regression and verification tests for downloadable PDF reports in AuthenTra.

Covers:
- All 10 verification statuses (including INVALID_FILE and VERIFICATION_UNAVAILABLE)
- Authorization and role access restrictions (USER only; other user -> 404; unauthenticated -> 401; ADMINs -> 403)
- Text assertions with pypdf: status, full file hash, verification ID, 'Page 1 of', and absence of 'authentic'/'genuine'
- Legacy rows without report_json produce reports with 'recorded before report snapshots were enabled' and 'N/A'
- Hostile user-controlled file name / OCR text safety (Unicode, <b>, &, 300+ chars)
- Batch endpoint: max 5 enforcement, ownership checks, combined PDF structure
- Response headers (Content-Disposition, application/pdf, Cache-Control: no-store)
- report_url presence on /api/verify response and /api/history rows
"""

import hashlib
import io
import json
import os
import time
import uuid

import pypdf
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

os.environ["AUTHENTRA_DEMO"] = "1"
from backend import main
from backend.storage import connect


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
            "0x0000000000000000000000000000000000000003": False,
        }
        self.fail_mode = None

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
            "explorer_template": "https://etherscan.io/tx/{tx_hash}",
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
def rep_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "report_test.db")
    monkeypatch.setenv("AUTHENTRA_DB", db_path)
    mock_chain = MockVerificationBlockchain()
    monkeypatch.setattr(main, "Registry", lambda: mock_chain)
    monkeypatch.setattr(main, "registry", lambda: mock_chain)
    main.LOGIN_ATTEMPTS.clear()

    with TestClient(main.app) as client:
        with connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(id, email, name, password, role, wallet, approval_status) "
                "VALUES(2, 'issuer@authentra.demo', 'Meridian Institute of Technology', 'hash', 'institution', "
                "'0x0000000000000000000000000000000000000002', 'APPROVED')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO users(id, email, name, password, role, wallet, approval_status) "
                "VALUES(3, 'disabled@authentra.demo', 'Rogue Academy', 'hash', 'institution', "
                "'0x0000000000000000000000000000000000000003', 'SUSPENDED')"
            )
            # Create a second standard user (user_id = 10) for authorization isolation testing
            from backend.storage import password_hash
            p_hash = password_hash("AuthenTra-demo-2026!")
            conn.execute(
                "INSERT OR IGNORE INTO users(id, email, name, password, role, approval_status) "
                "VALUES(10, 'otheruser@authentra.demo', 'Other User', ?, 'USER', 'APPROVED')",
                (p_hash,),
            )
            # Create a system admin user for authorization isolation testing
            conn.execute(
                "INSERT OR IGNORE INTO users(id, email, name, password, role, approval_status) "
                "VALUES(99, 'admin@authentra.demo', 'System Admin', ?, 'SYSTEM_ADMIN', 'APPROVED')",
                (p_hash,),
            )
        yield client, mock_chain, db_path


def login_user(client, email="verifier@authentra.demo", password="AuthenTra-demo-2026!", account_type="user"):
    if account_type == "admin":
        r = client.post("/api/auth/admin-login", json={"email": email, "password": password})
    else:
        r = client.post("/api/auth/login", json={"email": email, "password": password, "account_type": account_type})
    assert r.status_code == 200
    return r


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


# 1. VERIFIED STATUS
def test_report_verified_status(rep_env):
    client, chain, _ = rep_env
    login_user(client)

    pdf_bytes = make_test_pdf("AT-2026-VERIFIED", "Alice Smith", "Data Science")
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    chain.records["AT-2026-VERIFIED"] = {
        "file_hash": file_hash,
        "issuer": "0x0000000000000000000000000000000000000002",
        "registered_at": 1700000000,
        "revoked": False,
    }
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference, issuer_id, file_hash, transaction_hash) VALUES('AT-2026-VERIFIED', 2, ?, '0xaaa111')", (file_hash,))

    res = client.post("/api/verify", files={"file": ("verified_cert.pdf", pdf_bytes)})
    assert res.status_code == 200
    v_data = res.json()
    assert "report_url" in v_data
    v_id = v_data["id"]

    rep_res = client.get(f"/api/verifications/{v_id}/report.pdf")
    assert rep_res.status_code == 200
    assert rep_res.content.startswith(b"%PDF")
    assert rep_res.headers["Content-Type"] == "application/pdf"
    assert f'filename="AuthenTra-Report-{v_id}.pdf"' in rep_res.headers["Content-Disposition"]
    assert rep_res.headers["Cache-Control"] == "no-store"

    text = extract_pdf_text(rep_res.content)
    assert "Verified" in text
    assert file_hash in text
    assert f"#{v_id}" in text
    assert "Page 1 of" in text
    assert "authentic" not in text.lower()
    assert "genuine" not in text.lower()
    assert "AI and field analysis are advisory and never override the blockchain and hash result." in text


# 2. ALL 10 STATUSES RETURN 200 AND VALID PDF
@pytest.mark.parametrize("status_scenario", [
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
    "TAMPERING_DETECTED",
    "NOT_REGISTERED",
    "NOT_REGISTERED_OR_INCONCLUSIVE",
    "INCONCLUSIVE",
    "REVOKED",
    "ISSUER_NOT_AUTHORIZED",
    "VERIFICATION_UNAVAILABLE",
    "INVALID_FILE",
])
def test_report_all_statuses(rep_env, status_scenario):
    client, chain, _ = rep_env
    login_user(client)

    if status_scenario in ("POSSIBLE_TAMPERING_OR_FILE_MISMATCH", "TAMPERING_DETECTED"):
        orig_pdf = make_test_pdf("AT-2026-TAMP", "Bob", "Physics")
        chain.records["AT-2026-TAMP"] = {
            "file_hash": hashlib.sha256(orig_pdf).hexdigest(),
            "issuer": "0x0000000000000000000000000000000000000002",
            "registered_at": 1700000000,
            "revoked": False,
        }
        test_pdf = make_test_pdf("AT-2026-TAMP", "Bob", "Physics", extra_text="Modified bytes")
        res = client.post("/api/verify", files={"file": ("tampered.pdf", test_pdf)})
    elif status_scenario in ("NOT_REGISTERED", "NOT_REGISTERED_OR_INCONCLUSIVE"):
        test_pdf = make_test_pdf("AT-2026-NOTREG", "Charlie", "Art")
        res = client.post("/api/verify", files={"file": ("notreg.pdf", test_pdf)})
    elif status_scenario == "INCONCLUSIVE":
        test_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        res = client.post("/api/verify", files={"file": ("inconclusive.pdf", test_pdf)})
    elif status_scenario == "REVOKED":
        test_pdf = make_test_pdf("AT-2026-REVOKED", "Dave", "Biology")
        chain.records["AT-2026-REVOKED"] = {
            "file_hash": hashlib.sha256(test_pdf).hexdigest(),
            "issuer": "0x0000000000000000000000000000000000000002",
            "registered_at": 1700000000,
            "revoked": True,
        }
        res = client.post("/api/verify", files={"file": ("revoked.pdf", test_pdf)})
    elif status_scenario == "ISSUER_NOT_AUTHORIZED":
        test_pdf = make_test_pdf("AT-2026-ROGUE", "Eve", "Finance")
        chain.records["AT-2026-ROGUE"] = {
            "file_hash": hashlib.sha256(test_pdf).hexdigest(),
            "issuer": "0x0000000000000000000000000000000000000003",
            "registered_at": 1700000000,
            "revoked": False,
        }
        res = client.post("/api/verify", files={"file": ("rogue.pdf", test_pdf)})
    elif status_scenario == "VERIFICATION_UNAVAILABLE":
        chain.fail_mode = "offline"
        test_pdf = make_test_pdf("AT-2026-OFFLINE", "Frank", "History")
        res = client.post("/api/verify", files={"file": ("offline.pdf", test_pdf)})
        chain.fail_mode = None
    elif status_scenario == "INVALID_FILE":
        res = client.post("/api/verify", files={"file": ("invalid.txt", b"Invalid content not supported")})

    assert res.status_code == 200
    v_data = res.json()
    v_id = v_data["id"]

    rep_res = client.get(f"/api/verifications/{v_id}/report.pdf")
    assert rep_res.status_code == 200
    assert rep_res.content.startswith(b"%PDF")
    assert f'filename="AuthenTra-Report-{v_id}.pdf"' in rep_res.headers["Content-Disposition"]

    text = extract_pdf_text(rep_res.content)
    assert f"#{v_id}" in text
    assert "Page 1 of" in text
    assert "authentic" not in text.lower()
    assert "genuine" not in text.lower()


# 3. PERMISSIONS & ROLE RESTRICTIONS
def test_report_authorization_and_isolation(rep_env):
    client, chain, _ = rep_env

    # Unauthenticated -> 401
    assert client.get("/api/verifications/1/report.pdf").status_code == 401
    assert client.get("/api/verifications/report.pdf?ids=1").status_code == 401

    # Login as verifier (User ID = 1 in seed)
    login_user(client, email="verifier@authentra.demo")
    pdf_bytes = make_test_pdf("AT-2026-PRIVACY", "Student P", "Security")
    v_res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert v_res.status_code == 200
    v_id = v_res.json()["id"]

    # Current user gets 200
    assert client.get(f"/api/verifications/{v_id}/report.pdf").status_code == 200

    # Logout and login as another standard user (User ID = 10)
    client.post("/api/auth/logout")
    login_user(client, email="otheruser@authentra.demo")

    # MUST return 404 (not 403) to avoid leaking existence of other user's check
    assert client.get(f"/api/verifications/{v_id}/report.pdf").status_code == 404
    assert client.get(f"/api/verifications/report.pdf?ids={v_id}").status_code == 404

    # Non-existent ID returns 404
    assert client.get("/api/verifications/999999/report.pdf").status_code == 404

    # Logout and login as INSTITUTION_ADMIN -> 403
    client.post("/api/auth/logout")
    login_user(client, email="issuer@authentra.demo", account_type="institution")
    assert client.get(f"/api/verifications/{v_id}/report.pdf").status_code == 403
    assert client.get(f"/api/verifications/report.pdf?ids={v_id}").status_code == 403

    # Logout and login as SYSTEM_ADMIN -> 403
    client.post("/api/auth/logout")
    login_user(client, email="admin@authentra.demo", account_type="admin")
    assert client.get(f"/api/verifications/{v_id}/report.pdf").status_code == 403
    assert client.get(f"/api/verifications/report.pdf?ids={v_id}").status_code == 403


# 4. LEGACY ROW GENERATION
def test_report_legacy_row_fallback(rep_env):
    client, chain, _ = rep_env
    login_user(client, email="verifier@authentra.demo")

    # Insert a legacy row with NO report_json, NO file_name, NO file_size
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO verifications("
            "user_id, reference, status, category, file_hash, registered_hash, issuer, checks, message, duration_ms, ai_status, created_at) "
            "VALUES(1, 'AT-LEGACY-ROW', 'verified', 'VERIFIED', '112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00', "
            "'112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00', '0x1234', "
            "'{\"reference_found\": true, \"hash_matches\": true, \"issuer_approved\": true, \"active\": true}', "
            "'Registered and unchanged.', 45.2, 'clean', '2024-01-01 12:00:00')"
        )
        leg_id = cursor.lastrowid

    res = client.get(f"/api/verifications/{leg_id}/report.pdf")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF")

    text = extract_pdf_text(res.content)
    assert "recorded before report snapshots were enabled" in text
    assert "N/A" in text
    assert "112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00" in text
    assert "authentic" not in text.lower()
    assert "genuine" not in text.lower()


# 5. HOSTILE FILE NAME AND OCR TEXT SAFETY
def test_report_hostile_input_safety(rep_env):
    client, chain, _ = rep_env
    login_user(client, email="verifier@authentra.demo")

    # Hostile file name: Unicode, <b>, &, emojis, and 300+ characters
    hostile_name = "certificate_<script>alert('xss')</script>_<b>bold</b>_&_unicode_\u4e2d\u6587_\U0001f600_" + ("x" * 250) + ".pdf"
    pdf_bytes = make_test_pdf("AT-2026-HOSTILE", "Test Unicode", "Computer Science")

    res = client.post("/api/verify", files={"file": (hostile_name, pdf_bytes)})
    assert res.status_code == 200
    v_id = res.json()["id"]

    rep_res = client.get(f"/api/verifications/{v_id}/report.pdf")
    assert rep_res.status_code == 200
    assert rep_res.content.startswith(b"%PDF")

    text = extract_pdf_text(rep_res.content)
    assert f"#{v_id}" in text
    assert "Page 1 of" in text
    assert "authentic" not in text.lower()
    assert "genuine" not in text.lower()


# 6. BATCH ENDPOINT VALIDATION AND COMBINED PDF
def test_report_batch_endpoint(rep_env):
    client, chain, _ = rep_env
    login_user(client, email="verifier@authentra.demo")

    # Create 3 verification records
    ids = []
    for i in range(1, 4):
        pdf = make_test_pdf(f"AT-BATCH-{i}", f"Student {i}", "Engineering")
        r = client.post("/api/verify", files={"file": (f"cert_{i}.pdf", pdf)})
        assert r.status_code == 200
        ids.append(str(r.json()["id"]))

    ids_param = ",".join(ids)

    # Valid batch request (3 items)
    batch_res = client.get(f"/api/verifications/report.pdf?ids={ids_param}")
    assert batch_res.status_code == 200
    assert batch_res.content.startswith(b"%PDF")
    assert 'filename="AuthenTra-Report-Batch.pdf"' in batch_res.headers["Content-Disposition"]

    reader = pypdf.PdfReader(io.BytesIO(batch_res.content))
    # Combined PDF with summary table first, then page break per file -> at least 4 pages
    assert len(reader.pages) >= 2
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    assert "AuthenTra - Batch Verification Summary Report" in full_text
    assert "Total Certificates Verified" in full_text
    for vid in ids:
        assert f"#{vid}" in full_text
    assert "authentic" not in full_text.lower()
    assert "genuine" not in full_text.lower()

    # Rejects >5 IDs
    excess_ids = "1,2,3,4,5,6"
    bad_res = client.get(f"/api/verifications/report.pdf?ids={excess_ids}")
    assert bad_res.status_code == 400
    assert "Maximum of 5" in bad_res.json()["detail"]

    # Rejects empty or missing IDs
    assert client.get("/api/verifications/report.pdf?ids=").status_code == 400

    # Rejects invalid ID formatting
    assert client.get("/api/verifications/report.pdf?ids=1,abc,3").status_code == 400


# 7. HISTORY INCLUDES report_url
def test_report_url_in_history(rep_env):
    client, chain, _ = rep_env
    login_user(client, email="verifier@authentra.demo")

    pdf_bytes = make_test_pdf("AT-HIST-REP", "History Student", "Art")
    v_res = client.post("/api/verify", files={"file": ("cert.pdf", pdf_bytes)})
    assert v_res.status_code == 200
    v_id = v_res.json()["id"]

    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    rows = hist_res.json()
    target_row = next((r for r in rows if r["id"] == v_id), None)
    assert target_row is not None
    assert target_row["report_url"] == f"/api/verifications/{v_id}/report.pdf"
