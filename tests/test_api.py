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

def test_failed_login_and_wrong_portal(client):
    assert client.post('/api/auth/login', json={'email':'verifier@authentra.demo','password':'wrong'}).status_code == 401
    assert client.post('/api/auth/login', json={'email':'verifier@authentra.demo','password':'AuthenTra-demo-2026!','account_type':'institution'}).status_code == 403


def application(client, **extra):
    return client.post('/api/auth/institution-signup', json={'email':'office@college.test','name':'Example College','password':'strong-test-password','wallet':'0x0000000000000000000000000000000000000004','institution_reference':'COL-123','verification_info':'https://college.test; registrar contact',**extra})


def test_institution_application_cannot_self_approve(client):
    result = application(client, role='owner', approval_status='APPROVED', approved=True)
    assert result.status_code == 201
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email='office@college.test'").fetchone()
    assert row['role'] == 'institution' and row['approval_status'] == 'PENDING_APPROVAL'
    assert client.post('/api/auth/login',json={'email':'office@college.test','password':'strong-test-password','account_type':'institution'}).status_code == 403
    assert application(client).status_code == 409


def test_pending_institution_denied_every_protected_route(client):
    assert client.post('/api/auth/login',json={'email':'pending@authentra.demo','password':'AuthenTra-demo-2026!'}).status_code == 403
    import jwt
    from datetime import datetime, timedelta, timezone
    token = jwt.encode({'sub':'3','iss':'authentra','exp':datetime.now(timezone.utc)+timedelta(hours=1)},main.JWT_SECRET,algorithm='HS256')
    client.cookies.set(main.COOKIE,token)
    for path in ['/api/auth/me','/api/dashboard','/api/history','/api/certificates','/api/audit']:
        assert client.get(path).status_code == 403
    assert client.post('/api/certificates/bulk',files=[('files',('x.pdf',pdf()))],data={'references':'["AT-001"]'}).status_code == 403


def test_existing_session_loses_access_on_suspend(client):
    login(client,'issuer')
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status='SUSPENDED' WHERE email='issuer@authentra.demo'")
    assert client.get('/api/history').status_code == 403


@pytest.mark.parametrize('claims', [{}, {'exp':1}, {'exp':4102444800,'iss':'other'}])
def test_invalid_or_expired_session(client, claims):
    import jwt
    payload={'sub':'1','iss':'authentra',**claims}
    client.cookies.set(main.COOKIE,jwt.encode(payload,main.JWT_SECRET,algorithm='HS256'))
    assert client.get('/api/auth/me').status_code == 401


def test_owner_approval_and_revocation(client, monkeypatch):
    monkeypatch.setattr(FakeRegistry,'set_issuer',lambda self,wallet,approved: {'transaction_hash':'0xtest'},raising=False)
    login(client,'owner')
    for status in ['APPROVED','REJECTED','SUSPENDED','REVOKED']:
        response=client.post('/api/institutions/3/approval',json={'status':status})
        assert response.status_code == 200
        with connect() as conn:
            assert conn.execute('SELECT approval_status FROM users WHERE id=3').fetchone()[0] == status


def test_institution_cannot_approve(client):
    login(client,'issuer')
    assert client.post('/api/institutions/3/approval',json={'status':'APPROVED'}).status_code == 403


def test_application_validation(client):
    assert application(client, institution_reference=' ').status_code == 422
    assert application(client, verification_info=' ').status_code == 422
    assert application(client, wallet='0x'+'0'*40).status_code == 422

def test_schema_upgrade_preserves_legacy_accounts(tmp_path, monkeypatch):
    import sqlite3
    from backend.storage import initialize
    path = tmp_path / 'legacy.db'
    monkeypatch.setenv('AUTHENTRA_DB',str(path))
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, wallet TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        conn.execute("INSERT INTO users(email,name,password,role) VALUES('legacy@test.example','Legacy','hash','institution')")
    initialize()
    initialize()
    with connect() as conn:
        row=conn.execute('SELECT * FROM users').fetchone()
        assert row['name']=='Legacy' and row['approval_status']=='APPROVED'


def test_failed_chain_approval_keeps_pending(client, monkeypatch):
    login(client,'owner')
    def fail(*args):
        raise RuntimeError('offline')
    monkeypatch.setattr(FakeRegistry,'set_issuer',fail,raising=False)
    assert client.post('/api/institutions/3/approval',json={'status':'APPROVED'}).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT approval_status FROM users WHERE id=3').fetchone()[0]=='PENDING_APPROVAL'
