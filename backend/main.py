import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .core import decide, normalize_reference
from .documents import MAX_BYTES, analyze, validate_document
from .registry import Registry
from .storage import ROOT, audit, connect, initialize, password_hash, password_matches, seed_demo

DEMO = os.getenv("AUTHENTRA_DEMO", "0") == "1"
JWT_SECRET = os.getenv("JWT_SECRET") or (secrets.token_hex(32) if DEMO else "")
LOGIN_ATTEMPTS = {}
COOKIE = "authentra_session"
LABELS = {"verified": "Verified", "possible_tampering": "Possible Tampering", "not_registered": "Not Registered", "revoked": "Revoked", "not_verified": "Not Verified", "unable_to_authenticate": "Unable to Authenticate", "inconclusive": "Inconclusive"}

@asynccontextmanager
async def lifespan(app):
    if len(JWT_SECRET) < 32:
        raise RuntimeError("Set a JWT_SECRET of at least 32 characters, or explicitly enable AUTHENTRA_DEMO=1 for local development.")
    initialize()
    if DEMO:
        seed_demo(Registry())
    yield

app = FastAPI(title="AuthenTra API", version="0.1.0", lifespan=lifespan)

@app.middleware("http")
async def security_headers(request, call_next):
    # Reject oversized uploads before multipart parsing when Content-Length is available.
    try:
        if int(request.headers.get("content-length", "0")) > 51 * 1024 * 1024:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Request exceeds the 50 MB batch limit."}, status_code=413)
    except ValueError:
        raise HTTPException(400, "Invalid content length")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

def public_user(user):
    return {key: user[key] for key in ["id", "name", "email", "role", "wallet"]}

def current_user(request: Request):
    try:
        payload = jwt.decode(request.cookies.get(COOKIE, ""), JWT_SECRET, algorithms=["HS256"], issuer="authentra")
        with connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (int(payload["sub"]),)).fetchone()
        if user is None:
            raise ValueError()
        return dict(user)
    except Exception:
        raise HTTPException(401, "Please sign in to continue.")

User = Annotated[dict, Depends(current_user)]

def role(user, *allowed):
    if user["role"] not in allowed:
        raise HTTPException(403, "Your account is not authorized for this action.")

def registry():
    try:
        value = Registry()
        if not value.health():
            raise RuntimeError()
        return value
    except Exception:
        raise HTTPException(503, "The blockchain is unavailable. No authenticity conclusion can be made.")

def safe_chain_action(action):
    try:
        return action()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(409, "The blockchain did not confirm this action. Check authorization, duplicate IDs and network status before retrying.")

class Credentials(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=128)

class Signup(Credentials):
    name: str = Field(min_length=2, max_length=100)

@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    key = request.client.host if request.client else "local"
    now = time.monotonic()
    attempts = [t for t in LOGIN_ATTEMPTS.get(key, []) if now - t < 300]
    if len(attempts) >= 20:
        raise HTTPException(429, "Too many attempts. Try again in five minutes.")
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (body.email.lower().strip(),)).fetchone()
    if not user or not password_matches(body.password, user["password"]):
        LOGIN_ATTEMPTS[key] = attempts + [now]
        raise HTTPException(401, "The email or password is incorrect.")
    LOGIN_ATTEMPTS.pop(key, None)
    token = jwt.encode({"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)}, JWT_SECRET, algorithm="HS256")
    response.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    return public_user(user)

@app.post("/api/auth/signup", status_code=201)
def signup(body: Signup):
    if len(body.password) < 12 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email):
        raise HTTPException(422, "Enter a valid email and a password of at least 12 characters.")
    try:
        with connect() as conn:
            conn.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,'verifier')", (body.email.lower().strip(), body.name.strip(), password_hash(body.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This email is already registered.")
    return {"message": "Account created. You can now sign in."}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
def me(user: User):
    return public_user(user)

@app.get("/api/health")
def health():
    try:
        chain = Registry()
        connected = chain.health()
        address = chain.contract.address
    except Exception:
        connected, address = False, None
    return {"status": "ready" if connected else "degraded", "blockchain": connected, "network": "Local development · chain 1337" if DEMO else "Configured Ethereum network", "contract": address, "demo": DEMO, "model": (ROOT / ".local/model.joblib").exists()}

@app.get("/api/dashboard")
def dashboard(user: User):
    with connect() as conn:
        checks = [dict(r) for r in conn.execute("SELECT * FROM verifications WHERE user_id=? ORDER BY id DESC", (user["id"],))]
        count = conn.execute("SELECT COUNT(*) FROM registrations" + (" WHERE issuer_id=?" if user["role"] != "owner" else ""), (user["id"],) if user["role"] != "owner" else ()).fetchone()[0]
    durations = sorted(r["duration_ms"] for r in checks if r["duration_ms"] is not None)
    approved = None
    if user["role"] == "institution":
        try:
            approved = registry().approved(user["wallet"])
        except HTTPException:
            pass
    return {"total": len(checks), "verified": sum(r["status"] == "verified" for r in checks), "review": sum(r["status"] != "verified" for r in checks), "registered": count, "mean_ms": round(sum(durations) / len(durations)) if durations else None, "p95_ms": round(durations[max(0, int(len(durations) * .95 + .999) - 1)]) if durations else None, "recent": checks[:5], "issuer_approved": approved}

