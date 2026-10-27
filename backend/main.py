import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .core import CATEGORY_ACTIONS, CATEGORY_MAP, decide, normalize_reference, reference_hash
from .documents import MAX_BYTES, analyze
from .registry import Registry, UncertainTransactionError
from . import uploads, domains, email_verification, auth_oauth
from .storage import ROOT, audit, connect, initialize, password_hash, password_matches, seed_demo, ROLE_USER, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN, canonical_role

DEMO = os.getenv("AUTHENTRA_DEMO", "0") == "1"
JWT_SECRET = os.getenv("JWT_SECRET") or (secrets.token_hex(32) if DEMO else "")
LOGIN_ATTEMPTS = {}
COOKIE = "authentra_session"
LABELS = {
    "verified": "Verified",
    "VERIFIED": "Verified",
    "possible_tampering": "Possible Tampering",
    "tampering_detected": "Tampering Detected",
    "TAMPERING_DETECTED": "Possible Tampering or File Mismatch",
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "Possible Tampering or File Mismatch",
    "not_registered": "Not Registered",
    "NOT_REGISTERED": "Not Registered",
    "inconclusive": "Inconclusive",
    "INCONCLUSIVE": "Inconclusive",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "Not Registered or Inconclusive",
    "revoked": "Revoked",
    "REVOKED": "Revoked",
    "not_verified": "Issuer Not Authorized",
    "ISSUER_NOT_AUTHORIZED": "Issuer Not Authorized",
    "unable_to_authenticate": "Verification Unavailable",
    "VERIFICATION_UNAVAILABLE": "Verification Unavailable",
    "invalid_file": "Invalid File",
    "INVALID_FILE": "Invalid File",
}

@asynccontextmanager
async def lifespan(app):
    if len(JWT_SECRET) < 32:
        raise RuntimeError("Set a JWT_SECRET of at least 32 characters, or explicitly enable AUTHENTRA_DEMO=1 for local development.")
    initialize()
    if DEMO:
        seed_demo(Registry())
    with uploads.worker_guard():
        uploads.initialize_jobs()
        stop, worker = uploads.start_worker(
            lambda *args, **kwargs: process_verification(*args, **kwargs),
            lambda *args, **kwargs: register_document(*args, **kwargs)
        )
        try:
            yield
        finally:
            stop.set()
            await run_in_threadpool(worker.join)

app = FastAPI(title="AuthenTra API", version="0.1.0", lifespan=lifespan)

@app.middleware("http")
async def security_headers(request, call_next):
    # Reject oversized uploads before multipart parsing when Content-Length is available.
    try:
        if int(request.headers.get("content-length", "0")) > max(uploads.BULK_BYTES, 5 * MAX_BYTES) + 1024 * 1024:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Request exceeds the configured batch size limit."}, status_code=413)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Invalid content length"}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

def public_user(user):
    user_dict = dict(user)
    keys = ["id", "name", "email", "role", "wallet", "approval_status", "institution_reference", "verification_info", "institution_domain", "email_verified", "oauth_provider", "review_notes", "created_at"]
    result = {k: user_dict.get(k) for k in keys if k in user_dict}
    result["role"] = canonical_role(result.get("role"))
    return result

def current_user(request: Request):
    try:
        payload = jwt.decode(request.cookies.get(COOKIE, ""), JWT_SECRET, algorithms=["HS256"], issuer="authentra", options={"require": ["exp", "sub", "iss"]})
        with connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (int(payload["sub"]),)).fetchone()
        if row is None:
            raise ValueError()
        user = dict(row)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Please sign in again.")
    except Exception:
        raise HTTPException(401, "Please sign in to continue.")
    ensure_active(user)
    return user

def ensure_active(user):
    user_dict = dict(user)
    if canonical_role(user_dict.get("role")) == ROLE_INSTITUTION_ADMIN and user_dict.get("approval_status") != "APPROVED":
        messages = {
            "PENDING_APPROVAL": "Your institution is pending approval. Contact the platform administrator.",
            "REJECTED": "Your institution application was rejected.",
            "SUSPENDED": "Your institution account is suspended.",
            "REVOKED": "Your institution authorization has been revoked."
        }
        raise HTTPException(403, messages.get(user_dict.get("approval_status"), "Your institution account is not active."))

User = Annotated[dict, Depends(current_user)]

def role(user, *allowed):
    user_role = canonical_role(user["role"])
    allowed_canonical = {canonical_role(r) for r in allowed}
    if user_role not in allowed_canonical:
        raise HTTPException(403, "Your account is not authorized for this action.")

def registry():
    try:
        value = Registry()
        if not value.health():
            raise HTTPException(503, "The blockchain network is unreachable or the registry contract has no deployed bytecode. Check RPC connection and contract address.")
        return value
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(503, f"The blockchain is unavailable: {exc}")

