"""Unit and Integration Tests for Two Separate Authentication Experiences in AuthenTra.

Tests:
- User Login: Google and Apple OAuth / OIDC (success, failure, CSRF state protection, replay prevention)
- Institution Login: Institutional email domain validation (.edu, .ac.in, .edu.in, .res.in vs. fake substrings and generic .in)
- Personal email rejection for institutions (@gmail.com, @yahoo.com, etc.)
- Email ownership verification (code & token)
- Pending institution approval boundary (denied registration & bulk upload; status view permitted)
- Approved institution access to bulk registration
- Ordinary user denied access to institutional endpoints
- Suspended institution denied registration & login
- Expired and tampered authentication tokens
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
import pytest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AUTHENTRA_DEMO"] = "1"
from fastapi.testclient import TestClient
import jwt
from backend import main, domains, email_verification, auth_oauth
from backend.storage import connect, initialize, password_hash


class MockTestRegistry:
    owner = "0x0000000000000000000000000000000000000001"
    keys = {
        owner: "key1",
        "0x0000000000000000000000000000000000000002": "key2",
        "0x0000000000000000000000000000000000000003": "key3",
        "0x0000000000000000000000000000000000000004": "key4",
    }
    approvals = {"0x0000000000000000000000000000000000000002": True}
    contract = type("Contract", (), {"address": "0x0000000000000000000000000000000000000000"})()

    def health(self):
        return True

    def approved(self, address):
        return self.approvals.get(address, False)

    def set_issuer(self, address, approved):
        self.approvals[address] = approved
        return {"transaction_hash": "0xapprovetx", "gas_used": 25000, "fee_wei": "1000", "block_number": 10}

    def get_network_info(self):
        return {"chain_id": 1337, "network_name": "Local development · chain 1337", "contract_address": self.contract.address, "explorer_template": None}

    def get_explorer_url(self, tx_hash):
        return None

    def lookup(self, reference):
        return None

    def register_and_verify(self, reference, file_hash, issuer):
        return {"transaction_hash": "0xregtx", "gas_used": 70000, "fee_wei": "2000", "block_number": 12, "registered_at": 1700000000, "contract_address": self.contract.address, "network": "1337", "on_chain_verified": True, "idempotent": False}


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_auth_exp.db"
    monkeypatch.setenv("AUTHENTRA_DB", str(db_path))
    monkeypatch.setattr(main, "Registry", MockTestRegistry)
    initialize()
    main.LOGIN_ATTEMPTS.clear()
    with TestClient(main.app) as client:
        yield client


# ==============================================================================
# 1. USER LOGIN: GOOGLE & APPLE OAUTH TESTS
# ==============================================================================

def test_oauth_providers_info(auth_client):
    """GET /api/auth/oauth/providers reports availability without exposing secrets."""
    res = auth_client.get("/api/auth/oauth/providers")
    assert res.status_code == 200
    data = res.json()
    assert "google" in data and "apple" in data
    assert data["google"]["name"] == "Google"
    assert data["apple"]["name"] == "Apple"
    # Ensure no secrets leaked
    assert "client_secret" not in json.dumps(data)
    assert "key_id" not in json.dumps(data)


def test_google_login_flow_success(auth_client):
    """Successful Google OAuth flow: state generation, anti-CSRF check, user provisioning as verifier."""
    # 1. Initiate OAuth to get auth URL and state
    url_res = auth_client.get("/api/auth/oauth/google/url")
    assert url_res.status_code == 200
    url_data = url_res.json()
    state = url_data["state"]
    assert len(state) >= 32

    # 2. Exchange code via callback
    test_code = "test:google:student@gmail.com:Sarah Connor:google_sub_987"
    exchange_res = auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": test_code, "state": state}
    )
    assert exchange_res.status_code == 200
    user_data = exchange_res.json()
    assert user_data["email"] == "student@gmail.com"
    assert user_data["name"] == "Sarah Connor"
    assert user_data["role"] in ("USER", "verifier")
    assert user_data["approval_status"] == "APPROVED"
    assert user_data["oauth_provider"] == "google"
    assert user_data["email_verified"] == 1

    # 3. Session cookie is set and grants access to user dashboard and verification
    me_res = auth_client.get("/api/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "student@gmail.com"


def test_apple_login_flow_success(auth_client):
    """Successful Apple OAuth flow: provisions verifier user with verified email."""
    url_res = auth_client.get("/api/auth/oauth/apple/url")
    assert url_res.status_code == 200
    state = url_res.json()["state"]

    test_code = "test:apple:designer@icloud.com:Apple Designer:apple_sub_654"
    exchange_res = auth_client.post(
        "/api/auth/oauth/apple/exchange",
        json={"code": test_code, "state": state}
    )
    assert exchange_res.status_code == 200
    user = exchange_res.json()
    assert user["email"] == "designer@icloud.com"
    assert user["role"] in ("USER", "verifier")
    assert user["oauth_provider"] == "apple"
    assert user["email_verified"] == 1


def test_oauth_state_csrf_protection_and_replay_failure(auth_client):
    """OAuth rejects missing, invalid, or replayed state tokens."""
    url_res = auth_client.get("/api/auth/oauth/google/url")
    state = url_res.json()["state"]

    # Invalid state
    bad_res = auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": "test:google:x@gmail.com:X:sub1", "state": "tampered-state-token"}
    )
    assert bad_res.status_code == 400
    assert "state" in bad_res.json()["detail"].lower()

    # Valid first exchange
    good_res = auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": "test:google:x@gmail.com:X:sub1", "state": state}
    )
    assert good_res.status_code == 200

    # Replay attack with same state must fail because state was consumed
    replay_res = auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": "test:google:x@gmail.com:X:sub1", "state": state}
    )
    assert replay_res.status_code == 400


def test_oauth_failure_on_invalid_code(auth_client):
    """OAuth returns error when authorization code is corrupt or provider rejects exchange."""
    url_res = auth_client.get("/api/auth/oauth/google/url")
    state = url_res.json()["state"]

    fail_res = auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": "invalid-corrupted-code", "state": state}
    )
    assert fail_res.status_code in (400, 401, 503)


# ==============================================================================
# 2. INSTITUTIONAL EMAIL DOMAIN VALIDATION TESTS
# ==============================================================================

@pytest.mark.parametrize("valid_email,expected_domain", [
    ("registrar@mit.edu", "mit.edu"),
    ("admin@stanford.edu", "stanford.edu"),
    ("credentials@iitb.ac.in", "iitb.ac.in"),
    ("dean@iitd.ac.in", "iitd.ac.in"),
    ("office@annauniv.edu.in", "annauniv.edu.in"),
    ("records@tifr.res.in", "tifr.res.in"),
    ("exam@ox.ac.uk", "ox.ac.uk"),
    ("verify@authentra.demo", "authentra.demo"),
])
def test_institutional_domain_validation_success(valid_email, expected_domain):
    """Accredited educational suffixes and allowlisted registry domains are accepted."""
    is_valid, email, domain, err = domains.validate_institution_domain(valid_email)
    assert is_valid is True, f"Expected {valid_email} to be valid, got error: {err}"
    assert domain == expected_domain
    assert err is None


@pytest.mark.parametrize("invalid_email,error_substring", [
    ("user@gmail.com", "Personal and public email providers"),
    ("user@yahoo.in", "Personal and public email providers"),
    ("user@outlook.com", "Personal and public email providers"),
    ("user@proton.me", "Personal and public email providers"),
    ("attacker@fakeedu.com", "not recognized as an official educational institution"),
    ("attacker@stanford.edu.evil.com", "not recognized as an official educational institution"),
    ("hacker@eduhack.net", "not recognized as an official educational institution"),
    ("someone@random.in", "ends with .in, but is not recognized as an accredited educational domain"),
    ("business@company.in", "ends with .in, but is not recognized as an accredited educational domain"),
    ("invalid-email-format", "Invalid email format"),
    ("bad@@mit.edu", "Invalid email format"),
])
def test_institutional_domain_validation_rejections(invalid_email, error_substring):
    """Personal freemail, substring-spoofed domains, and arbitrary .in domains are rejected."""
    is_valid, email, domain, err = domains.validate_institution_domain(invalid_email)
    assert is_valid is False
    assert error_substring.lower() in err.lower()


# ==============================================================================
# 3. INSTITUTION APPLICATION, EMAIL OWNERSHIP & APPROVAL WORKFLOW
# ==============================================================================

def test_personal_email_attempting_institution_registration_rejected(auth_client):
    """Registration with personal/freemail email address is rejected with 422."""
    res = auth_client.post(
        "/api/auth/institution-signup",
        json={
            "email": "dean@gmail.com",
            "name": "Fraud College",
            "password": "StrongPassword2026!",
            "wallet": "0x0000000000000000000000000000000000000004",
            "institution_reference": "REF-001",
            "verification_info": "https://fake.edu; contact"
        }
    )
    assert res.status_code == 422
    assert "personal and public email" in res.json()["detail"].lower()


def test_valid_domain_creates_pending_unverified_institution(auth_client):
    """Valid institutional domain creates PENDING_APPROVAL account with unverified email."""
    res = auth_client.post(
        "/api/auth/institution-signup",
        json={
            "email": "registrar@iitb.ac.in",
            "name": "IIT Bombay",
            "password": "StrongPassword2026!",
            "wallet": "0x0000000000000000000000000000000000000004",
            "institution_reference": "IITB-REG-01",
            "verification_info": "https://www.iitb.ac.in; academic section"
        }
    )
    assert res.status_code == 201
    data = res.json()
    assert data["approval_status"] == "PENDING_APPROVAL"
    assert data["institution_domain"] == "iitb.ac.in"
    assert data["email_verified"] is False
    assert data["verification_sent"] is True

    # 1. Unverified email cannot log in
    login_res = auth_client.post(
        "/api/auth/login",
        json={"email": "registrar@iitb.ac.in", "password": "StrongPassword2026!", "account_type": "institution"}
    )
    assert login_res.status_code == 403
    assert "verify your institutional email" in login_res.json()["detail"].lower()

    # 2. Complete email ownership verification
    demo_code = data.get("demo_verification_code")
    assert demo_code is not None
    ver_res = auth_client.post(
        "/api/auth/verify-email",
        json={"email": "registrar@iitb.ac.in", "code": demo_code}
    )
    assert ver_res.status_code == 200

    # 3. Email verified, but STILL PENDING_APPROVAL -> login still denied with pending message
    login_pending = auth_client.post(
        "/api/auth/login",
        json={"email": "registrar@iitb.ac.in", "password": "StrongPassword2026!", "account_type": "institution"}
    )
    assert login_pending.status_code == 403
    assert "pending approval" in login_pending.json()["detail"].lower()

    # 4. Check public institution status view
    status_res = auth_client.get("/api/auth/institution-status?email=registrar@iitb.ac.in")
    assert status_res.status_code == 200
    st_data = status_res.json()
    assert st_data["exists"] is True
    assert st_data["name"] == "IIT Bombay"
    assert st_data["domain"] == "iitb.ac.in"
    assert st_data["approval_status"] == "PENDING_APPROVAL"
    assert st_data["email_verified"] is True


def test_approved_institution_can_access_registration(auth_client):
    """Once approved by platform owner on-chain and in DB, institution accesses bulk upload and registry."""
    test_wallet = "0x0000000000000000000000000000000000000088"
    MockTestRegistry.approvals[test_wallet] = True
    # 1. Register institution with valid domain
    signup_res = auth_client.post(
        "/api/auth/institution-signup",
        json={
            "email": "dean@mit.edu",
            "name": "MIT Registrar",
            "password": "StrongPassword2026!",
            "wallet": test_wallet,
            "institution_reference": "MIT-REF-99",
            "verification_info": "https://mit.edu/registrar"
        }
    )
    assert signup_res.status_code == 201
    with connect() as conn:
        inst = conn.execute("SELECT id FROM users WHERE email='dean@mit.edu'").fetchone()
        assert inst is not None
        conn.execute("UPDATE users SET email_verified=1, approval_status='APPROVED' WHERE id=?", (inst["id"],))

    # 2. Approved institution logs in
    login_res = auth_client.post(
        "/api/auth/login",
        json={"email": "dean@mit.edu", "password": "StrongPassword2026!", "account_type": "institution"}
    )
    assert login_res.status_code == 200
    assert login_res.json()["approval_status"] == "APPROVED"

    # 3. Access bulk upload limits endpoint
    limits_res = auth_client.get("/api/uploads/limits?mode=register")
    assert limits_res.status_code == 200
    assert limits_res.json()["max_files"] >= 10


def test_ordinary_user_denied_institutional_apis(auth_client):
    """Ordinary users (role='verifier') are rejected with 403 when calling institution endpoints."""
    # Log in as verifier via Google OAuth
    url_res = auth_client.get("/api/auth/oauth/google/url")
    state = url_res.json()["state"]
    auth_client.post(
        "/api/auth/oauth/google/exchange",
        json={"code": "test:google:verifier_user@gmail.com:Verifier Bob:sub_bob_1", "state": state}
    )

    # Attempt to access institution upload limits
    limits_res = auth_client.get("/api/uploads/limits?mode=register")
    assert limits_res.status_code == 403

    # Attempt to call certificate issuance endpoint
    reg_res = auth_client.post(
        "/api/certificates",
        files={"file": ("cert.pdf", b"%PDF-1.4 mock cert bytes", "application/pdf")},
        data={"reference": "AT-FORGED-01"}
    )
    assert reg_res.status_code == 403

    # Attempt to access owner institutions admin list
    owner_res = auth_client.get("/api/institutions")
    assert owner_res.status_code == 403


def test_suspended_institution_denied_registration_and_login(auth_client):
    """Suspended institution is blocked from logging in and accessing registration APIs."""
    # Set up approved institution then suspend it
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO users(id, email, name, password, role, wallet, approval_status, email_verified, institution_domain)
            VALUES(999, 'suspended@iitb.ac.in', 'Suspended College', ?, 'institution', '0x0000000000000000000000000000000000000002', 'SUSPENDED', 1, 'iitb.ac.in')
            """,
            (password_hash("AuthenTra-demo-2026!"),)
        )

    # 1. Login fails with 403 suspended
    res = auth_client.post(
        "/api/auth/login",
        json={"email": "suspended@iitb.ac.in", "password": "AuthenTra-demo-2026!", "account_type": "institution"}
    )
    assert res.status_code == 403
    assert "suspended" in res.json()["detail"].lower()

    # 2. Existing session token loses access immediately
    token = jwt.encode({"sub": "999", "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, main.JWT_SECRET, algorithm="HS256")
    auth_client.cookies.set(main.COOKIE, token)
    assert auth_client.get("/api/uploads/limits?mode=register").status_code == 403
    assert auth_client.get("/api/certificates").status_code == 403


def test_expired_and_invalid_authentication_tokens(auth_client):
    """Expired or forged JWT cookies are rejected with 401."""
    # 1. Expired token
    expired_token = jwt.encode({"sub": "1", "iss": "authentra", "exp": datetime.now(timezone.utc) - timedelta(hours=1)}, main.JWT_SECRET, algorithm="HS256")
    auth_client.cookies.set(main.COOKIE, expired_token)
    exp_res = auth_client.get("/api/auth/me")
    assert exp_res.status_code == 401
    assert "expired" in exp_res.json()["detail"].lower()

    # 2. Forged signature token
    forged_token = jwt.encode({"sub": "1", "iss": "authentra", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "wrong-secret-key-123", algorithm="HS256")
    auth_client.cookies.set(main.COOKIE, forged_token)
    forge_res = auth_client.get("/api/auth/me")
    assert forge_res.status_code == 401
