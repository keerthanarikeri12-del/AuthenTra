"""Live Blockchain Integration Tests for AuthenTra.

These tests execute REAL Web3 transactions against a live Ethereum-compatible
disposable blockchain node (Ganache on a temporary loopback port) running the deployed
AuthenTraRegistry.sol smart contract.

Mocked tests are in tests/test_registration_workflow.py and tests/test_verification_workflow.py.
THIS TEST SUITE EXCLUSIVELY EXERCISES THE ACTUAL LIVE BLOCKCHAIN.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from reportlab.pdfgen import canvas
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

# Ensure AUTHENTRA_DEMO is active so Registry loads .local/chain.json
os.environ["AUTHENTRA_DEMO"] = "1"



def create_test_pdf(reference: str, text: str = "Test Certificate") -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(50, 750, "MERIDIAN INSTITUTE OF TECHNOLOGY")
    c.drawString(50, 710, f"Certificate of Completion - Ref: {reference}")
    c.drawString(50, 680, f"Awarded to Test Candidate: {text}")
    c.drawString(50, 650, "Date: 2026-05-15")
    c.save()
    return buffer.getvalue()


class TestLiveBlockchainDirect:
    """Direct Web3 contract interactions against the live Ganache EVM."""

    def test_live_chain_health_and_contract(self, live_chain):
        """Confirm live blockchain is responding and contract code is present on-chain."""
        assert live_chain.health() is True
        net_info = live_chain.get_network_info()
        assert net_info["chain_id"] == 1337
        assert net_info["contract_address"].startswith("0x")
        code = live_chain.w3.eth.get_code(live_chain.contract.address)
        assert len(code) > 0, "No contract bytecode at deployed address on live chain."

    def test_live_registration_and_independent_readback(self, live_chain):
        """Execute a REAL transaction to register a certificate and independently read it back."""
        ref = f"AT-LIVE-{uuid.uuid4().hex[:8].upper()}"
        file_bytes = b"Authentic certificate original payload " + uuid.uuid4().bytes
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Identify authorized issuer wallet
        issuers = [k for k in live_chain.keys if k != live_chain.owner]
        assert len(issuers) > 0, "No authorized issuer accounts in chain config."
        issuer_wallet = issuers[0]
        assert live_chain.approved(issuer_wallet), "Issuer must be approved on-chain."

        # Real registration
        result = live_chain.register_and_verify(ref, file_hash, issuer_wallet)

        # Assert real transaction outcome
        assert result["on_chain_verified"] is True
        assert result["idempotent"] is False
        raw_tx = result["transaction_hash"].removeprefix("0x")
        assert len(raw_tx) == 64, f"Expected 64 hex chars, got {raw_tx}"
        assert result["block_number"] >= 0
        assert result["gas_used"] > 0
        assert result["contract_address"] == live_chain.contract.address

        # Independent on-chain read-back
        on_chain = live_chain.lookup(ref)
        assert on_chain is not None, "Independent read-back failed: record not found on blockchain."
        assert on_chain["file_hash"].lower() == file_hash.lower()
        assert on_chain["issuer"].lower() == issuer_wallet.lower()
        assert on_chain["revoked"] is False
        assert on_chain["registered_at"] > 0

    def test_live_registration_idempotency(self, live_chain):
        """Re-submitting the same reference and hash returns verified idempotent result without re-mining."""
        ref = f"AT-LIVE-{uuid.uuid4().hex[:8].upper()}"
        file_hash = hashlib.sha256(b"idempotency-check-payload-" + uuid.uuid4().bytes).hexdigest()
        issuer = [k for k in live_chain.keys if k != live_chain.owner][0]

        first = live_chain.register_and_verify(ref, file_hash, issuer)
        assert first["idempotent"] is False
        assert first["transaction_hash"] is not None

        # Second call with exact same parameters
        second = live_chain.register_and_verify(ref, file_hash, issuer)
        assert second["on_chain_verified"] is True
        assert second["idempotent"] is True
        assert second["transaction_hash"] is None  # No redundant transaction submitted
        assert second["registered_at"] == first["registered_at"]

    def test_live_duplicate_conflict_rejection(self, live_chain):
        """Attempting to overwrite an existing reference with a different hash is rejected."""
        ref = f"AT-LIVE-{uuid.uuid4().hex[:8].upper()}"
        hash_1 = hashlib.sha256(b"original-payload-" + uuid.uuid4().bytes).hexdigest()
        hash_2 = hashlib.sha256(b"conflicting-payload-" + uuid.uuid4().bytes).hexdigest()
        issuer = [k for k in live_chain.keys if k != live_chain.owner][0]

        live_chain.register_and_verify(ref, hash_1, issuer)

        with pytest.raises(ValueError, match="already exists on the blockchain with different parameters"):
            live_chain.register_and_verify(ref, hash_2, issuer)

        # Confirm on-chain record was NOT corrupted
        on_chain = live_chain.lookup(ref)
        assert on_chain["file_hash"].lower() == hash_1.lower()

    def test_live_unapproved_issuer_rejection(self, live_chain):
        """Unapproved institution cannot register certificates on the live EVM."""
        # Ganache already provides an unapproved third demo signer; no funding transfer.
        unapproved = [address for address in live_chain.keys
                      if address != live_chain.owner and not live_chain.approved(address)][0]

        ref = f"AT-UNAPPROVED-{uuid.uuid4().hex[:8]}"
        dummy_hash = hashlib.sha256(b"unauthorized").hexdigest()

        # The contract call must revert
        with pytest.raises(Exception, match="Approved issuer only"):
            live_chain.register(ref, dummy_hash, unapproved)

    def test_live_certificate_revocation(self, live_chain):
        """An authorized issuer can revoke their registered certificate on the live blockchain."""
        ref = f"AT-REVOKE-{uuid.uuid4().hex[:8].upper()}"
        file_hash = hashlib.sha256(b"revocation-target-" + uuid.uuid4().bytes).hexdigest()
        issuer = [k for k in live_chain.keys if k != live_chain.owner][0]

        live_chain.register_and_verify(ref, file_hash, issuer)
        assert live_chain.lookup(ref)["revoked"] is False

        # Revoke on-chain
        rev_result = live_chain.revoke(ref, issuer)
        raw_rev_tx = rev_result["transaction_hash"].removeprefix("0x")
        assert len(raw_rev_tx) == 64, f"Expected 64 hex chars, got {raw_rev_tx}"

        # Independent on-chain read-back
        on_chain = live_chain.lookup(ref)
        assert on_chain["revoked"] is True

        # Second revocation must revert (permanent and idempotent)
        with pytest.raises(Exception):
            live_chain.revoke(ref, issuer)


class TestLiveBlockchainEndToEndAPI:
    """End-to-end integration tests using FastAPI TestClient with the live blockchain."""

    @pytest.fixture
    def test_app(self, live_chain, tmp_path, monkeypatch):
        from backend import main
        monkeypatch.setenv("AUTHENTRA_DB", str(tmp_path / "live_test.db"))
        main.initialize()
        main.seed_demo(live_chain)
        main.LOGIN_ATTEMPTS.clear()
        with TestClient(main.app) as client:
            yield client, live_chain

    def test_flow_a_and_flow_b_end_to_end_on_live_chain(self, test_app):
        """FLOW A: Approved institution registers certificate on live blockchain.
        FLOW B: User verifies exact original certificate against live blockchain.
        """
        client, live_chain = test_app
        ref = f"AT-E2E-{uuid.uuid4().hex[:8].upper()}"
        pdf_bytes = create_test_pdf(ref, "Alice Walker")
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # 1. FLOW A: Approved institution logs in
        login_res = client.post(
            "/api/auth/login",
            json={"email": "issuer@authentra.demo", "password": "AuthenTra-demo-2026!", "account_type": "institution"}
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"

        # 2. Institution uploads certificate to register on live blockchain
        reg_res = client.post(
            "/api/certificates",
            files={"file": (f"{ref}.pdf", pdf_bytes, "application/pdf")},
            data={"reference": ref}
        )
        assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
        reg_data = reg_res.json()
        assert reg_data["status"] == "registered"
        raw_tx = reg_data["transaction_hash"].removeprefix("0x")
        assert len(raw_tx) == 64
        assert reg_data["block_number"] >= 0

        # Independent confirmation: query blockchain directly
        on_chain = live_chain.lookup(ref)
        assert on_chain is not None
        assert on_chain["file_hash"].lower() == pdf_hash.lower()
        assert on_chain["revoked"] is False

        # 3. FLOW B: Regular user logs in
        user_login = client.post(
            "/api/auth/login",
            json={"email": "verifier@authentra.demo", "password": "AuthenTra-demo-2026!", "account_type": "user"}
        )
        assert user_login.status_code == 200

        # 4. User verifies the authentic original certificate
        verify_res = client.post(
            "/api/verify",
            files={"file": (f"{ref}.pdf", pdf_bytes, "application/pdf")},
            data={"reference": ref}
        )
        assert verify_res.status_code == 200
        v_data = verify_res.json()
        assert v_data["status"] == "verified"
        assert v_data["category"] == "VERIFIED"
        assert v_data["hash_matches"] is True
        assert v_data["blockchain_record_status"] == "ACTIVE"
        assert v_data["issuer_authorized"] is True
        assert v_data["transaction_hash"] == reg_data["transaction_hash"]
        assert "exact match" in v_data["hash_comparison"].lower()

        # 5. User verifies an altered certificate (same reference, modified content)
        altered_bytes = create_test_pdf(ref, "Eve Tampered")
        verify_altered = client.post(
            "/api/verify",
            files={"file": (f"{ref}-altered.pdf", altered_bytes, "application/pdf")},
            data={"reference": ref}
        )
        assert verify_altered.status_code == 200
        alt_data = verify_altered.json()
        assert alt_data["status"] == "possible_tampering"
        assert alt_data["category"] == "POSSIBLE_TAMPERING_OR_FILE_MISMATCH"
        assert alt_data["hash_matches"] is False
        assert alt_data["blockchain_record_status"] == "ACTIVE"
        assert "differs" in alt_data["hash_comparison"].lower()

        # 6. Institution revokes certificate on live blockchain
        issuers = [k for k in live_chain.keys if k != live_chain.owner]
        live_chain.revoke(ref, issuers[0])

        # 7. User re-verifies the now-revoked certificate
        verify_revoked = client.post(
            "/api/verify",
            files={"file": (f"{ref}.pdf", pdf_bytes, "application/pdf")},
            data={"reference": ref}
        )
        assert verify_revoked.status_code == 200
        rev_data = verify_revoked.json()
        assert rev_data["status"] == "revoked"
        assert rev_data["category"] == "REVOKED"
        assert rev_data["blockchain_record_status"] == "REVOKED"

        # 8. User verifies an unregistered reference
        verify_unregistered = client.post(
            "/api/verify",
            files={"file": ("unregistered.pdf", create_test_pdf("AT-UNKNOWN-9999"), "application/pdf")},
            data={"reference": "AT-UNKNOWN-9999"}
        )
        assert verify_unregistered.status_code == 200
        unreg_data = verify_unregistered.json()
        assert unreg_data["status"] == "not_registered"
        assert unreg_data["category"] == "NOT_REGISTERED_OR_INCONCLUSIVE"
        assert unreg_data["blockchain_record_status"] == "NOT_FOUND"

        # 9. Verify user history records all operations
        hist_res = client.get("/api/history")
        assert hist_res.status_code == 200
        history = hist_res.json()
        assert len(history) >= 4
        categories = [h["category"] for h in history]
        assert "VERIFIED" in categories
        assert "POSSIBLE_TAMPERING_OR_FILE_MISMATCH" in categories
        assert "REVOKED" in categories
        assert "NOT_REGISTERED_OR_INCONCLUSIVE" in categories