def safe_chain_action(action):
    try:
        return action()
    except HTTPException:
        raise
    except UncertainTransactionError as exc:
        raise HTTPException(504, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(504, detail=f"Transaction confirmation timed out: {exc}")
    except Exception as exc:
        msg = str(exc)
        if "timed out" in msg.lower() or "timeout" in msg.lower() or "uncertain" in msg.lower():
            raise HTTPException(504, detail=f"Transaction confirmation timed out: {exc}")
        if "revert" in msg.lower():
            raise HTTPException(409, "Blockchain transaction reverted.")
        raise HTTPException(409, "The blockchain did not confirm this action. Check authorization, duplicate IDs and network status before retrying.")

class Credentials(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=128)
    account_type: Literal["user", "institution", "admin"] | None = None

class AdminCredentials(BaseModel):
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
        row = conn.execute("SELECT * FROM users WHERE lower(email)=?", (body.email.lower().strip(),)).fetchone()
    if not row or not password_matches(body.password, row["password"]):
        LOGIN_ATTEMPTS[key] = attempts + [now]
        raise HTTPException(401, "The email or password is incorrect.")
    user = dict(row)
    user_role = canonical_role(user["role"])
    expected = {"user": ROLE_USER, "institution": ROLE_INSTITUTION_ADMIN, "admin": ROLE_SYSTEM_ADMIN}
    if body.account_type and user_role != expected.get(body.account_type):
        raise HTTPException(403, "Use the login option for your account type.")
    if user_role == ROLE_INSTITUTION_ADMIN and not user.get("email_verified", 0):
        raise HTTPException(403, "Please verify your institutional email address before signing in.")
    ensure_active(user)
    LOGIN_ATTEMPTS.pop(key, None)
    token = jwt.encode({"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)}, JWT_SECRET, algorithm="HS256")
    response.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    return public_user(user)

@app.post("/api/auth/admin-login")
def admin_login(body: AdminCredentials, request: Request, response: Response):
    key = request.client.host if request.client else "local"
    now = time.monotonic()
    attempts = [t for t in LOGIN_ATTEMPTS.get(key, []) if now - t < 300]
    if len(attempts) >= 20:
        raise HTTPException(429, "Too many attempts. Try again in five minutes.")
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE lower(email)=?", (body.email.lower().strip(),)).fetchone()
    if not row or not password_matches(body.password, row["password"]):
        LOGIN_ATTEMPTS[key] = attempts + [now]
        raise HTTPException(401, "The email or password is incorrect.")
    user = dict(row)
    user_role = canonical_role(user["role"])
    if user_role != ROLE_SYSTEM_ADMIN:
        LOGIN_ATTEMPTS[key] = attempts + [now]
        with connect() as conn:
            audit(conn, user["id"], "admin_login_rejected_not_admin", reference=user["email"], details="Unauthorized attempt to access Admin Login portal", ip_address=key)
        raise HTTPException(403, "Access denied. Only explicitly authorized administrator accounts may access this role.")
    LOGIN_ATTEMPTS.pop(key, None)
    token = jwt.encode({"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)}, JWT_SECRET, algorithm="HS256")
    response.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    with connect() as conn:
        audit(conn, user["id"], "admin_login_success", reference=user["email"], details="System administrator signed in via Admin Login portal", ip_address=key)
    return public_user(user)

@app.post("/api/auth/signup", status_code=201)
def signup(body: Signup):
    if len(body.name.strip()) < 2 or len(body.password) < 12 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email):
        raise HTTPException(422, "Enter a valid email and a password of at least 12 characters.")
    try:
        with connect() as conn:
            conn.execute("INSERT INTO users(email,name,password,role,approval_status,email_verified) VALUES(?,?,?,?,'APPROVED',1)", (body.email.lower().strip(), body.name.strip(), password_hash(body.password), ROLE_USER))
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

# ==================== Google & Apple OAuth ====================

@app.get("/api/auth/oauth/providers")
def oauth_providers():
    return auth_oauth.get_providers_info()

@app.get("/api/auth/oauth/{provider}/url")
def oauth_url(provider: str):
    return auth_oauth.get_authorization_url(provider)

@app.get("/api/auth/oauth/{provider}/callback")
async def oauth_callback_get(provider: str, code: str = "", state: str = "", response: Response = None):
    if not code or not state:
        raise HTTPException(400, "Missing authorization code or state parameter.")
    user_info = await auth_oauth.exchange_oauth_code(provider, code, state)
    user = auth_oauth.provision_oauth_user(user_info)
    token = jwt.encode(
        {"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)},
        JWT_SECRET, algorithm="HS256"
    )
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    return redirect

@app.post("/api/auth/oauth/{provider}/callback")
async def oauth_callback_post(
    provider: str,
    code: str = Form(""),
    state: str = Form(""),
    id_token: str = Form(""),
    response: Response = None
):
    if not state or (not code and not id_token):
        raise HTTPException(400, "Missing authorization code, token, or state parameter.")
    user_info = await auth_oauth.exchange_oauth_code(provider, code, state, id_token)
    user = auth_oauth.provision_oauth_user(user_info)
    token = jwt.encode(
        {"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)},
        JWT_SECRET, algorithm="HS256"
    )
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    return redirect

class OAuthExchange(BaseModel):
    code: str
    state: str
    id_token: str | None = None

@app.post("/api/auth/oauth/{provider}/exchange")
async def oauth_exchange(provider: str, body: OAuthExchange, response: Response):
    user_info = await auth_oauth.exchange_oauth_code(provider, body.code, body.state, body.id_token)
    user = auth_oauth.provision_oauth_user(user_info)
    token = jwt.encode(
        {"sub": str(user["id"]), "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=4)},
        JWT_SECRET, algorithm="HS256"
    )
    response.set_cookie(COOKIE, token, httponly=True, secure=not DEMO, samesite="strict", max_age=14400, path="/")
    return public_user(user)

@app.get("/api/auth/oauth/demo", response_class=HTMLResponse)
def oauth_demo_consent(provider: str = "google", state: str = ""):
    if not DEMO:
        raise HTTPException(404, "Demo OAuth consent is only available when AUTHENTRA_DEMO=1.")
    provider_name = "Google" if provider.lower() == "google" else "Apple"
    sample_email = f"verifier.{provider.lower()}@authentra.demo"
    sample_name = f"Alex Morgan ({provider_name} Account)"
    auth_code = f"demo:{provider.lower()}:{sample_email}:{sample_name}:sub_demo_{provider.lower()}_123"
    callback_url = f"/api/auth/oauth/{provider.lower()}/callback?code={auth_code}&state={state}"

    html = f"""<!DOCTYPE html>
    <html>
    <head>
      <title>{provider_name} Sign In (AuthenTra Demo)</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f6f8; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }}
        .card {{ background: white; border-radius: 12px; box-shadow: 0 4px 18px rgba(0,0,0,0.08); padding: 32px; max-width: 420px; width: 100%; border: 1px solid #e1e8ed; }}
        h2 {{ font-size: 20px; margin: 0 0 8px; color: #1a202c; }}
        p {{ font-size: 14px; color: #4a5568; line-height: 1.5; margin: 0 0 20px; }}
        .identity {{ background: #f7fafc; border: 1px solid #edf2f7; border-radius: 8px; padding: 14px; margin-bottom: 24px; }}
        .identity strong {{ display: block; font-size: 14px; color: #2d3748; }}
        .identity small {{ color: #718096; font-size: 12px; }}
        .btn {{ display: block; width: 100%; text-align: center; background: #087d6a; color: white; text-decoration: none; padding: 12px; border-radius: 6px; font-weight: 600; font-size: 14px; box-sizing: border-box; }}
        .btn:hover {{ background: #066858; }}
        .badge {{ display: inline-block; background: #e6fffa; color: #234e52; font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600; margin-bottom: 12px; }}
      </style>
    </head>
    <body>
      <div class="card">
        <span class="badge">DEVELOPMENT DEMO OIDC</span>
        <h2>Sign in with {provider_name}</h2>
        <p>Authorize AuthenTra Certificate Intelligence to access your verified email and profile.</p>
        <div class="identity">
          <strong>{sample_name}</strong>
          <small>{sample_email}</small>
        </div>
        <a class="btn" href="{callback_url}">Continue to AuthenTra</a>
      </div>
    </body>
    </html>"""
    return HTMLResponse(content=html)

# ==================== Email Verification & Institution Status ====================

class VerifyEmailRequest(BaseModel):
    email: str
    token: str | None = None
    code: str | None = None

class ResendEmailRequest(BaseModel):
    email: str

@app.post("/api/auth/verify-email")
def verify_institution_email(body: VerifyEmailRequest):
    token_or_code = body.token or body.code
    if not token_or_code:
        raise HTTPException(422, "Supply verification code or token.")
    success = email_verification.verify_email_token(body.email, token_or_code)
    if not success:
        raise HTTPException(400, "Invalid or expired verification code or token.")
    return {"ok": True, "message": "Email ownership verified successfully."}

@app.post("/api/auth/resend-verification")
def resend_institution_verification(body: ResendEmailRequest):
    data = email_verification.create_email_verification(body.email)
    res = {"ok": True, "message": "A new verification code has been generated."}
    if DEMO:
        res["demo_code"] = data["code"]
        res["demo_token"] = data["token"]
    return res

@app.get("/api/auth/institution-status")
def institution_status(email: str):
    clean_email = email.strip().lower()
    with connect() as conn:
        inst = conn.execute("SELECT * FROM users WHERE lower(email)=? AND role IN ('INSTITUTION_ADMIN', 'institution')", (clean_email,)).fetchone()
    if not inst:
        return {"exists": False}
    return {
        "exists": True,
        "name": inst["name"],
        "email": inst["email"],
        "domain": inst["institution_domain"],
        "approval_status": inst["approval_status"],
        "email_verified": bool(inst["email_verified"]),
        "wallet": inst["wallet"],
        "created_at": inst["created_at"],
    }

class AddDomainRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=2, max_length=150)

@app.get("/api/institutions/domains")
def list_institution_domains(user: User):
    role(user, ROLE_SYSTEM_ADMIN)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT domain, name, verified, created_at FROM institution_domains ORDER BY domain")]
    return rows

@app.post("/api/institutions/domains", status_code=201)
def add_institution_domain(body: AddDomainRequest, user: User, request: Request):
    role(user, ROLE_SYSTEM_ADMIN)
    clean_domain = body.domain.strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
    with connect() as conn:
        conn.execute(
            "INSERT INTO institution_domains(domain, name, verified) VALUES(?, ?, 1) ON CONFLICT(domain) DO UPDATE SET name=excluded.name, verified=1",
            (clean_domain, body.name.strip())
        )
        ip = request.client.host if request.client else "local"
        audit(conn, user["id"], "add_institution_domain", reference=clean_domain, details=f"Added domain {clean_domain} ({body.name.strip()})", ip_address=ip)
    return {"ok": True, "domain": clean_domain, "name": body.name.strip()}

@app.get("/api/health")
def health():
    try:
        chain = Registry()
        connected = chain.health()
        address = chain.contract.address
        net_info = chain.get_network_info()
    except Exception:
        connected, address, net_info = False, None, {"network_name": "Local development · chain 1337" if DEMO else "Configured Ethereum network", "chain_id": 1337 if DEMO else None}
    return {
        "status": "ready" if connected else "degraded",
        "blockchain": connected,
        "network": net_info["network_name"],
        "chain_id": net_info.get("chain_id"),
        "contract": address,
        "demo": DEMO,
        "model": (ROOT / ".local/model.joblib").exists()
    }

@app.get("/api/dashboard")
def dashboard(user: User):
    canonical = canonical_role(user["role"])
    with connect() as conn:
        if canonical == ROLE_SYSTEM_ADMIN:
            total_inst = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('INSTITUTION_ADMIN','institution')").fetchone()[0]
            pending_inst = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('INSTITUTION_ADMIN','institution') AND approval_status='PENDING_APPROVAL'").fetchone()[0]
            approved_inst = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('INSTITUTION_ADMIN','institution') AND approval_status='APPROVED'").fetchone()[0]
            suspended_inst = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('INSTITUTION_ADMIN','institution') AND approval_status IN ('SUSPENDED','REVOKED')").fetchone()[0]
            total_regs = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
            total_verifs = conn.execute("SELECT COUNT(*) FROM verifications").fetchone()[0]
            recent_audits = [dict(r) for r in conn.execute(
                "SELECT a.*, u.name AS actor, u.email AS actor_email FROM audit a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 5"
            )]
            recent_regs = [dict(r) for r in conn.execute(
                "SELECT r.*, u.name AS issuer_name FROM registrations r JOIN users u ON u.id=r.issuer_id ORDER BY r.created_at DESC LIMIT 5"
            )]
            return {
                "role": ROLE_SYSTEM_ADMIN,
                "total": total_verifs,
                "registered": total_regs,
                "total_institutions": total_inst,
                "pending_institutions": pending_inst,
                "approved_institutions": approved_inst,
                "suspended_institutions": suspended_inst,
                "recent_audits": recent_audits,
                "recent_registrations": recent_regs,
                "recent": [],
                "verified": 0,
                "review": 0,
                "issuer_approved": None
            }
        elif canonical == ROLE_INSTITUTION_ADMIN:
            checks = [dict(r) for r in conn.execute("SELECT * FROM verifications WHERE user_id=? ORDER BY id DESC", (user["id"],))]
            count = conn.execute("SELECT COUNT(*) FROM registrations WHERE issuer_id=?", (user["id"],)).fetchone()[0]
            approved = None
            try:
                approved = registry().approved(user["wallet"])
            except Exception:
                pass
            recent_regs = [dict(r) for r in conn.execute(
                "SELECT * FROM registrations WHERE issuer_id=? ORDER BY created_at DESC LIMIT 5", (user["id"],)
            )]
            durations = sorted(r["duration_ms"] for r in checks if r["duration_ms"] is not None)
            return {
                "role": ROLE_INSTITUTION_ADMIN,
                "total": len(checks),
                "registered": count,
                "recent_registrations": recent_regs,
                "issuer_approved": approved,
                "approval_status": user.get("approval_status"),
                "wallet": user.get("wallet"),
                "institution_name": user.get("name"),
                "recent": checks[:5],
                "verified": sum(r["status"] == "verified" for r in checks),
                "review": sum(r["status"] != "verified" for r in checks),
                "mean_ms": round(sum(durations) / len(durations)) if durations else None,
                "p95_ms": round(durations[max(0, int(len(durations) * .95 + .999) - 1)]) if durations else None,
            }
        else: # USER
            checks = [dict(r) for r in conn.execute("SELECT * FROM verifications WHERE user_id=? ORDER BY id DESC", (user["id"],))]
            durations = sorted(r["duration_ms"] for r in checks if r["duration_ms"] is not None)
            return {
                "role": ROLE_USER,
                "total": len(checks),
                "verified": sum(r["status"] == "verified" for r in checks),
                "review": sum(r["status"] != "verified" for r in checks),
                "registered": 0,
                "mean_ms": round(sum(durations) / len(durations)) if durations else None,
                "p95_ms": round(durations[max(0, int(len(durations) * .95 + .999) - 1)]) if durations else None,
                "recent": checks[:5],
                "issuer_approved": None
            }

@app.get("/api/history")
@app.get("/api/verifications")
def history(user: User):
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM verifications WHERE user_id=? ORDER BY id DESC LIMIT 500", (user["id"],))]

async def read_upload(file):
    try:
        data = await file.read(MAX_BYTES + 1)
        kind = await run_in_threadpool(uploads.validate_file, data, file.filename, file.content_type)
        return data, kind
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        await file.close()

def process_verification(data, kind, supplied_reference, user):
    start = time.perf_counter()
    digest = hashlib.sha256(data).hexdigest().lower()
    analysis = analyze(data, kind)
    extracted = analysis["fields"]["reference"]
    checks = {"reference_found": False, "hash_matches": None, "issuer_approved": None, "active": None}
    record = None
    record_source = None
    authorized = False
    reference = None
    reg_row = None
    status = "inconclusive"
    verification_status = "INCONCLUSIVE"
    category = "NOT_REGISTERED_OR_INCONCLUSIVE"
    message = "A readable certificate reference could not be detected. Confirm the reference from the issuing institution and try again."
    hash_matches = None
    hash_comparison = "No registered hash available for comparison"
    hash_comparison_result = "NOT_COMPARED"

    chain = None
    try:
        chain = registry()
        # 1. Primary lookup: query by exact normalized SHA-256 file hash
        if hasattr(chain, "lookup_by_hash"):
            record = chain.lookup_by_hash(digest)
            if record:
                record_source = "hash"

        # 2. If found directly by file hash on-chain
        if record is not None:
            if supplied_reference:
                try:
                    reference = normalize_reference(supplied_reference)
                except ValueError:
                    reference = None
            elif extracted:
                try:
                    reference = normalize_reference(extracted)
                except ValueError:
                    reference = None

            with connect() as conn:
                reg_row = conn.execute("SELECT * FROM registrations WHERE lower(file_hash)=lower(?)", (digest,)).fetchone()
                if not reg_row and reference:
                    reg_row = conn.execute("SELECT * FROM registrations WHERE reference=?", (reference,)).fetchone()
                if not reg_row and record.get("reference_hash"):
                    for r in conn.execute("SELECT * FROM registrations").fetchall():
                        try:
                            if reference_hash(r["reference"]).hex().lower() == record["reference_hash"]:
                                reg_row = r
                                break
                        except Exception:
                            continue
            if not reference and reg_row:
                reference = reg_row["reference"]

            try:
                authorized = chain.approved(record["issuer"])
            except Exception:
                authorized = False

            if record["revoked"]:
                status = "revoked"
                verification_status = "REVOKED"
                category = "REVOKED"
                message = "The issuer or platform owner has revoked this certificate."
            elif not authorized:
                status = "not_verified"
                verification_status = "ISSUER_NOT_AUTHORIZED"
                category = "ISSUER_NOT_AUTHORIZED"
                message = "The issuing institution is not currently approved."
            else:
                status = "verified"
                verification_status = "VERIFIED"
                category = "VERIFIED"
                message = "Registered and unchanged. The file matches the registered hash, the issuer is approved, and the record is active."

            checks = {
                "reference_found": True,
                "hash_matches": True,
                "issuer_approved": authorized,
                "active": not record["revoked"]
            }
            hash_matches = True
            hash_comparison = "Exact match between uploaded file hash and registered on-chain hash"
            hash_comparison_result = "MATCH"

        else:
            # 3. Not found by exact hash. Check if reference is available to detect tampering or unregistered status.
            ref_candidate = supplied_reference or extracted or ""
            ref_norm = None
            if ref_candidate:
                try:
                    ref_norm = normalize_reference(ref_candidate)
                except ValueError:
                    ref_norm = None

            if ref_norm:
                reference = ref_norm
                if supplied_reference and extracted and reference != extracted.upper():
                    analysis["warnings"].append("The entered certificate ID differs from the extracted ID. This result applies to the entered ID.")
                ref_record = chain.lookup(reference)
                if ref_record is not None:
                    record = ref_record
                    record_source = "reference"
                    with connect() as conn:
                        reg_row = conn.execute("SELECT * FROM registrations WHERE reference=?", (reference,)).fetchone()
                    try:
                        authorized = chain.approved(record["issuer"])
                    except Exception:
                        authorized = False

                    if record["revoked"]:
                        status = "revoked"
                        verification_status = "REVOKED"
                        category = "REVOKED"
                        message = "The issuer or platform owner has revoked this certificate."
                    elif not authorized:
                        status = "not_verified"
                        verification_status = "ISSUER_NOT_AUTHORIZED"
                        category = "ISSUER_NOT_AUTHORIZED"
                        message = "The issuing institution is not currently approved."
                    elif record["file_hash"].lower() == digest.lower():
                        status = "verified"
                        verification_status = "VERIFIED"
                        category = "VERIFIED"
                        message = "Registered and unchanged. The file matches the registered hash, the issuer is approved, and the record is active."
                        checks = {
                            "reference_found": True,
                            "hash_matches": True,
                            "issuer_approved": authorized,
                            "active": not record["revoked"]
                        }
                        hash_matches = True
                        hash_comparison = "Exact match between uploaded file hash and registered on-chain hash"
                        hash_comparison_result = "MATCH"
                    else:
                        status = "possible_tampering"
                        verification_status = "TAMPERING_DETECTED"
                        category = "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
                        message = "This file differs from the registered original. Re-saving, re-exporting, compression, and rescanning also change file bytes. Verify the original issued file."
                        checks = {
                            "reference_found": True,
                            "hash_matches": False,
                            "issuer_approved": authorized,
                            "active": not record["revoked"]
                        }
                        hash_matches = False
                        hash_comparison = "Uploaded file hash differs from registered on-chain hash (possible tampering, re-export, or rescan)"
                        hash_comparison_result = "MISMATCH"
                else:
                    status = "not_registered"
                    verification_status = "NOT_REGISTERED"
                    category = "NOT_REGISTERED_OR_INCONCLUSIVE"
                    message = "No registration exists for the supplied certificate reference. This does not prove that the document is forged."
                    checks = {"reference_found": False, "hash_matches": None, "issuer_approved": None, "active": None}
                    hash_matches = None
                    hash_comparison = "No registered hash available for comparison"
                    hash_comparison_result = "NOT_COMPARED"
            else:
                reference = None
                status = "inconclusive"
                verification_status = "INCONCLUSIVE"
                category = "NOT_REGISTERED_OR_INCONCLUSIVE"
                message = "A readable certificate reference could not be detected. Confirm the reference from the issuing institution and try again."
                checks = {"reference_found": False, "hash_matches": None, "issuer_approved": None, "active": None}
                hash_matches = None
                hash_comparison = "No registered hash available for comparison"
                hash_comparison_result = "NOT_COMPARED"

    except Exception:
        status = "unable_to_authenticate"
        verification_status = "VERIFICATION_UNAVAILABLE"
        category = "VERIFICATION_UNAVAILABLE"
        message = "The blockchain registry could not be reached. Please retry when the service is available."
        checks = {"reference_found": None, "hash_matches": None, "issuer_approved": None, "active": None}
        hash_matches = None
        hash_comparison = "Blockchain registry unavailable for hash verification"
        hash_comparison_result = "NOT_COMPARED"

    elapsed = round((time.perf_counter() - start) * 1000, 1)
    verified_at = datetime.now(timezone.utc).isoformat()

    # Determine blockchain record status
    if category == "VERIFICATION_UNAVAILABLE":
        blockchain_record_status = "UNAVAILABLE"
    elif record is None:
        blockchain_record_status = "NOT_FOUND"
    elif record["revoked"]:
        blockchain_record_status = "REVOKED"
    elif not authorized:
        blockchain_record_status = "ISSUER_UNAUTHORIZED"
    else:
        blockchain_record_status = "ACTIVE"

    # Network information
    fallback_addr = getattr(getattr(chain, "contract", None), "address", "0x0") if chain else "0x0"
    try:
        net_info = chain.get_network_info() if chain else {"chain_id": 1337, "network_name": "Local development · chain 1337", "contract_address": fallback_addr}
    except Exception:
        net_info = {"chain_id": 1337, "network_name": "Local development · chain 1337", "contract_address": fallback_addr}

    chain_id = net_info.get("chain_id", 1337)
    network_name = net_info.get("network_name", "Local development · chain 1337")
    contract_address = net_info.get("contract_address") or fallback_addr

    # Registered metadata from database
    issuer_name = None
    reg_tx = None
    block_number = None
    reg_date = None
    explorer_url = None

    reg_dict = dict(reg_row) if reg_row else {}
    if reg_dict:
        reg_tx = reg_dict.get("transaction_hash")
        block_number = reg_dict.get("block_number")
        reg_date = reg_dict.get("registered_at")
        if reg_dict.get("metadata"):
            try:
                meta = json.loads(reg_dict["metadata"])
                if isinstance(meta, dict):
                    if not analysis["fields"].get("name") and meta.get("recipient_name"):
                        analysis["fields"]["name"] = meta["recipient_name"]
                    if not analysis["fields"].get("course") and meta.get("course"):
                        analysis["fields"]["course"] = meta["course"]
                    if not analysis["fields"].get("institution") and meta.get("institution_name"):
                        analysis["fields"]["institution"] = meta["institution_name"]
                    if not analysis["fields"].get("issue_date") and meta.get("issue_date"):
                        analysis["fields"]["issue_date"] = meta["issue_date"]
            except Exception:
                pass

    if record:
        if not reg_date and record.get("registered_at"):
            reg_date = str(record["registered_at"])
        with connect() as conn:
            issuer_row = conn.execute("SELECT name FROM users WHERE lower(wallet)=lower(?)", (record["issuer"],)).fetchone()
            if issuer_row:
                issuer_name = issuer_row["name"]
            else:
                issuer_name = f"Wallet {record['issuer'][:8]}...{record['issuer'][-6:]}"
            if not reg_tx and reference:
                r_row = conn.execute("SELECT transaction_hash, block_number FROM registrations WHERE reference=?", (reference,)).fetchone()
                if r_row:
                    reg_tx = r_row["transaction_hash"]
                    block_number = r_row["block_number"]
        if reg_tx and chain and hasattr(chain, "get_explorer_url"):
            try:
                explorer_url = chain.get_explorer_url(reg_tx)
            except Exception:
                explorer_url = None

    # Detect discrepancies between DB record and on-chain record
    if record and reg_dict and reg_dict.get("file_hash"):
        if reg_dict["file_hash"].lower() != record["file_hash"].lower():
            analysis["warnings"].append("Database file hash differs from trusted on-chain record. Immutable blockchain record takes precedence.")

    next_action = CATEGORY_ACTIONS.get(category, "Review the result details and consult the issuing institution.")

    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO verifications(user_id,reference,status,category,file_hash,registered_hash,issuer,checks,message,duration_ms,ai_status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"], reference, status, category, digest, record["file_hash"] if record else None,
             record["issuer"] if record else None, json.dumps(checks), message, elapsed, analysis["ai"]["status"])
        )
        check_id = cursor.lastrowid

    reason = message if verification_status in ("NOT_REGISTERED", "INCONCLUSIVE", "VERIFICATION_UNAVAILABLE", "TAMPERING_DETECTED", "ISSUER_NOT_AUTHORIZED") else None

    return {
        "id": check_id,
        "reference": reference,
        "status": status,
        "verification_status": verification_status,
        "category": category,
        "label": LABELS.get(verification_status, LABELS.get(category, LABELS.get(status, status))),
        "message": message,
        "next_action": next_action,
        "reason": reason,
        "recipient_name": analysis["fields"].get("name"),
        "course": analysis["fields"].get("course"),
        "institution": analysis["fields"].get("institution") or issuer_name,
        "issue_date": analysis["fields"].get("issue_date"),
        "registered_at": reg_date,
        "file_hash": digest,
        "registered_hash": record["file_hash"] if record else None,
        "hash_matches": hash_matches,
        "hash_comparison": hash_comparison,
        "hash_comparison_result": hash_comparison_result,
        "issuer": record["issuer"] if record else None,
        "issuer_name": issuer_name,
        "issuer_authorized": authorized if record else None,
        "blockchain_record_status": blockchain_record_status,
        "chain_id": chain_id,
        "network": str(chain_id),
        "network_name": network_name,
        "contract_address": contract_address,
        "transaction_hash": reg_tx,
        "block_number": block_number,
        "explorer_url": explorer_url,
        "ocr_confidence": analysis.get("ocr_confidence"),
        "extraction_method": analysis.get("extraction_method"),
        "verified_at": verified_at,
        "checks": checks,
        "duration_ms": elapsed,
        **analysis,
    }

@app.post("/api/verify")
async def verify(user: User, file: UploadFile = File(...), reference: str = Form("")):
    if canonical_role(user["role"]) == ROLE_SYSTEM_ADMIN:
        raise HTTPException(403, "System administrators do not have certificate upload or verification permissions.")
    try:
        data, kind = await read_upload(file)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        now_iso = datetime.now(timezone.utc).isoformat()
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO verifications(user_id,reference,status,category,file_hash,registered_hash,issuer,checks,message,duration_ms,ai_status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (user["id"], None, "unable_to_authenticate", "INVALID_FILE", None, None, None,
                 json.dumps({"reference_found": False, "hash_matches": None, "issuer_approved": None, "active": None}),
                 exc.detail, 0.0, "unavailable")
            )
            check_id = cursor.lastrowid
        return {
            "id": check_id,
            "reference": None,
            "status": "unable_to_authenticate",
            "verification_status": "INVALID_FILE",
            "category": "INVALID_FILE",
            "label": "Invalid File",
            "message": exc.detail,
            "next_action": "Ensure the file is an unencrypted, valid PDF, PNG, or JPEG under the maximum size limit and try again.",
            "reason": exc.detail,
            "recipient_name": None,
            "course": None,
            "institution": None,
            "issue_date": None,
            "registered_at": None,
            "checks": {"reference_found": False, "hash_matches": None, "issuer_approved": None, "active": None},
            "ai": {"status": "unavailable", "label": "AI analysis unavailable", "score": None},
            "warnings": [],
            "fields": {"reference": None, "name": None, "course": None, "institution": None, "issue_date": None, "date_valid": False},
            "file_hash": None,
            "registered_hash": None,
            "hash_matches": None,
            "hash_comparison": "Cannot hash invalid file",
            "hash_comparison_result": "NOT_COMPARED",
            "issuer": None,
            "issuer_name": None,
            "issuer_authorized": None,
            "blockchain_record_status": "NOT_CHECKED",
            "chain_id": 1337,
            "network": "1337",
            "network_name": "Local development · chain 1337",
            "contract_address": None,
            "transaction_hash": None,
            "block_number": None,
            "explorer_url": None,
            "ocr_confidence": None,
            "extraction_method": None,
            "verified_at": now_iso,
            "duration_ms": 0.0,
        }
    return await run_in_threadpool(process_verification, data, kind, reference, user)

REGISTRATION_LOCK = threading.Lock()


def register_document(data, kind, reference, user, metadata_override=None):
    # Serialize duplicate checks and submission across legacy single uploads and queued jobs.
    with REGISTRATION_LOCK:
        with connect() as conn:
            latest = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if latest is None:
            raise HTTPException(403, "The account is no longer available.")
        ensure_active(latest)
        return _register_document(data, kind, reference, dict(latest), metadata_override=metadata_override)


def _register_document(data, kind, reference, user, metadata_override=None):
    role(user, "institution")
    ensure_active(user)
    digest = hashlib.sha256(data).hexdigest().lower()
    if metadata_override and isinstance(metadata_override, dict):
        fields = metadata_override
        ocr_confidence = metadata_override.get("ocr_confidence")
        extraction_method = metadata_override.get("extraction_method") or "Verified by Institution Admin"
    else:
        analysis = analyze(data, kind)
        fields = analysis.get("fields", {})
        ocr_confidence = analysis.get("ocr_confidence")
        extraction_method = analysis.get("extraction_method")

    ref_candidate = reference.strip() if reference else fields.get("reference")
    if not ref_candidate:
        raise HTTPException(422, "A certificate reference is required.")
    try:
        reference = normalize_reference(ref_candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    chain = registry()
    try:
        if not chain.approved(user["wallet"]):
            raise HTTPException(403, "Your institution must be approved before registering certificates.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"The blockchain is unavailable: {exc}") from exc

    network_info = chain.get_network_info()
    metadata_json = json.dumps({
        "recipient_name": fields.get("name") or fields.get("recipient_name"),
        "institution_name": fields.get("institution") or fields.get("institution_name") or user["name"],
        "course": fields.get("course") or fields.get("qualification"),
        "issue_date": fields.get("issue_date"),
        "ocr_confidence": ocr_confidence,
        "extraction_method": extraction_method,
        "missing_fields": fields.get("missing_fields", []),
        "ambiguous_fields": fields.get("ambiguous_fields", []),
    })

    # Idempotent checks in local database
    with connect() as conn:
        existing_ref = conn.execute("SELECT * FROM registrations WHERE reference=?", (reference,)).fetchone()
        if existing_ref:
            if existing_ref["file_hash"].lower() == digest and existing_ref["issuer_id"] == user["id"]:
                on_chain = chain.lookup(reference)
                if on_chain and on_chain["file_hash"].lower() == digest and on_chain["issuer"].lower() == user["wallet"].lower() and not on_chain["revoked"]:
                    audit(conn, user["id"], "register_idempotent", reference, existing_ref["transaction_hash"])
                    return {
                        "reference": reference,
                        "file_hash": digest,
                        "status": "registered",
                        "registration_status": "REGISTERED_ON_BLOCKCHAIN",
                        "transaction_hash": existing_ref["transaction_hash"],
                        "block_number": existing_ref["block_number"],
                        "gas_used": existing_ref["gas_used"],
                        "fee_wei": existing_ref["fee_wei"],
                        "network": existing_ref["network"],
                        "contract_address": existing_ref["contract_address"],
                        "registered_at": existing_ref["registered_at"],
                        "explorer_url": chain.get_explorer_url(existing_ref["transaction_hash"]),
                        "fields": fields,
                        "ocr_confidence": ocr_confidence,
                        "on_chain_verified": True,
                        "idempotent": True,
                    }
                elif on_chain is None:
                    # Database record exists from prior session, but not yet present on active blockchain.
                    # Proceed to register on-chain and sync the database record.
                    pass
                else:
                    raise HTTPException(409, "This certificate ID already exists on the blockchain with different parameters.")
            else:
                dup_file = conn.execute("SELECT reference FROM registrations WHERE issuer_id=? AND file_hash=? AND reference != ?", (user["id"], digest, reference)).fetchone()
                if dup_file:
                    raise HTTPException(409, f"This file is already registered by your institution under ID {dup_file['reference']}.")
                raise HTTPException(409, "This certificate ID already exists. IDs cannot be overwritten or reused.")

        dup_file = conn.execute("SELECT reference FROM registrations WHERE issuer_id=? AND file_hash=? AND reference != ?", (user["id"], digest, reference)).fetchone()
        if dup_file:
            raise HTTPException(409, f"This file is already registered by your institution under ID {dup_file['reference']}.")

    # Check on-chain lookup
    on_chain = chain.lookup(reference)
    if on_chain:
        if on_chain["file_hash"].lower() == digest and on_chain["issuer"].lower() == user["wallet"].lower() and not on_chain["revoked"]:
            # On-chain already exists with exact parameters; record locally
            with connect() as conn:
                conn.execute("""
                    INSERT INTO registrations(
                        reference, issuer_id, file_hash, transaction_hash, gas_used, fee_wei,
                        network, contract_address, block_number, registered_at, status, metadata
                    ) VALUES(?, ?, ?, '0xidempotent', 0, '0', ?, ?, NULL, ?, 'REGISTERED_ON_BLOCKCHAIN', ?)
                    ON CONFLICT(reference) DO UPDATE SET status='REGISTERED_ON_BLOCKCHAIN'
                """, (reference, user["id"], digest, str(network_info["chain_id"]), chain.contract.address, str(on_chain["registered_at"]), metadata_json))
                audit(conn, user["id"], "register_idempotent", reference, None)
            return {
                "reference": reference,
                "file_hash": digest,
                "status": "registered",
                "registration_status": "REGISTERED_ON_BLOCKCHAIN",
                "transaction_hash": None,
                "network": str(network_info["chain_id"]),
                "contract_address": chain.contract.address,
                "registered_at": on_chain["registered_at"],
                "fields": fields,
                "ocr_confidence": ocr_confidence,
                "on_chain_verified": True,
                "idempotent": True,
            }
        else:
            raise HTTPException(409, "This certificate ID already exists on the blockchain with different parameters.")

    # Real blockchain transaction + read-back verification
    transaction = safe_chain_action(lambda: chain.register_and_verify(reference, digest, user["wallet"]))
    if not transaction.get("on_chain_verified"):
        raise HTTPException(500, "On-chain verification could not confirm the certificate registration.")

    tx_hash = transaction.get("transaction_hash")
    with connect() as conn:
        conn.execute("""
            INSERT INTO registrations(
                reference, issuer_id, file_hash, transaction_hash, gas_used, fee_wei,
                network, contract_address, block_number, registered_at, status, metadata
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'REGISTERED_ON_BLOCKCHAIN', ?)
            ON CONFLICT(reference) DO UPDATE SET
                file_hash=excluded.file_hash,
                transaction_hash=excluded.transaction_hash,
                status='REGISTERED_ON_BLOCKCHAIN',
                metadata=excluded.metadata
        """, (
            reference, user["id"], digest, tx_hash or "0xconfirmed", transaction.get("gas_used"),
            transaction.get("fee_wei"), str(network_info["chain_id"]), transaction.get("contract_address") or chain.contract.address,
            transaction.get("block_number"), str(transaction.get("registered_at")), metadata_json
        ))
        audit(conn, user["id"], "register_confirmed", reference, tx_hash)

    explorer_url = chain.get_explorer_url(tx_hash)
    return {
        "reference": reference,
        "file_hash": digest,
        "status": "registered",
        "registration_status": "REGISTERED_ON_BLOCKCHAIN",
        "transaction_hash": tx_hash,
        "block_number": transaction.get("block_number"),
        "gas_used": transaction.get("gas_used"),
        "fee_wei": transaction.get("fee_wei"),
        "network": str(network_info["chain_id"]),
        "network_name": network_info["network_name"],
        "contract_address": transaction.get("contract_address") or chain.contract.address,
        "registered_at": transaction.get("registered_at"),
        "explorer_url": explorer_url,
        "fields": fields,
        "ocr_confidence": ocr_confidence,
        "on_chain_verified": True,
    }

@app.post("/api/certificates", status_code=201)
async def register(user: User, file: UploadFile = File(...), reference: str = Form(...)):
    role(user, ROLE_INSTITUTION_ADMIN)
    data, kind = await read_upload(file)
    return await run_in_threadpool(register_document, data, kind, reference, user)

def require_issuer(user):
    role(user, ROLE_INSTITUTION_ADMIN)
    if not registry().approved(user["wallet"]):
        raise HTTPException(403, "Your institution must be approved on the blockchain before uploading certificates.")


@app.get("/api/uploads/limits")
def upload_limits(user: User, mode: Literal["verify", "register"] = "verify"):
    canon = canonical_role(user["role"])
    if canon == ROLE_SYSTEM_ADMIN:
        raise HTTPException(403, "System administrators do not have certificate upload permissions.")
    if mode == "register":
        role(user, ROLE_INSTITUTION_ADMIN)
        require_issuer(user)
    elif canon == ROLE_USER and mode != "verify":
        raise HTTPException(403, "Users cannot register certificates on the blockchain.")

    # Role-specific limits: five-file limit applies ONLY to ordinary USER accounts per batch.
    # It must NOT apply to INSTITUTION_ADMIN accounts.
    if canon == ROLE_USER:
        max_files = uploads.USER_FILES  # 5
        max_batch_bytes = uploads.USER_FILES * MAX_BYTES
    else:
        max_files = uploads.BULK_FILES  # Configurable institutional bulk limit (default 100)
        max_batch_bytes = uploads.BULK_BYTES

    return {
        "max_files": max_files,
        "max_file_bytes": MAX_BYTES,
        "max_batch_bytes": max_batch_bytes,
        "role": canon
    }


@app.get("/api/uploads")
def recent_uploads(user: User, mode: Literal["verify", "register"] = "verify"):
    with connect() as conn:
        jobs = conn.execute("SELECT id FROM upload_jobs WHERE user_id=? AND mode=? ORDER BY created_at DESC,rowid DESC LIMIT 10", (user["id"], mode)).fetchall()
    return [uploads.snapshot(job["id"], user) for job in jobs]

@app.post("/api/uploads", status_code=202)
async def upload_batch(user: User, files: list[UploadFile] = File(...), references: str = Form("[]"), mode: str = Form("verify")):
    canon = canonical_role(user["role"])
    if canon == ROLE_SYSTEM_ADMIN:
        raise HTTPException(403, "System administrators do not have certificate upload or registration permissions.")
    if mode not in ("verify", "register"):
        raise HTTPException(422, "Choose verification or registration.")
    if mode == "register":
        role(user, ROLE_INSTITUTION_ADMIN)
        await run_in_threadpool(require_issuer, user)
    elif canon == ROLE_USER and mode != "verify":
        raise HTTPException(403, "Users cannot register certificates on the blockchain.")

    # Role-specific limits: five-file limit applies ONLY to ordinary USER accounts per batch.
    # It must NOT apply to INSTITUTION_ADMIN accounts.
    if canon == ROLE_USER:
        limit = uploads.USER_FILES  # 5
        batch_bytes_limit = uploads.USER_FILES * MAX_BYTES
    else:
        limit = uploads.BULK_FILES  # Configurable institutional bulk limit (default 100)
        batch_bytes_limit = uploads.BULK_BYTES

    try:
        if not 1 <= len(files) <= limit:
            if canon == ROLE_USER:
                raise HTTPException(422, f"Users can upload a maximum of {uploads.USER_FILES} certificate files per batch. Remove extra files to continue.")
            else:
                raise HTTPException(422, f"Institutions can upload between 1 and {limit} files per batch.")
        try:
            ids = json.loads(references)
            if ids == [] and mode == "verify":
                ids = [""] * len(files)
            if not isinstance(ids, list) or len(ids) != len(files) or not all(isinstance(v, str) and len(v) <= 64 for v in ids):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "Supply one certificate reference per file.")
        items, total = [], 0
        for file, reference in zip(files, ids):
            data = await file.read(MAX_BYTES + 1)
            total += len(data)
            if total > batch_bytes_limit:
                raise HTTPException(413, "The batch exceeds its total size limit. No files were queued.")
            kind, error = None, None
            try:
                kind = await run_in_threadpool(uploads.validate_file, data, file.filename, file.content_type)
                if mode == "register" or reference.strip():
                    reference = normalize_reference(reference)
            except ValueError as exc:
                error = str(exc)
            items.append(((file.filename or "Unnamed file")[:255], reference, data, kind, error))
        job = await run_in_threadpool(uploads.create_job, user, mode, items)
        return await run_in_threadpool(uploads.snapshot, job, user)
    finally:
        for file in files:
            await file.close()

@app.post("/api/certificates/bulk", status_code=202)
async def bulk(user: User, files: list[UploadFile] = File(...), references: str = Form(...)):
    role(user, ROLE_INSTITUTION_ADMIN)
    return await upload_batch(user, files, references, "register")

@app.get("/api/uploads/{job}")
def upload_status(job: str, user: User):
    return uploads.snapshot(job, user)

@app.get("/api/uploads/{job}/report")
def upload_report(job: str, user: User):
    batch = uploads.snapshot(job, user)
    return Response(uploads.csv_report(batch), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="authentra-batch-{batch["id"]}.csv"'})

class ReviewAction(BaseModel):
    action: Literal["approve", "reject"]
    reference: str = ""
    name: str | None = None
    course: str | None = None
    institution: str | None = None
    issue_date: str | None = None

@app.post("/api/uploads/{job}/items/{item_id}/review")
def review_upload_item(job: str, item_id: int, body: ReviewAction, user: User):
    role(user, ROLE_INSTITUTION_ADMIN)
    return uploads.review_item(job, item_id, user, body.action, body.model_dump())

@app.post("/api/uploads/{job}/items/{item_id}/retry")
def retry_upload_item(job: str, item_id: int, user: User):
    role(user, ROLE_INSTITUTION_ADMIN)
    return uploads.retry_item(job, item_id, user)

@app.get("/api/certificates")
def certificates(user: User):
    canonical = canonical_role(user["role"])
    if canonical == ROLE_USER:
        raise HTTPException(403, "Your account is not authorized to view the certificate registry.")
    role(user, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT r.*, u.name AS issuer_name FROM registrations r JOIN users u ON u.id=r.issuer_id" +
            (" WHERE issuer_id=?" if canonical == ROLE_INSTITUTION_ADMIN else "") +
            " ORDER BY created_at DESC",
            (user["id"],) if canonical == ROLE_INSTITUTION_ADMIN else ()
        )]
    chain = registry()
    for row in rows:
        record = chain.lookup(row["reference"])
        row["revoked"] = record["revoked"] if record else None
        row["issuer_approved"] = chain.approved(record["issuer"]) if record else None
        row["on_chain_verified"] = record is not None and record["file_hash"].lower() == row["file_hash"].lower()
        row["explorer_url"] = chain.get_explorer_url(row.get("transaction_hash"))
        if row.get("metadata"):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except Exception:
                pass
    return rows

@app.post("/api/certificates/{reference}/revoke")
def revoke(reference: str, user: User, request: Request):
    role(user, ROLE_INSTITUTION_ADMIN)
    try:
        reference = normalize_reference(reference)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    chain = registry()
    record = chain.lookup(reference)
    if not record:
        raise HTTPException(404, "Certificate not found.")
    if record["issuer"].lower() != user.get("wallet", "").lower():
        raise HTTPException(403, "Only the issuing institution can revoke this certificate.")
    transaction = safe_chain_action(lambda: chain.revoke(reference, user["wallet"]))
    ip = request.client.host if request.client else "local"
    with connect() as conn:
        audit(conn, user["id"], "revoke", reference, transaction["transaction_hash"], details=f"Certificate {reference} revoked by issuer {user.get('name')}", ip_address=ip)
    return {"status": "revoked", **transaction}

class Approval(BaseModel):
    approved: bool | None = None
    status: Literal["APPROVED", "REJECTED", "SUSPENDED", "REVOKED", "RESTORED"] | None = None
    reason: str | None = Field(default=None, max_length=1000)

class Institution(Signup):
    wallet: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    institution_reference: str = Field(min_length=3, max_length=200)
    verification_info: str = Field(min_length=10, max_length=2000)

@app.get("/api/institutions")
def institutions(user: User):
    role(user, ROLE_SYSTEM_ADMIN)
    with connect() as conn:
        rows = [public_user(r) for r in conn.execute("SELECT * FROM users WHERE role IN ('INSTITUTION_ADMIN','institution') ORDER BY id DESC")]
        chain = registry()
        for r in rows:
            r["approved"] = r["approval_status"] == "APPROVED" and chain.approved(r["wallet"])
            latest = conn.execute(
                "SELECT action, created_at FROM audit WHERE user_id=? OR reference=? ORDER BY id DESC LIMIT 1",
                (r["id"], r.get("wallet"))
            ).fetchone()
            if latest:
                act = latest["action"].replace("_", " ").capitalize()
                r["latest_activity"] = f"{act} ({latest['created_at']})"
                r["latest_activity_at"] = latest["created_at"]
            else:
                r["latest_activity"] = f"Application submitted ({r.get('created_at', '—')})"
                r["latest_activity_at"] = r.get("created_at")
    return rows

def create_institution(body):
    from web3 import Web3
    if not Web3.is_address(body.wallet) or int(body.wallet, 16) == 0 or len(body.password) < 12 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email.strip()) or len(body.name.strip()) < 2 or len(body.institution_reference.strip()) < 3 or len(body.verification_info.strip()) < 10:
        raise HTTPException(422, "Provide institution name, official email, registration reference, verification details, a nonzero wallet and a password of at least 12 characters.")
    wallet = Web3.to_checksum_address(body.wallet)
    valid_dom, clean_email, domain, domain_err = domains.validate_institution_domain(body.email)
    if not valid_dom:
        raise HTTPException(422, domain_err)

    ver_data = email_verification.create_email_verification(clean_email)
    with connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users(email,name,password,role,wallet,institution_reference,verification_info,approval_status,institution_domain,email_verified)
                VALUES(?,?,?,?,?,?,?,'PENDING_APPROVAL',?,0)
                """,
                (clean_email, body.name.strip(), password_hash(body.password), ROLE_INSTITUTION_ADMIN, wallet, body.institution_reference.strip(), body.verification_info.strip(), domain)
            )
            audit(conn, None, "institution_application", wallet, details=f"New institution application for {clean_email}")
        except sqlite3.IntegrityError:
            raise HTTPException(409, "This email or wallet is already registered.")
    res = {
        "message": "Application submitted. Your institution is PENDING_APPROVAL. An administrator must verify your details and configure your signer before approval.",
        "approval_status": "PENDING_APPROVAL",
        "institution_domain": domain,
        "email_verified": False,
        "verification_sent": True
    }
    if DEMO:
        res["demo_verification_code"] = ver_data["code"]
        res["demo_verification_token"] = ver_data["token"]
    return res

@app.post("/api/auth/institution-signup", status_code=201)
def institution_signup(body: Institution):
    return create_institution(body)

@app.post("/api/institutions", status_code=201)
def add_institution(body: Institution, user: User, request: Request):
    role(user, ROLE_SYSTEM_ADMIN)
    result = create_institution(body)
    ip = request.client.host if request.client else "local"
    with connect() as conn:
        audit(conn, user["id"], "add_institution", reference=body.wallet, details=f"Admin added institution {body.name.strip()}", ip_address=ip)
    return result

@app.post("/api/institutions/{institution_id}/approval")
def approve(institution_id: int, body: Approval, user: User, request: Request):
    role(user, ROLE_SYSTEM_ADMIN)
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=? AND role IN ('INSTITUTION_ADMIN','institution')", (institution_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Institution not found.")
    institution = dict(row)

    if user["id"] == institution_id or (user.get("wallet") and institution.get("wallet") and user.get("wallet", "").lower() == institution.get("wallet", "").lower()):
        raise HTTPException(403, "Institutions cannot approve or alter their own authorization.")

    status = body.status
    if status == "RESTORED":
        status = "APPROVED"
    elif not status and body.approved is not None:
        status = "APPROVED" if body.approved else "SUSPENDED"

    if status not in ("APPROVED", "REJECTED", "SUSPENDED", "REVOKED"):
        raise HTTPException(422, "Supply a valid approval status (APPROVED, REJECTED, SUSPENDED, REVOKED, or RESTORED).")

    reason = (body.reason or "").strip()
    if not reason:
        reason = f"Administrative decision by {user.get('email', 'admin')}: set status to {status}."

    chain = registry()
    approved = (status == "APPROVED")
    if approved and institution["wallet"] not in chain.keys:
        raise HTTPException(409, "Configure the institution server-side signer before approval.")

    transaction = safe_chain_action(lambda: chain.set_issuer(institution["wallet"], approved))

    ip = request.client.host if request.client else "local"
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status=?, review_notes=? WHERE id=?", (status, reason, institution_id))
        audit(
            conn,
            user["id"],
            "issuer_" + status.lower(),
            reference=institution["wallet"],
            transaction_hash=transaction.get("transaction_hash"),
            details=f"Admin {user['email']} set institution '{institution['name']}' (ID: {institution_id}) to {status}. Reason: {reason}",
            ip_address=ip
        )
    return {
        "approved": approved,
        "approval_status": status,
        "review_notes": reason,
        "institution_id": institution_id,
        "institution_name": institution["name"],
        **transaction
    }

@app.get("/api/admin/institutions/{institution_id}/history")
def admin_institution_history(institution_id: int, user: User):
    role(user, ROLE_SYSTEM_ADMIN)
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=? AND role IN ('INSTITUTION_ADMIN','institution')", (institution_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Institution not found.")
        inst = dict(row)
        inst_data = public_user(inst)
        chain = registry()
        wallet = inst.get("wallet")
        try:
            onchain_ok = chain.approved(wallet) if wallet else False
        except Exception:
            onchain_ok = False
        inst_data["onchain_approved"] = onchain_ok
        inst_data["approved"] = inst["approval_status"] == "APPROVED" and onchain_ok

        # Certificate registrations submitted by that institution
        registrations = [dict(r) for r in conn.execute(
            """
            SELECT r.*
            FROM registrations r
            WHERE r.issuer_id=?
            ORDER BY r.created_at DESC
            """,
            (institution_id,)
        )]
        for reg in registrations:
            rec = chain.lookup(reg["reference"])
            reg["revoked"] = rec["revoked"] if rec else False
            reg["on_chain_verified"] = rec is not None and rec["file_hash"].lower() == reg["file_hash"].lower()
            reg["explorer_url"] = chain.get_explorer_url(reg.get("transaction_hash"))
            reg["status_label"] = "REVOKED" if reg["revoked"] else ("ACTIVE" if reg["on_chain_verified"] else "UNVERIFIED")
            if reg.get("metadata"):
                try:
                    reg["metadata"] = json.loads(reg["metadata"])
                except Exception:
                    pass

        # Revocations, status changes, and relevant audit events
        audit_events = [dict(a) for a in conn.execute(
            """
            SELECT a.*, u.name AS actor_name, u.email AS actor_email
            FROM audit a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.user_id=? OR (a.reference IS NOT NULL AND a.reference=?) OR a.reference IN (SELECT reference FROM registrations WHERE issuer_id=?)
            ORDER BY a.id DESC LIMIT 200
            """,
            (institution_id, inst.get("wallet") or "", institution_id)
        )]
        for event in audit_events:
            tx = event.get("transaction_hash")
            event["explorer_url"] = chain.get_explorer_url(tx) if tx else None
            event["is_onchain"] = bool(tx)

        return {
            "institution": inst_data,
            "registrations": registrations,
            "audit_events": audit_events
        }

@app.get("/api/audit")
def audit_log(user: User):
    canonical = canonical_role(user["role"])
    if canonical == ROLE_USER:
        raise HTTPException(403, "Your account is not authorized for this action.")
    with connect() as conn:
        if canonical == ROLE_SYSTEM_ADMIN:
            return [dict(r) for r in conn.execute(
                """
                SELECT a.*, u.name AS actor, u.email AS actor_email, u.role AS actor_role
                FROM audit a
                LEFT JOIN users u ON a.user_id=u.id
                ORDER BY a.id DESC LIMIT 300
                """
            )]
        else:
            return [dict(r) for r in conn.execute(
                """
                SELECT a.*, u.name AS actor
                FROM audit a
                JOIN users u ON a.user_id=u.id
                WHERE a.user_id=?
                ORDER BY a.id DESC LIMIT 200
                """,
                (user["id"],)
            )]

@app.get("/api/admin/verifications")
def admin_verifications(
    user: User,
    date_from: str | None = None,
    date_to: str | None = None,
    result: str | None = None,
    user_id: str | None = None,
    reference: str | None = None
):
    role(user, ROLE_SYSTEM_ADMIN)
    chain = registry()
    query = """
        SELECT v.id, v.user_id, u.name AS user_name, u.email AS user_email,
               v.reference, v.status, v.category, v.file_hash, v.registered_hash,
               COALESCE(v.issuer, r_iss.wallet) AS issuer,
               COALESCE(iss.name, r_iss.name) AS issuer_name,
               r.transaction_hash,
               v.duration_ms, v.ai_status, v.message, v.created_at
        FROM verifications v
        LEFT JOIN users u ON u.id = v.user_id
        LEFT JOIN registrations r ON r.reference = v.reference
        LEFT JOIN users r_iss ON r_iss.id = r.issuer_id
        LEFT JOIN users iss ON lower(iss.wallet) = lower(v.issuer)
        WHERE 1=1
    """
    params = []
    if date_from:
        query += " AND v.created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND v.created_at <= ?"
        params.append(date_to + " 23:59:59" if len(date_to) == 10 else date_to)
    if result and result != "all":
        query += " AND (v.status = ? OR v.category = ?)"
        params.extend([result, result])
    if user_id:
        query += " AND (CAST(v.user_id AS TEXT) LIKE ? OR lower(u.email) LIKE ? OR lower(u.name) LIKE ?)"
        term = f"%{user_id.lower().strip()}%"
        params.extend([term, term, term])
    if reference:
        query += " AND lower(v.reference) LIKE ?"
        params.append(f"%{reference.lower().strip()}%")

    query += " ORDER BY v.id DESC LIMIT 500"

    with connect() as conn:
        rows = [dict(r) for r in conn.execute(query, params)]

    for row in rows:
        email_part = f" ({row['user_email']})" if row.get("user_email") else ""
        row["user_identifier"] = f"User #{row['user_id']}{email_part}" if row.get("user_id") else "Anonymous / Unauthenticated"
        row["explorer_url"] = chain.get_explorer_url(row.get("transaction_hash"))
        row["verification_timestamp"] = row.get("created_at")
        row["processing_outcome"] = row.get("category") or row.get("status")
        row["transaction_reference"] = row.get("transaction_hash")
        if not row.get("issuer_name") and row.get("issuer"):
            row["issuer_name"] = f"Wallet {row['issuer'][:8]}...{row['issuer'][-6:]}"
        if not row.get("message"):
            if row.get("category") == "VERIFIED":
                row["message"] = "Certificate verified and active on blockchain"
            elif row.get("category") == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH":
                row["message"] = "File hash does not match registered on-chain digest"
            elif row.get("category") == "REVOKED":
                row["message"] = "Certificate was revoked by the issuing authority"
            elif row.get("category") == "NOT_REGISTERED_OR_INCONCLUSIVE":
                row["message"] = "Certificate reference not found on the blockchain registry"
            elif row.get("category") == "INVALID_FILE":
                row["message"] = "Unsupported file format, corrupted payload, or unreadable document"
            elif row.get("category") == "ISSUER_NOT_AUTHORIZED":
                row["message"] = "Issuing institution is not authorized on the smart contract"
            else:
                row["message"] = "Verification could not be conclusively determined"
        row["failure_reason"] = row["message"] if row.get("category") != "VERIFIED" else None

    return rows

@app.get("/api/admin/certificates")
def admin_certificates(user: User):
    role(user, ROLE_SYSTEM_ADMIN)
    return certificates(user)

@app.get("/api/admin/audit")
def admin_audit(user: User):
    role(user, ROLE_SYSTEM_ADMIN)
    return audit_log(user)

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

from .upload_transport import UploadTransport
app.add_middleware(UploadTransport, authenticate=current_user)

if (ROOT / "dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
