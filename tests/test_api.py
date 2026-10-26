import hashlib
import io
import os
import time
import json
import uuid
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
    contract = type("Contract", (), {"address": "0x0000000000000000000000000000000000000000"})()
    def health(self): return True
    def lookup(self, reference): return self.record
    def lookup_by_hash(self, file_hash):
        if self.record and self.record.get("file_hash", "").lower() == (file_hash or "").lower().removeprefix("0x"):
            return self.record
        return None
    def approved(self, address): return True
    def get_network_info(self):
        return {"chain_id": 1337, "network_name": "Local development · chain 1337", "contract_address": "0x0000000000000000000000000000000000000000", "explorer_template": None}
    def get_explorer_url(self, tx_hash):
        return None
    def register(self, reference, file_hash, issuer):
        return {"transaction_hash": "0xconfirmed", "gas_used": 21000, "fee_wei": "1000", "block_number": 1}
    def register_and_verify(self, reference, file_hash, issuer):
        self.record = {"file_hash": file_hash, "issuer": issuer, "registered_at": 1700000000, "revoked": False}
        return {"transaction_hash": "0xconfirmed", "gas_used": 21000, "fee_wei": "1000", "block_number": 1, "registered_at": 1700000000, "contract_address": "0x0000000000000000000000000000000000000000", "network": "1337", "on_chain_verified": True, "idempotent": False}

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
    stream = io.BytesIO(); c = canvas.Canvas(stream); c.setTitle(uuid.uuid4().hex); c.drawString(50, 700, "Certificate ID: AT-001"); c.save(); return stream.getvalue()

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
    assert r.json()["role"] in ("USER", "verifier")

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
        return {"reference":reference,"status":"registered","transaction_hash":"0xconfirmed"}
    monkeypatch.setattr(main,"register_document",register)
    files=[("files",("one.pdf",pdf())),("files",("two.pdf",pdf()))]
    response=client.post("/api/certificates/bulk",files=files,data={"references":'["NEW-001","DUPLICATE"]'})
    assert response.status_code == 202
    result=wait_batch(client,response.json()["id"])
    assert [r["state"] for r in result["items"]] == ["succeeded","failed"]
    assert result["summary"]["successful"] == 1
    assert result["summary"]["failed"] == 1

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
    assert row['role'] in ('INSTITUTION_ADMIN', 'institution') and row['approval_status'] == 'PENDING_APPROVAL'
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



def wait_batch(client, job):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get('/api/uploads/' + job)
        assert response.status_code == 200, response.text
        if response.json()['state'] == 'completed':
            return response.json()
        time.sleep(.03)
    pytest.fail('Upload worker did not finish')


def upload(client, files, mode='verify', refs=None):
    return client.post('/api/uploads', files=[('files', f) for f in files], data={'mode': mode, 'references': json.dumps(refs or [])})


@pytest.fixture
def simple_analysis(monkeypatch):
    monkeypatch.setattr(main, 'analyze', lambda *args: {'fields': {'reference': 'AT-001'}, 'ai': {'status': 'unavailable', 'label': 'Unavailable'}, 'warnings': []})


def test_upload_auth_and_role_boundaries(client):
    assert upload(client, [('x.pdf', pdf())]).status_code == 401
    assert client.get('/api/uploads').status_code == 401
    login(client)
    assert upload(client, [('x.pdf', pdf())], 'register', ['AT-001']).status_code == 403
    assert client.get('/api/uploads/limits?mode=register').status_code == 403
    assert client.get('/api/uploads/limits').json()['max_files'] == 5


def test_five_file_server_limit(client, simple_analysis):
    login(client)
    response = upload(client, [(str(i)+'.pdf', pdf()) for i in range(6)])
    assert response.status_code == 422
    assert client.get('/api/uploads').json() == []
    response = upload(client, [(str(i)+'.pdf', pdf()) for i in range(5)])
    assert response.status_code == 202
    result = wait_batch(client, response.json()['id'])
    assert result['summary'] == {'total': 5, 'valid': 5, 'rejected': 0, 'pending': 0, 'successful': 5, 'failed': 0}
    assert all(i['result']['status'] == 'not_registered' for i in result['items'])


