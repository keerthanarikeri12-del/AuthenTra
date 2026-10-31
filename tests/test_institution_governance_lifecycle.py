"""Comprehensive tests for institution governance lifecycle:
- Approve
- Reject
- Suspend
- Restore
- Revoke
- Reconsider & Approve
- Self-approval prevention
- Non-admin authorization check
"""
import os
import sys
from pathlib import Path

repo_root = str(Path(__file__).resolve().parent.parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

os.environ["AUTHENTRA_DEMO"] = "1"
os.environ["JWT_SECRET"] = "01234567890123456789012345678901"

import pytest
from fastapi.testclient import TestClient

from backend import main
main.JWT_SECRET = "01234567890123456789012345678901"
from backend.storage import connect, initialize, password_hash


class MockGovernanceChain:
    owner = "0x90f8bf6a479f320ead074411a4b0e7944ea8c9c1"
    keys = {
        owner: "owner_key",
        "0xffcf8fdee72ac11b5c542428b35eef5769c409f0": "issuer1_key",
        "0x22d491bde2303f2f43325b2108d26f1eaba1e32b": "issuer2_key",
    }
    contract = type("MockContract", (), {"address": "0x1234567890123456789012345678901234567890"})()

    def __init__(self):
        self.approvals = {}

    def health(self):
        return True

    def approved(self, address):
        return self.approvals.get(address.lower(), False)

    def set_issuer(self, address, approved):
        self.approvals[address.lower()] = approved
        return {
            "transaction_hash": "0xgov_tx_hash",
            "gas_used": 45000,
            "fee_wei": "45000000000",
            "block_number": 100,
        }

    def get_explorer_url(self, tx):
        return f"https://etherscan.io/tx/{tx}" if tx else None


@pytest.fixture
def gov_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gov_test.db")
    monkeypatch.setenv("AUTHENTRA_DB", db_path)
    monkeypatch.setenv("JWT_SECRET", "01234567890123456789012345678901")
    monkeypatch.setattr(main, "JWT_SECRET", "01234567890123456789012345678901")
    mock_chain = MockGovernanceChain()
    monkeypatch.setattr(main, "Registry", lambda: mock_chain)
    monkeypatch.setattr(main, "registry", lambda: mock_chain)
    initialize()

    with connect() as conn:
        # Create system admin
        conn.execute(
            "INSERT INTO users(id, email, name, password, role) VALUES(1, 'admin@authentra.demo', 'Admin', ?, 'SYSTEM_ADMIN')",
            (password_hash("AdminPass123!"),)
        )
        # Create pending institution with user wallet
        conn.execute(
            """INSERT INTO users(id, email, name, password, role, wallet, institution_reference, approval_status, email_verified)
               VALUES(10, 'registrar@iitb.ac.in', 'IIT Bombay', ?, 'INSTITUTION_ADMIN', '0x528f81D918ccdf2D79A90F62E2f8CC2bB138e187', 'IITB-2026', 'PENDING_APPROVAL', 1)""",
            (password_hash("InstPass123!"),)
        )
        # Create normal verifier user
        conn.execute(
            "INSERT INTO users(id, email, name, password, role) VALUES(20, 'user@authentra.demo', 'User', ?, 'USER')",
            (password_hash("UserPass123!"),)
        )

    client = TestClient(main.app)
    yield client, mock_chain


def login_as(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text


def test_full_governance_lifecycle(gov_env):
    client, chain = gov_env
    login_as(client, "admin@authentra.demo", "AdminPass123!")
    wallet = "0x528f81D918ccdf2D79A90F62E2f8CC2bB138e187"

    # 1. APPROVE
    res_app = client.post("/api/institutions/10/approval", json={"status": "APPROVED", "reason": "Accreditation verified."})
    assert res_app.status_code == 200
    assert res_app.json()["approved"] is True
    assert res_app.json()["approval_status"] == "APPROVED"
    assert chain.approved(wallet) is True

    # 2. SUSPEND
    res_susp = client.post("/api/institutions/10/approval", json={"status": "SUSPENDED", "reason": "Annual compliance check pending."})
    assert res_susp.status_code == 200
    assert res_susp.json()["approved"] is False
    assert res_susp.json()["approval_status"] == "SUSPENDED"
    assert chain.approved(wallet) is False

    # 3. RESTORE
    res_rest = client.post("/api/institutions/10/approval", json={"status": "RESTORED", "reason": "Compliance documents received."})
    assert res_rest.status_code == 200
    assert res_rest.json()["approved"] is True
    assert res_rest.json()["approval_status"] == "APPROVED"
    assert chain.approved(wallet) is True

    # 4. REVOKE
    res_rev = client.post("/api/institutions/10/approval", json={"status": "REVOKED", "reason": "Institutional status revoked by board."})
    assert res_rev.status_code == 200
    assert res_rev.json()["approved"] is False
    assert res_rev.json()["approval_status"] == "REVOKED"
    assert chain.approved(wallet) is False

    # 5. REJECT (testing rejection flow)
    res_rej = client.post("/api/institutions/10/approval", json={"status": "REJECTED", "reason": "Rejected."})
    assert res_rej.status_code == 200
    assert res_rej.json()["approved"] is False
    assert res_rej.json()["approval_status"] == "REJECTED"
    assert chain.approved(wallet) is False

    # 6. RECONSIDER & APPROVE
    res_reapp = client.post("/api/institutions/10/approval", json={"status": "APPROVED", "reason": "Appeal validated."})
    assert res_reapp.status_code == 200
    assert res_reapp.json()["approved"] is True
    assert res_reapp.json()["approval_status"] == "APPROVED"
    assert chain.approved(wallet) is True


def test_self_approval_prevented(gov_env):
    client, chain = gov_env
    # Give institution active status so they can log in
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status='APPROVED' WHERE id=10")
    login_as(client, "registrar@iitb.ac.in", "InstPass123!")
    res = client.post("/api/institutions/10/approval", json={"status": "APPROVED", "reason": "Self-approval"})
    assert res.status_code == 403


def test_unauthorized_user_prevented(gov_env):
    client, chain = gov_env
    login_as(client, "user@authentra.demo", "UserPass123!")
    res = client.post("/api/institutions/10/approval", json={"status": "APPROVED", "reason": "Unauthorized user"})
    assert res.status_code == 403