@app.get("/api/history")
def history(user: User):
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM verifications WHERE user_id=? ORDER BY id DESC LIMIT 500", (user["id"],))]

async def read_upload(file):
    try:
        data = await file.read(MAX_BYTES + 1)
        kind = await run_in_threadpool(validate_document, data)
        return data, kind
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        await file.close()

def process_verification(data, kind, supplied_reference, user):
    start = time.perf_counter()
    digest = hashlib.sha256(data).hexdigest()
    analysis = analyze(data, kind)
    reference = None
    extracted = analysis["fields"]["reference"]
    checks = {"reference_found": None, "hash_matches": None, "issuer_approved": None, "active": None}
    record = None
    try:
        reference = normalize_reference(supplied_reference or extracted or "")
    except ValueError:
        status, message = "inconclusive", "A readable certificate ID is required. Confirm the ID from the issuing institution and try again."
    else:
        if supplied_reference and extracted and reference != extracted.upper():
            analysis["warnings"].append("The entered certificate ID differs from the extracted ID. This result applies to the entered ID.")
        try:
            chain = registry()
            record = chain.lookup(reference)
            authorized = chain.approved(record["issuer"]) if record else False
            checks = {"reference_found": record is not None, "hash_matches": record["file_hash"] == digest if record else None, "issuer_approved": authorized if record else None, "active": not record["revoked"] if record else None}
            status, message = decide(record, digest, authorized)
        except Exception:
            status, message = "unable_to_authenticate", "The blockchain could not be read. Please retry when the service is available."
    elapsed = round((time.perf_counter() - start) * 1000, 1)
    with connect() as conn:
        cursor = conn.execute("INSERT INTO verifications(user_id,reference,status,file_hash,duration_ms,ai_status) VALUES(?,?,?,?,?,?)", (user["id"], reference, status, digest, elapsed, analysis["ai"]["status"]))
        check_id = cursor.lastrowid
    return {"id": check_id, "reference": reference, "status": status, "label": LABELS[status], "message": message, "file_hash": digest, "registered_hash": record["file_hash"] if record else None, "issuer": record["issuer"] if record else None, "checks": checks, "duration_ms": elapsed, **analysis}

@app.post("/api/verify")
async def verify(user: User, file: UploadFile = File(...), reference: str = Form("")):
    try:
        data, kind = await read_upload(file)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return {"status": "unable_to_authenticate", "label": LABELS["unable_to_authenticate"], "message": exc.detail, "checks": {}, "ai": {"status": "unavailable", "label": "AI analysis unavailable", "score": None}, "warnings": [], "fields": {}}
    return await run_in_threadpool(process_verification, data, kind, reference, user)

def register_document(data, kind, reference, user):
    role(user, "institution")
    try:
        reference = normalize_reference(reference)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    chain = registry()
    if not chain.approved(user["wallet"]):
        raise HTTPException(403, "Your institution must be approved before registering certificates.")
    if chain.lookup(reference):
        raise HTTPException(409, "This certificate ID already exists. IDs cannot be overwritten or reused.")
    digest = hashlib.sha256(data).hexdigest()
    transaction = safe_chain_action(lambda: chain.register(reference, digest, user["wallet"]))
    with connect() as conn:
        conn.execute("INSERT INTO registrations(reference,issuer_id,file_hash,transaction_hash,gas_used,fee_wei) VALUES(?,?,?,?,?,?)", (reference, user["id"], digest, transaction["transaction_hash"], transaction["gas_used"], transaction["fee_wei"]))
        audit(conn, user["id"], "register", reference, transaction["transaction_hash"])
    return {"reference": reference, "file_hash": digest, "status": "registered", **transaction}

@app.post("/api/certificates", status_code=201)
async def register(user: User, file: UploadFile = File(...), reference: str = Form(...)):
    role(user, "institution")
    data, kind = await read_upload(file)
    return await run_in_threadpool(register_document, data, kind, reference, user)

@app.post("/api/certificates/bulk")
async def bulk(user: User, files: list[UploadFile] = File(...), references: str = Form(...)):
    role(user, "institution")
    try:
        ids = json.loads(references)
        if not isinstance(ids, list) or len(ids) != len(files) or not all(isinstance(i, str) for i in ids) or not 1 <= len(files) <= 20:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "Supply one certificate ID per file, up to 20 files per batch.")
    start = time.perf_counter()
    results = []
    total_bytes = 0
    for file, reference in zip(files, ids):
        try:
            data, kind = await read_upload(file)
            total_bytes += len(data)
            if total_bytes > 50 * 1024 * 1024:
                raise HTTPException(413, "Batch exceeds 50 MB; this and subsequent files were not registered.")
            result = await run_in_threadpool(register_document, data, kind, reference, user)
            results.append({"filename": file.filename, "ok": True, **result})
        except HTTPException as exc:
            results.append({"filename": file.filename, "reference": reference, "ok": False, "error": exc.detail})
    duration = time.perf_counter() - start
    success = sum(r["ok"] for r in results)
    return {"results": results, "duration_ms": round(duration * 1000), "throughput_per_second": round(success / max(duration, .001), 2), "failure_rate": (len(results) - success) / len(results)}