@pytest.mark.parametrize('name,data,mime', [
    ('fake.pdf', b'not a PDF', 'application/pdf'),
    ('empty.jpg', b'', 'image/jpeg'),
    ('renamed.png', None, 'image/png'),
    ('wrong.pdf', None, 'text/html'),
    ('archive.zip', b'PK\x03\x04', 'application/zip'),
    ('broken.png', b'\x89PNG\r\n\x1a\ncorrupt', 'image/png'),
])
def test_per_file_validation_rejects_without_success(client, name, data, mime):
    login(client)
    response = upload(client, [(name, pdf() if data is None else data, mime)])
    assert response.status_code == 202
    batch = wait_batch(client, response.json()['id'])
    assert batch['summary']['rejected'] == 1 and batch['summary']['successful'] == 0
    assert batch['items'][0]['result']['error']
    with connect() as conn:
        assert conn.execute('SELECT data FROM upload_items').fetchone()[0] is None
        assert conn.execute('SELECT state FROM upload_jobs').fetchone()[0] == 'completed'


def test_file_size_limit(client):
    login(client)
    result = upload(client, [('large.pdf', b'%PDF-' + b'x' * main.MAX_BYTES)])
    assert result.status_code == 202
    assert result.json()['summary']['rejected'] == 1


def test_duplicate_bytes_and_partial_failure(client, simple_analysis):
    login(client)
    data = pdf()
    result = upload(client, [('first.pdf', data), ('copy.pdf', data), ('bad.pdf', b'broken')])
    batch = wait_batch(client, result.json()['id'])
    assert [i['state'] for i in batch['items']] == ['succeeded', 'rejected', 'rejected']
    assert batch['summary']['valid'] == 1
    assert 'Duplicate' in batch['items'][1]['result']['error']
    with connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM upload_items WHERE data IS NOT NULL').fetchone()[0] == 0


def test_job_and_csv_are_private_and_csv_escapes_formulas(client, simple_analysis):
    login(client)
    response = upload(client, [('=HYPERLINK("bad").pdf', pdf())])
    batch = wait_batch(client, response.json()['id'])
    report = client.get('/api/uploads/' + batch['id'] + '/report')
    assert report.status_code == 200 and 'text/csv' in report.headers['content-type']
    import csv
    assert list(csv.reader(io.StringIO(report.text)))[1][0].startswith("'=HYPERLINK")
    login(client, 'issuer')
    assert client.get('/api/uploads/' + batch['id']).status_code == 404
    assert client.get('/api/uploads/' + batch['id'] + '/report').status_code == 404
    assert client.get('/api/uploads').json() == []


def test_configurable_institution_limits_and_chain_approval(client, monkeypatch):
    login(client, 'issuer')
    monkeypatch.setattr(main.uploads, 'BULK_FILES', 2)
    assert client.get('/api/uploads/limits?mode=register').json()['max_files'] == 2
    assert client.get('/api/uploads/limits?mode=verify').json()['max_files'] == 2
    login(client, 'verifier')
    assert client.get('/api/uploads/limits?mode=verify').json()['max_files'] == 5
    login(client, 'issuer')
    assert upload(client, [(str(i)+'.pdf', pdf()) for i in range(3)], 'register', ['AT-001','AT-002','AT-003']).status_code == 422
    monkeypatch.setattr(FakeRegistry, 'approved', lambda *args: False)
    assert upload(client, [('x.pdf', pdf())], 'register', ['AT-001']).status_code == 403
    assert client.get('/api/uploads/limits?mode=register').status_code == 403


def test_total_batch_bytes_rejected_atomically(client, monkeypatch):
    login(client, 'issuer')
    data = pdf()
    monkeypatch.setattr(main.uploads, 'BULK_BYTES', len(data) + 10)
    response = upload(client, [('x.pdf', data), ('y.pdf', pdf())], 'register', ['AT-001','AT-002'])
    assert response.status_code == 413
    assert client.get('/api/uploads?mode=register').json() == []


def test_reference_validation_and_duplicate_ids(client, monkeypatch):
    login(client, 'issuer')
    monkeypatch.setattr(main, 'register_document', lambda *args: {'status':'registered','transaction_hash':'0xconfirmed'})
    response = upload(client, [('a.pdf', pdf()), ('b.pdf', pdf()), ('c.pdf', pdf())], 'register', ['AT-001', 'AT-001', '../invalid'])
    batch = wait_batch(client, response.json()['id'])
    assert [i['state'] for i in batch['items']] == ['succeeded','rejected','rejected']


