"""Integration tests for all 3 visual tampering options:
- Option A: Authorized reference template storage and differential alignment.
- Option B: Full end-to-end verification lifecycle & forensic integrity.
- Option C: Pluggable trained model architecture and fallback handling.
"""
import hashlib
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from backend.storage import connect, initialize
from backend.visual_tampering import (
    analyze_visual_tampering,
    store_reference_asset,
    get_reference_asset,
    delete_reference_asset,
    register_tampering_model,
    unregister_tampering_model,
    get_active_tampering_model,
)
from backend.main import _persist_reference_preview, process_verification


def make_sample_certificate(name: str = "Alice Walker", grade: str = "First Class Honours") -> bytes:
    """Create a test certificate image with text."""
    img = Image.new("RGB", (800, 600), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    # Header
    draw.rectangle([40, 40, 760, 100], fill=(220, 230, 245), outline=(180, 200, 220))
    draw.text((60, 60), "METROPOLITAN UNIVERSITY OF TECHNOLOGY", fill=(20, 40, 80))
    draw.text((60, 140), "Certificate of Graduation", fill=(30, 30, 30))
    # Recipient field
    draw.text((60, 220), f"Awarded to: {name}", fill=(10, 10, 10))
    # Degree & Grade field
    draw.text((60, 280), f"Classification: {grade}", fill=(10, 10, 10))
    draw.text((60, 340), "Certificate ID: AT-INT-2026-001", fill=(80, 80, 80))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_spliced_certificate(original_png: bytes, forged_name: str = "Mallory Hacker") -> bytes:
    """Create a tampered version of the certificate with altered name."""
    img = Image.open(io.BytesIO(original_png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    # Paint over the name area
    draw.rectangle([55, 215, 450, 250], fill=(245, 245, 245))
    draw.text((60, 220), f"Awarded to: {forged_name}", fill=(180, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockChainForIntegration:
    owner = "0x1111111111111111111111111111111111111111"
    contract = type("MockContract", (), {"address": "0x1234567890123456789012345678901234567890"})()

    def __init__(self, records=None):
        self.records = records or {}

    def lookup(self, ref):
        return self.records.get(ref)

    def lookup_by_hash(self, digest):
        for ref, rec in self.records.items():
            if rec.get("file_hash", "").lower() == digest.lower():
                return {**rec, "reference": ref}
        return None

    def approved(self, addr):
        return True

    def get_network_info(self):
        return {"chain_id": 1337, "network_name": "Testnet", "contract_address": self.contract.address}

    def get_explorer_url(self, tx):
        return f"https://etherscan.io/tx/{tx}"


# ==============================================================================
# OPTION A TESTS: Reference Template Storage, Retrieval & Alignment
# ==============================================================================

def test_option_a_store_and_retrieve_reference_asset(tmp_path, monkeypatch):
    """Verify that reference assets are written to disk and can be retrieved."""
    initialize()
    ref = "AT-ASSET-001"
    raw_data = make_sample_certificate()

    # Store
    ok = store_reference_asset(ref, institution_id=1, data=raw_data)
    assert ok is True

    # Retrieve
    retrieved = get_reference_asset(ref)
    assert retrieved is not None
    assert retrieved == raw_data

    # Cleanup
    ok_del = delete_reference_asset(ref, user_id=1, user_role="INSTITUTION_ADMIN")
    assert ok_del is True
    assert get_reference_asset(ref) is None


def test_option_a_differential_alignment_detects_spliced_regions():
    """Verify that comparing a tampered document against authorized reference locates diffs."""
    orig_bytes = make_sample_certificate(name="Alice Walker")
    spliced_bytes = make_spliced_certificate(orig_bytes, forged_name="Mallory Hacker")

    result = analyze_visual_tampering(spliced_bytes, "png", reference_image_data=orig_bytes)
    assert result["status"] == "reference_comparison_only"
    assert len(result["regions"]) > 0
    assert result["summary"]["reference_differences"] > 0
    assert any(r["type"] == "reference_difference" for r in result["regions"])
    # First region must have normalized coordinates [x, y, w, h]
    box = result["regions"][0]["box"]
    assert len(box) == 4
    assert 0.0 <= box[0] <= 1.0 and 0.0 <= box[1] <= 1.0


# ==============================================================================
# OPTION B TESTS: Full Verification Pipeline Integration
# ==============================================================================

def test_option_b_full_verification_with_reference_asset(tmp_path, monkeypatch):
    """End-to-end verification: when file hash mismatches, backend pulls reference template."""
    initialize()
    ref = "AT-INT-2026-001"
    orig_bytes = make_sample_certificate(name="Alice Walker")
    spliced_bytes = make_spliced_certificate(orig_bytes, forged_name="Mallory Hacker")
    orig_hash = hashlib.sha256(orig_bytes).hexdigest().lower()

    # Store reference template in system
    store_reference_asset(ref, institution_id=1, data=orig_bytes)

    # Set up mock blockchain record pointing to original hash
    mock_chain = MockChainForIntegration({
        ref: {
            "file_hash": orig_hash,
            "issuer": "0x1111111111111111111111111111111111111111",
            "registered_at": 1700000000,
            "revoked": False,
        }
    })
    from backend import main
    monkeypatch.setattr(main, "registry", lambda: mock_chain)

    user = {"id": 1, "role": "verifier", "email": "verifier@test.com"}

    # 1. Verify exact original -> visual tampering is 'not_required'
    res_orig = process_verification(orig_bytes, "png", supplied_reference=ref, user=user)
    assert res_orig["hash_matches"] is True
    assert res_orig["visual_tampering"]["status"] == "not_required"

    # 2. Verify spliced document -> automatically finds reference asset & localizes diff
    res_spliced = process_verification(spliced_bytes, "png", supplied_reference=ref, user=user)
    assert res_spliced["hash_matches"] is False
    assert res_spliced["visual_tampering"]["status"] == "reference_comparison_only"
    assert len(res_spliced["visual_tampering"]["regions"]) > 0

    # Clean up asset
    delete_reference_asset(ref, user_id=1, user_role="SYSTEM_ADMIN")


def test_option_b_unregistered_document_returns_unavailable_without_reference():
    """Documents without reference or trained model return unavailable disclaimer."""
    sample = make_sample_certificate()
    result = analyze_visual_tampering(sample, "png", reference_image_data=None)
    assert result["status"] == "unavailable"
    assert "No trained tampering localization model" in result["accessible_description"]
    assert result["regions"] == []


# ==============================================================================
# OPTION C TESTS: Pluggable Trained Model Architecture
# ==============================================================================

def test_option_c_pluggable_tampering_model():
    """Registering a model allows blind tampering detection without a reference image."""
    try:
        # Define a mock trained model predict function
        def mock_neural_segmenter(image):
            # Model predicts an anomaly box around [0.1, 0.2, 0.4, 0.15] with 0.88 anomaly score
            return [
                {
                    "box": [0.1, 0.2, 0.4, 0.15],
                    "confidence": 0.88,
                    "score": 0.88,
                    "type": "model_anomaly",
                    "label": "Neural Boundary Inconsistency",
                    "explanation": "High-frequency edge mismatch detected by AuthenTra-Net.",
                }
            ], 0.88

        register_tampering_model(
            name="AuthenTra-Net Forensic Segmenter v2.0",
            predict_fn=mock_neural_segmenter,
            technique="Deep Convolutional Residual Noise Analysis",
            license="MIT",
            limitations="Advisory neural model.",
        )

        sample = make_sample_certificate()
        result = analyze_visual_tampering(sample, "png", reference_image_data=None)

        assert result["status"] == "suspicious_regions_detected"
        assert result["model_provenance"] == "Deep Convolutional Residual Noise Analysis"
        assert result["provenance"]["model_name"] == "AuthenTra-Net Forensic Segmenter v2.0"
        assert result["anomaly_score"] == 0.88
        assert len(result["regions"]) == 1
        assert result["regions"][0]["type"] == "model_anomaly"
    finally:
        # Ensure model is unregistered so subsequent tests see default state
        unregister_tampering_model()

    # After unregistering, behavior returns to clean default
    after = analyze_visual_tampering(sample, "png", reference_image_data=None)
    assert after["status"] == "unavailable"
    assert after["provenance"]["model_name"] is None