@app.get("/api/certificates")
def certificates(user: User):
    role(user, "institution", "owner")
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT r.*, u.name AS issuer_name FROM registrations r JOIN users u ON u.id=r.issuer_id" + (" WHERE issuer_id=?" if user["role"] == "institution" else "") + " ORDER BY created_at DESC", (user["id"],) if user["role"] == "institution" else ())]
    chain = registry()
    for row in rows:
        record = chain.lookup(row["reference"])
        row["revoked"] = record["revoked"] if record else None
        row["issuer_approved"] = chain.approved(record["issuer"]) if record else None
    return rows

@app.post("/api/certificates/{reference}/revoke")
def revoke(reference: str, user: User):
    role(user, "institution", "owner")
    try:
        reference = normalize_reference(reference)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    chain = registry()
    record = chain.lookup(reference)
    if not record:
        raise HTTPException(404, "Certificate not found.")
    if user["role"] != "owner" and record["issuer"].lower() != user["wallet"].lower():
        raise HTTPException(403, "Only the issuing institution or platform owner can revoke this certificate.")
    transaction = safe_chain_action(lambda: chain.revoke(reference, user["wallet"]))
    with connect() as conn:
        audit(conn, user["id"], "revoke", reference, transaction["transaction_hash"])
    return {"status": "revoked", **transaction}

class Approval(BaseModel):
    approved: bool

class Institution(Signup):
    wallet: str

@app.get("/api/institutions")
def institutions(user: User):
    role(user, "owner")
    with connect() as conn:
        rows = [public_user(r) for r in conn.execute("SELECT * FROM users WHERE role='institution'")]
    chain = registry()
    return [{**r, "approved": chain.approved(r["wallet"])} for r in rows]

@app.post("/api/institutions", status_code=201)
def add_institution(body: Institution, user: User):
    role(user, "owner")
    from web3 import Web3
    if not Web3.is_address(body.wallet) or len(body.password) < 12 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email):
        raise HTTPException(422, "Provide a valid wallet, email and password of at least 12 characters.")
    wallet = Web3.to_checksum_address(body.wallet)
    try:
        with connect() as conn:
            if conn.execute("SELECT id FROM users WHERE wallet=?", (wallet,)).fetchone():
                raise HTTPException(409, "This wallet already belongs to an account.")
            conn.execute("INSERT INTO users(email,name,password,role,wallet) VALUES(?,?,?,'institution',?)", (body.email.lower().strip(), body.name, password_hash(body.password), wallet))
            audit(conn, user["id"], "institution_created", wallet)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "The email is already registered.")
    return {"message": "Institution created. Approve its wallet after verifying its identity and configuring its server-side signer."}

@app.post("/api/institutions/{institution_id}/approval")
def approve(institution_id: int, body: Approval, user: User):
    role(user, "owner")
    with connect() as conn:
        institution = conn.execute("SELECT * FROM users WHERE id=? AND role='institution'", (institution_id,)).fetchone()
    if not institution:
        raise HTTPException(404, "Institution not found.")
    transaction = safe_chain_action(lambda: registry().set_issuer(institution["wallet"], body.approved))
    with connect() as conn:
        audit(conn, user["id"], "issuer_approved" if body.approved else "issuer_disabled", institution["wallet"], transaction["transaction_hash"])
    return {"approved": body.approved, **transaction}

@app.get("/api/audit")
def audit_log(user: User):
    role(user, "institution", "owner")
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT a.*,u.name AS actor FROM audit a JOIN users u ON a.user_id=u.id" + (" WHERE user_id=?" if user["role"] != "owner" else "") + " ORDER BY a.id DESC LIMIT 200", (user["id"],) if user["role"] != "owner" else ())]

@app.get("/api/evaluation")
def evaluation(user: User):
    result = {}
    for key, filename in [("model", "model-metrics.json"), ("system", "system-metrics.json")]:
        path = ROOT / ".local" / filename
        result[key] = json.loads(path.read_text()) if path.exists() else None
    return result

@app.get("/api/samples/{filename}")
def sample(filename: str):
    if not DEMO or filename not in {"original.pdf", "modified.pdf", "unregistered.pdf", "revoked.pdf", "scan.png"}:
        raise HTTPException(404, "Sample not found.")
    path = ROOT / "samples" / filename
    if not path.exists():
        raise HTTPException(404, "Run the sample setup script first.")
    return FileResponse(path, filename=filename)

if (ROOT / "dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