def test_worker_failure_does_not_abort_remaining_files(client, monkeypatch):
    login(client, 'issuer')
    def process(data, kind, reference, user):
        if reference == 'AT-002':
            raise RuntimeError('private internal message')
        return {'status':'registered','transaction_hash':'0xconfirmed'}
    monkeypatch.setattr(main, 'register_document', process)
    response = upload(client, [(str(i)+'.pdf', pdf()) for i in range(3)], 'register', ['AT-001','AT-002','AT-003'])
    batch = wait_batch(client, response.json()['id'])
    assert [i['state'] for i in batch['items']] == ['succeeded','failed','succeeded']
    assert 'private internal message' not in json.dumps(batch)


def test_unconfirmed_registration_never_succeeds(client, monkeypatch):
    login(client, 'issuer')
    monkeypatch.setattr(main, 'register_document', lambda *args: {'status':'registered'})
    batch = wait_batch(client, upload(client, [('a.pdf',pdf())], 'register', ['AT-001']).json()['id'])
    assert batch['summary']['failed'] == 1 and batch['summary']['successful'] == 0


def test_bounded_queue_and_responsive_api(client, monkeypatch, simple_analysis):
    import threading
    login(client)
    entered, release = threading.Event(), threading.Event()
    original = main.process_verification
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(main, 'process_verification', slow)
    monkeypatch.setattr(main.uploads, 'MAX_ACTIVE', 1)
    response = upload(client, [('a.pdf', pdf())])
    try:
        assert entered.wait(3)
        assert client.get('/api/auth/me').status_code == 200
        assert client.get('/api/uploads/' + response.json()['id']).json()['summary']['pending'] == 1
        assert upload(client, [('b.pdf', pdf())]).status_code == 429
    finally:
        release.set()
    wait_batch(client, response.json()['id'])


def test_restart_marks_inflight_uncertain_without_replay(tmp_path, monkeypatch):
    from backend.storage import initialize
    monkeypatch.setenv('AUTHENTRA_DB', str(tmp_path / 'restart.db'))
    initialize(); main.uploads.initialize_jobs()
    with connect() as conn:
        conn.execute("INSERT INTO users(id,email,name,password,role) VALUES(1,'t@t.test','Test','unused','verifier')")
    user = {'id': 1}
    job = main.uploads.create_job(user, 'verify', [('a.pdf','',pdf(),'pdf',None)])
    with connect() as conn:
        conn.execute("UPDATE upload_items SET state='processing'")
    main.uploads.initialize_jobs()
    batch = main.uploads.snapshot(job, user)
    assert batch['state'] == 'completed' and batch['items'][0]['state'] == 'failed'
    assert 'interrupted' in batch['items'][0]['result']['error']
    with connect() as conn:
        assert conn.execute('SELECT data FROM upload_items').fetchone()[0] is None


def test_worker_lock_prevents_two_servers(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTHENTRA_DB', str(tmp_path / 'lock.db'))
    with main.uploads.worker_guard():
        with pytest.raises(RuntimeError, match='one AuthenTra'):
            with main.uploads.worker_guard():
                pass


def test_streamed_request_limit_without_content_length(client, monkeypatch):
    login(client)
    # Exercise the real transport with chunked input and a deliberately small receiving bound.
    import backend.upload_transport as transport
    monkeypatch.setattr(transport, 'MAX_BYTES', 1)
    response = client.post('/api/uploads', content=iter([b'x' * 600000, b'x' * 600000]), headers={'Content-Type':'multipart/form-data; boundary=boundary'})
    assert response.status_code == 413
    assert client.get('/api/uploads').json() == []


def test_existing_registration_bytes_not_reissued(client, monkeypatch):
    login(client, 'issuer')
    data = pdf()
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference,issuer_id,file_hash,transaction_hash) VALUES('EXISTING',2,?,'0xconfirmed')", (hashlib.sha256(data).hexdigest(),))
    response = client.post('/api/certificates', files={'file':('a.pdf',data)}, data={'reference':'NEW-ID'})
    assert response.status_code == 409
    assert 'already registered' in response.json()['detail']
