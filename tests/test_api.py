import hashlib
import io
import os
os.environ["AUTHENTRA_DEMO"] = "1"
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from backend import main
from backend.storage import connect, password_hash

class FakeRegistry:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {owner: "unused", "0x0000000000000000000000000000000000000002": "unused", "0x0000000000000000000000000000000000000003": "unused"}
    record = None
    def health(self): return True
    def lookup(self, reference): return self.record
    def approved(self, address): return True

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTHENTRA_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "Registry", FakeRegistry)
    FakeRegistry.record = None
    main.LOGIN_ATTEMPTS.clear()
    with TestClient(main.app) as client:
        yield client

def login(client, role="verifier"):
    response = client.post("/api/auth/login", json={"email": role + "@authentra.demo", "password": "AuthenTra-demo-2026!"})
    assert response.status_code == 200
    return response

def pdf():
    stream = io.BytesIO(); c = canvas.Canvas(stream); c.drawString(50, 700, "Certificate ID: AT-001"); c.save(); return stream.getvalue()

def test_authentication_required(client):
    assert client.post("/api/verify", files={"file": ("file.pdf", pdf())}).status_code == 401

def test_general_user_cannot_issue_or_revoke(client):
    login(client)
    assert client.post("/api/certificates", data={"reference": "AT-001"}, files={"file": ("file.pdf", pdf())}).status_code == 403
    assert client.post("/api/certificates/AT-001/revoke").status_code == 403
    assert client.get("/api/institutions").status_code == 403

def test_signup_cannot_self_assign_admin(client):
    r = client.post("/api/auth/signup", json={"email":"new@example.test","name":"New user","password":"strong-test-password","role":"owner"})
    assert r.status_code == 201
    r = client.post("/api/auth/login", json={"email":"new@example.test","password":"strong-test-password"})
    assert r.json()["role"] == "verifier"

def test_invalid_file_is_unable_to_authenticate(client):
    login(client)
    r = client.post("/api/verify", files={"file": ("fake.pdf", b"not PDF")})
    assert r.status_code == 200 and r.json()["status"] == "unable_to_authenticate"

def test_history_is_private(client):
    login(client)
    with connect() as conn:
        conn.execute("INSERT INTO verifications(user_id,reference,status) VALUES(2,'PRIVATE-001','verified')")
    assert client.get("/api/history").json() == []

def test_logout_clears_session(client):
    r = login(client)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

def test_ai_cannot_override_verified(client, monkeypatch):
    login(client); data = pdf()
    FakeRegistry.record = {"file_hash":hashlib.sha256(data).hexdigest(),"issuer":FakeRegistry.owner,"revoked":False}
    monkeypatch.setattr(main, "analyze", lambda *args: {"fields":{"reference":"AT-001"},"ai":{"status":"warning","label":"Potential anomaly detected","score":1},"warnings":[]})
    response = client.post("/api/verify", files={"file":("x.pdf",data)})
    assert response.json()["status"] == "verified"
    assert response.json()["ai"]["status"] == "warning"

def test_missing_id_inconclusive_not_unregistered(client, monkeypatch):
    login(client)
    monkeypatch.setattr(main,"analyze",lambda *args: {"fields":{"reference":None},"ai":{"status":"unavailable"},"warnings":[]})
    assert client.post("/api/verify",files={"file":("x.pdf",pdf())}).json()["status"] == "inconclusive"

def test_network_failure_never_authentic(client, monkeypatch):
    login(client)
    monkeypatch.setattr(main,"analyze",lambda *args: {"fields":{"reference":"AT-001"},"ai":{"status":"clear"},"warnings":[]})
    def fail(): raise RuntimeError("network offline")
    monkeypatch.setattr(main,"registry",fail)
    result=client.post("/api/verify",files={"file":("x.pdf",pdf())}).json()
    assert result["status"] == "unable_to_authenticate"

def test_ocr_failure_with_manual_id_preserves_trusted_checks(client, monkeypatch):
    login(client); data=pdf()
    FakeRegistry.record={"file_hash":hashlib.sha256(data).hexdigest(),"issuer":FakeRegistry.owner,"revoked":False}
    monkeypatch.setattr(main,"analyze",lambda *args: {"fields":{"reference":None},"ai":{"status":"unavailable"},"warnings":["OCR failed"]})
    result=client.post("/api/verify",data={"reference":"AT-001"},files={"file":("x.pdf",data)}).json()
    assert result["status"] == "verified" and result["ai"]["status"] == "unavailable"

def test_bulk_reports_partial_success(client, monkeypatch):
    login(client, "issuer")
    def register(data, kind, reference, user):
        if reference == "DUPLICATE":
            raise main.HTTPException(409, "Reference already exists")
        return {"reference":reference,"status":"registered"}
    monkeypatch.setattr(main,"register_document",register)
    files=[("files",("one.pdf",pdf())),("files",("two.pdf",pdf()))]
    result=client.post("/api/certificates/bulk",files=files,data={"references":'["NEW-001","DUPLICATE"]'}).json()
    assert [r["ok"] for r in result["results"]] == [True,False]
    assert result["failure_rate"] == .5

def test_bulk_rejects_reference_count_mismatch(client):
    login(client,"issuer")
    response=client.post("/api/certificates/bulk",files=[("files",("one.pdf",pdf()))],data={"references":"[]"})
    assert response.status_code == 422
