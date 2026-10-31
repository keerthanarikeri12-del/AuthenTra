"""Regression cases for unsupported or manufactured advisory conclusions."""
import io
import json

import pytest
from PIL import Image
from eth_account import Account
from eth_account.messages import encode_defunct
from backend.fields import compare_fields, compute_metadata_commitment
from backend.routing import determine_review_routing
from backend.transformations import analyze_transformations
from backend.visual_tampering import analyze_visual_tampering


def record(fields):
    result = {"reference": "AT-TEST", "file_hash": "a" * 64,
              "confirmed_metadata": json.dumps(fields)}
    result["metadata_commitment"] = compute_metadata_commitment(fields, "AT-TEST", "a" * 64)
    return result


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(stream, "PNG")
    return stream.getvalue()


def test_missing_registered_field_cannot_be_all_matched():
    result = compare_fields(record({"name": "Alice", "course": "Physics"}), {"name": "Alice"})
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["all_fields_match"] is False
    assert result["fields"]["course"]["status"] == "missing"


def test_absent_optional_unregistered_fields_do_not_prevent_match():
    result = compare_fields(record({"name": "Alice"}), {"name": "Alice"})
    assert result["status"] == "ALL_MATCHED"
    assert result["all_fields_match"] is True


def test_ambiguous_alias_cannot_be_reported_as_changed():
    result = compare_fields(record({"name": "Alice"}), {"name": "Bob", "ambiguous_fields": ["name"]})
    assert result["status"] == "INDETERMINATE"
    assert result["fields"]["recipient_name"]["status"] == "ambiguous"


def test_invalid_commitment_cannot_support_a_match():
    reg = record({"name": "Alice"})
    reg["confirmed_metadata"] = json.dumps({"name": "Bob"})
    assert compare_fields(reg, {"name": "Bob"})["status"] == "unavailable"


def test_signature_must_match_chain_issuer_and_hash():
    signer = Account.from_key("01" * 32)
    reg = record({"name": "Alice"})
    reg["issuer_signature"] = Account.sign_message(encode_defunct(hexstr=reg["metadata_commitment"]), signer.key).signature.hex()
    result = compare_fields(reg, {"name": "Alice"}, trusted_issuer=signer.address, trusted_hash="a" * 64)
    assert result["signature_verified"] is True
    assert compare_fields(reg, {"name": "Alice"}, trusted_issuer=signer.address, trusted_hash="b" * 64)["status"] == "unavailable"
    reg["issuer_signature"] = "0xcommitment-fake"
    assert compare_fields(reg, {"name": "Alice"}, trusted_issuer=signer.address, trusted_hash="a" * 64)["status"] == "unavailable"


def test_visual_analysis_never_invents_a_model_or_clear_verdict():
    results = [analyze_visual_tampering(image_bytes(), "image") for _ in range(3)]
    for result in results:
        assert result["status"] == "unavailable"
        assert result["provenance"]["model_name"] is None
        assert result["anomaly_score"] is None
        assert result["regions"] == []
    assert all({k: v for k, v in r.items() if k != "duration_ms"} ==
               {k: v for k, v in results[0].items() if k != "duration_ms"} for r in results)


def test_exact_match_does_not_fabricate_quality_measurements():
    result = analyze_transformations(image_bytes(), "image", is_hash_match=True)
    assert result["image_quality"] is None
    assert result["ocr_reliability"] is None
    assert result["skew_angle"] is None


def test_matching_fields_do_not_establish_rescan_history():
    result = analyze_transformations(image_bytes(), "image", field_comparison={"status": "ALL_MATCHED"})
    assert result["transformation_type"] == "unknown"
    assert result["confidence"] is None
    assert result["risk_level"] == "undetermined"


@pytest.mark.parametrize("status", ["POSSIBLE_TAMPERING_OR_FILE_MISMATCH", "NOT_FOUND", "REVOKED"])
def test_nonverified_document_is_never_cleared_by_advisory_similarity(status):
    result = determine_review_routing(status, {"status": "ALL_MATCHED"}, {"status": "clear"}, None,
                                     None, "University Certificate", {"name": "Alice", "reference": "AT-TEST"})
    assert result["requires_human_review"] is True
    assert result["calibrated_confidence"] is None
