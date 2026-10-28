"""
Comprehensive test suite covering Features 1 through 4:
1. Field-level change detection against authenticated metadata.
2. Visual tampering localization on PDFs and images.
3. Rescan, recompression, and re-export transformation advisory.
4. Confidence-based review routing and immutable audit trail.
"""

import io
import json
import hashlib
import sqlite3
import pytest
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from backend.fields import (
    FIELD_SCHEMA_VERSION,
    canonical_metadata_dict,
    compute_metadata_commitment,
    compare_fields,
    compare_single_field,
    normalize_recipient_name,
    normalize_course,
    normalize_date,
    normalize_grade,
    normalize_reference
)
from backend.visual_tampering import (
    analyze_visual_tampering,
    compute_ela_image,
    detect_suspicious_patches,
    store_reference_asset,
    delete_reference_asset
)
from backend.transformations import (
    assess_image_quality,
    estimate_skew_angle,
    analyze_transformations
)
from backend.routing import (
    POLICY_VERSION,
    assess_layout_familiarity,
    determine_review_routing,
    record_review_decision,
    get_review_history
)
from backend.storage import connect, initialize, ROLE_USER, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN
from fastapi import HTTPException


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

def make_test_image(width=600, height=400, bg=(255, 255, 255), text="Certificate"):
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, width - 10, height - 10], outline=(0, 0, 0), width=2)
    draw.text((30, 30), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# =============================================================================
# 1. FIELD-LEVEL CHANGE DETECTION TESTS
# =============================================================================

def test_field_schema_and_canonical_metadata():
    assert FIELD_SCHEMA_VERSION == "2026.1"
    raw = {
        "recipient_name": "  Alex Morgan ",
        "course": "Blockchain Architecture",
        "reference": "AT-2026-0001",
        "unknown_extra": "Ignore me"
    }
    canon = canonical_metadata_dict(raw)
    assert canon["recipient_name"] == "Alex Morgan"
    assert canon["course"] == "Blockchain Architecture"
    assert canon["certificate_reference"] == "AT-2026-0001"
    assert "unknown_extra" not in canon


def test_metadata_commitment_integrity():
    fields = {
        "recipient_name": "Alex Morgan",
        "course": "Blockchain Architecture",
        "institution": "Apex Institute",
        "issue_date": "2025-06-12",
        "grade": "Distinction"
    }
    ref = "AT-2026-0001"
    file_hash = "f" * 64
    commitment = compute_metadata_commitment(fields, ref, file_hash)
    assert isinstance(commitment, str) and len(commitment) == 64

    # Any single character change in any field alters the commitment
    tampered_fields = {**fields, "recipient_name": "Alex Morgam"}
    tampered_commitment = compute_metadata_commitment(tampered_fields, ref, file_hash)
    assert commitment != tampered_commitment

    # Altering the reference alters the commitment
    assert commitment != compute_metadata_commitment(fields, "AT-2026-0002", file_hash)

    # Altering the file hash alters the commitment
    assert commitment != compute_metadata_commitment(fields, ref, "0" * 64)


def test_conservative_normalizers_prevent_fuzzy_matches():
    # Names: strict non-fuzzy
    assert normalize_recipient_name("Dr. Alex Morgan") == "alex morgan"
    assert normalize_recipient_name("  Alex   Morgan  ") == "alex morgan"
    # Never equate distinct names
    assert normalize_recipient_name("Alex Morgan") != normalize_recipient_name("Alex Smith")
    assert normalize_recipient_name("Alex Morgan") != normalize_recipient_name("Alexander Morgan")

    # Dates: strict ISO conversion
    assert normalize_date("2025-06-12") == "2025-06-12"
    assert normalize_date("12 June 2025") == "2025-06-12"
    assert normalize_date("June 12, 2025") == "2025-06-12"
    assert normalize_date("12th June 2025") == "2025-06-12"
    # Never equate different dates
    assert normalize_date("2025-06-12") != normalize_date("2025-06-13")

    # Grades: strip spacing around slashes, uppercase
    assert normalize_grade(" 3.8 / 4.0 ") == "3.8/4.0"
    assert normalize_grade("First Class Honours") == "FIRST CLASS HONOURS"
    assert normalize_grade("First Class") != normalize_grade("Second Class")


def test_field_comparison_statuses_and_uncertainty():
    confirmed = {
        "reference": "AT-2026-0001",
        "recipient_name": "Alex Morgan",
        "institution": "Apex Institute",
        "course": "Blockchain",
        "issue_date": "2025-06-12",
        "grade": "Distinction"
    }
    dummy_hash = "a" * 64
    comm = compute_metadata_commitment(confirmed, "AT-2026-0001", dummy_hash)
    record = {
        "reference": "AT-2026-0001",
        "file_hash": dummy_hash,
        "confirmed_metadata": json.dumps(confirmed),
        "metadata_commitment": comm,
        "metadata_schema_version": "2026.1"
    }

    # 1. Exact match
    res_exact = compare_fields(record, confirmed)
    assert res_exact["status"] == "ALL_MATCHED"
    assert res_exact["commitment_verified"] is True
    assert res_exact["summary"]["matched"] == 6

    # 2. Critical field changed (Name)
    res_name = compare_fields(record, {**confirmed, "name": "Jordan Vance"})
    assert res_name["status"] == "CRITICAL_FIELDS_CHANGED"
    assert res_name["fields"]["recipient_name"]["status"] == "changed"

    # 3. Grade changed (Secondary field)
    res_grade = compare_fields(record, {**confirmed, "grade": "Merit"})
    assert res_grade["status"] == "FIELDS_CHANGED"
    assert res_grade["fields"]["grade"]["status"] == "changed"

    # 4. Unreadable field -> Uncertainty, NOT confirmed alteration
    f_unreadable = compare_single_field("recipient_name", "Alex Morgan", "???", unreadable=True)
    assert f_unreadable["status"] == "unreadable"
    assert "unreadable" in f_unreadable["explanation"]

    # 5. Missing field -> Uncertainty
    f_missing = compare_single_field("grade", "Distinction", None)
    assert f_missing["status"] == "missing"


def test_backward_compatibility_uncommitted_records():
    legacy_record = {"reference": "AT-2026-0001", "file_hash": "a" * 64, "confirmed_metadata": None}
    res = compare_fields(legacy_record, {"name": "Alex Morgan"})
    assert res["status"] == "unavailable"
    assert res["commitment_verified"] is False
    assert "unavailable" in res["explanation"].lower()


# =============================================================================
# 2. VISUAL TAMPERING LOCALIZATION TESTS
# =============================================================================

def test_visual_tampering_preserves_untouched_bytes():
    original_bytes = make_test_image(text="Official Certificate AT-2026-0001")
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    # Pass bytes to visual tampering analysis
    analysis = analyze_visual_tampering(original_bytes, "jpeg")

    # Untouched byte guarantee: input bytes are completely preserved
    assert hashlib.sha256(original_bytes).hexdigest() == original_hash
    assert analysis["status"] in ("clear", "suspicious_regions_detected")
    assert "provenance" in analysis
    assert "accessible_description" in analysis


def test_visual_tampering_resource_limits_and_safety():
    # Oversized byte payload rejected safely
    oversized = b"0" * (11 * 1024 * 1024)
    res_oversized = analyze_visual_tampering(oversized, "jpeg")
    assert res_oversized["status"] == "unavailable"

    # Empty payload handled safely
    res_empty = analyze_visual_tampering(b"", "jpeg")
    assert res_empty["status"] == "unavailable"


def test_visual_tampering_spliced_patch_localization():
    # Create clean image
    base = Image.new("RGB", (600, 400), (255, 255, 255))
    draw = ImageDraw.Draw(base)
    draw.text((50, 50), "Original Text", fill=(0, 0, 0))
    buf_clean = io.BytesIO()
    base.save(buf_clean, format="JPEG", quality=90)
    clean_bytes = buf_clean.getvalue()

    # Create spliced image with foreign patch
    spliced = base.copy()
    draw_s = ImageDraw.Draw(spliced)
    draw_s.rectangle([150, 150, 350, 200], fill=(255, 255, 200))
    draw_s.text((160, 165), "SPLICED FAKE RECIPIENT", fill=(0, 0, 0))
    buf_spliced = io.BytesIO()
    spliced.save(buf_spliced, format="JPEG", quality=75)
    spliced_bytes = buf_spliced.getvalue()

    analysis = analyze_visual_tampering(spliced_bytes, "jpeg", reference_image_data=clean_bytes)
    assert analysis["status"] == "suspicious_regions_detected"
    assert len(analysis["regions"]) > 0

    first_region = analysis["regions"][0]
    assert "box" in first_region
    assert len(first_region["box"]) == 4  # [x, y, w, h] normalized
    assert 0.0 <= first_region["box"][0] <= 1.0
    assert 0.0 <= first_region["box"][1] <= 1.0
    assert analysis["accessible_description"] is not None
    assert "Region" in analysis["accessible_description"]


def test_reference_asset_storage_and_deletion():
    ref = f"AT-TEST-ASSET-{hashlib.md5(b'test').hexdigest()[:8]}"
    test_data = b"fake_png_data"
    initialize()

    # Ensure clean state
    with connect() as conn:
        conn.execute("DELETE FROM reference_assets WHERE reference=?", (ref,))
        conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role) VALUES(999, 'inst@demo.test', 'Test Inst', 'hash', 'INSTITUTION_ADMIN')")

    # Store asset
    ok_store = store_reference_asset(ref, institution_id=999, data=test_data, asset_type="preview_png")
    assert ok_store is True

    # Delete asset with consent verification
    ok_delete = delete_reference_asset(ref, user_id=999, user_role=ROLE_INSTITUTION_ADMIN)
    assert ok_delete is True

    # Verify deleted
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM reference_assets WHERE reference=?", (ref,)).fetchone()
        assert row is None


# =============================================================================
# 3. ANALYSIS OF RESCANS AND COMPRESSION TESTS
# =============================================================================

def test_image_quality_assessment():
    clean_bytes = make_test_image(600, 400, text="Sharp Crisp Digital Certificate")
    img_clean = Image.open(io.BytesIO(clean_bytes))
    q_clean = assess_image_quality(img_clean)

    assert q_clean["sharpness_laplacian"] > 0
    assert q_clean["is_blurry"] is False

    # Blurry image
    img_blurry = img_clean.filter(ImageFilter.GaussianBlur(12))
    q_blurry = assess_image_quality(img_blurry)
    assert q_blurry["sharpness_laplacian"] < q_clean["sharpness_laplacian"]
    assert q_blurry["is_blurry"] is True


def test_skew_angle_estimation():
    img = Image.new("RGB", (500, 300), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(40, 260, 20):
        draw.line([(30, y), (470, y)], fill=(0, 0, 0), width=3)
    skew = estimate_skew_angle(img)
    assert abs(skew) <= 1.0  # Horizontal lines have ~0 degree skew


def test_transformation_advisory_synthesis_and_trust_invariants():
    raw_bytes = make_test_image(text="Test Certificate AT-2026-0001")

    # 1. Exact match
    res_exact = analyze_transformations(raw_bytes, "jpeg", is_hash_match=True)
    assert res_exact["advisory_outcome"] == "MATCH_CONFIRMED"

    # 2. Benign rescan where all fields agree
    res_benign = analyze_transformations(
        raw_bytes, "jpeg",
        field_comparison={"status": "ALL_MATCHED"},
        ocr_confidence=92.0,
        is_hash_match=False
    )
    assert res_benign["advisory_outcome"] == "FIELDS_AGREE_RESAVE_OR_REEXPORT"
    assert "Fields Agree" in res_benign["headline"]

    # 3. Malicious content differences detected
    res_malicious = analyze_transformations(
        raw_bytes, "jpeg",
        field_comparison={"status": "CRITICAL_FIELDS_CHANGED"},
        ocr_confidence=90.0,
        is_hash_match=False
    )
    assert res_malicious["advisory_outcome"] == "CONTENT_DIFFERENCES_DETECTED"
    assert "Content Differences" in res_malicious["headline"]

    # 4. Mixed evidence (fields match but visual tamper anomalies detected)
    res_mixed = analyze_transformations(
        raw_bytes, "jpeg",
        field_comparison={"status": "ALL_MATCHED"},
        visual_analysis={"status": "suspicious_regions_detected"},
        ocr_confidence=88.0,
        is_hash_match=False
    )
    assert res_mixed["advisory_outcome"] == "MIXED_EVIDENCE_REVIEW_REQUIRED"

    # 5. TRUST INVARIANT: High visual similarity or benign rescan NEVER promotes to "VERIFIED"
    for trial_outcome in [res_benign, res_malicious, res_mixed]:
        assert trial_outcome["advisory_outcome"] != "VERIFIED"
        assert trial_outcome["advisory_outcome"] != "verified"


# =============================================================================
# 4. CONFIDENCE-BASED REVIEW ROUTING & AUDIT TRAIL TESTS
# =============================================================================

def test_layout_familiarity_detection():
    cert_text = "Apex Institute of Technology Certificate of Completion Degree Awarded Alex Morgan"
    fam_cert = assess_layout_familiarity(cert_text, {"reference": "AT-001", "name": "Alex Morgan"})
    assert fam_cert["familiarity_score"] >= 0.70
    assert fam_cert["is_unfamiliar"] is False

    random_text = "Shopping list: apples, milk, bread, butter, eggs"
    fam_random = assess_layout_familiarity(random_text, {})
    assert fam_random["familiarity_score"] < 0.40
    assert fam_random["is_unfamiliar"] is True


def test_review_routing_policy_outcomes():
    # Clean high confidence -> No additional review
    route_clean = determine_review_routing(
        verification_status="POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
        field_comparison={"status": "ALL_MATCHED"},
        visual_tampering={"status": "clear"},
        transformation_advisory={"evidence": {"image_quality": {"is_blurry": False, "sharpness_laplacian": 120.0}}},
        ocr_confidence=95.0,
        document_text="Apex Institute of Technology Certificate of Completion Alex Morgan",
        extracted_fields={"reference": "AT-001", "name": "Alex"}
    )
    assert route_clean["routing_outcome"] == "COMPLETED_NO_REVIEW"
    assert route_clean["requires_human_review"] is False

    # Critical field changed -> Institution review required
    route_inst = determine_review_routing(
        verification_status="POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
        field_comparison={"status": "CRITICAL_FIELDS_CHANGED"},
        visual_tampering={"status": "clear"},
        transformation_advisory={"evidence": {"image_quality": {"is_blurry": False, "sharpness_laplacian": 120.0}}},
        ocr_confidence=90.0,
        document_text="Certificate of Completion Alex Morgan",
        extracted_fields={"reference": "AT-001", "name": "Alex"}
    )
    assert route_inst["routing_outcome"] == "INSTITUTION_REVIEW_REQUIRED"
    assert route_inst["requires_human_review"] is True
    assert route_inst["target_reviewer"] == "INSTITUTION_ADMIN"

    # Blurry image with low OCR -> Better quality upload required (Abstention)
    route_blurry = determine_review_routing(
        verification_status="POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
        field_comparison=None,
        visual_tampering=None,
        transformation_advisory={"evidence": {"image_quality": {"is_blurry": True, "sharpness_laplacian": 15.0}}},
        ocr_confidence=30.0,
        document_text="unreadable blur",
        extracted_fields={}
    )
    assert route_blurry["routing_outcome"] == "BETTER_QUALITY_REQUIRED"

    # Unauthorized issuer -> Platform admin review required
    route_admin = determine_review_routing(
        verification_status="ISSUER_NOT_AUTHORIZED",
        field_comparison=None,
        visual_tampering=None,
        transformation_advisory=None,
        ocr_confidence=80.0,
        document_text="Certificate",
        extracted_fields={}
    )
    assert route_admin["routing_outcome"] == "ADMIN_REVIEW_REQUIRED"
    assert route_admin["target_reviewer"] == "SYSTEM_ADMIN"


def test_review_decision_recording_and_permission_enforcement():
    initialize()
    ref = f"AT-REVIEW-TEST-{hashlib.md5(b'audit').hexdigest()[:8]}"

    # Setup test users
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role) VALUES(801, 'user@test.demo', 'User', 'h', 'USER')")
        conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role) VALUES(802, 'inst1@test.demo', 'Inst1', 'h', 'INSTITUTION_ADMIN')")
        conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role) VALUES(803, 'inst2@test.demo', 'Inst2', 'h', 'INSTITUTION_ADMIN')")
        conn.execute("INSERT OR IGNORE INTO users(id, email, name, password, role) VALUES(804, 'admin@test.demo', 'Admin', 'h', 'SYSTEM_ADMIN')")
        # Register test certificate belonging to Inst 802
        conn.execute(
            "INSERT OR REPLACE INTO registrations(reference, issuer_id, file_hash, transaction_hash) VALUES(?, 802, 'hash', '0xtx')",
            (ref,)
        )

    # 1. Regular USER cannot record review decisions (403 Forbidden)
    with pytest.raises(HTTPException) as exc1:
        record_review_decision(
            reference=ref,
            user={"id": 801, "role": ROLE_USER, "email": "user@test.demo"},
            decision="APPROVED",
            reason="User attempt to record review"
        )
    assert exc1.value.status_code == 403

    # 2. Unaffiliated INSTITUTION_ADMIN cannot review another institution's certificate (403 Forbidden)
    with pytest.raises(HTTPException) as exc2:
        record_review_decision(
            reference=ref,
            user={"id": 803, "role": ROLE_INSTITUTION_ADMIN, "email": "inst2@test.demo"},
            decision="APPROVED",
            reason="Foreign institution attempt to record review"
        )
    assert exc2.value.status_code == 403

    # 3. Authorized INSTITUTION_ADMIN can record review decision
    rec_inst = record_review_decision(
        reference=ref,
        user={"id": 802, "role": ROLE_INSTITUTION_ADMIN, "email": "inst1@test.demo"},
        decision="APPROVED",
        reason="Verified physical archive record; student name confirmed."
    )
    assert rec_inst["decision"] == "APPROVED"

    # 4. SYSTEM_ADMIN can record platform-level review decision
    rec_admin = record_review_decision(
        reference=ref,
        user={"id": 804, "role": ROLE_SYSTEM_ADMIN, "email": "admin@test.demo"},
        decision="FLAGGED_FOR_AUDIT",
        reason="Escalated for secondary forensic seal review."
    )
    assert rec_admin["decision"] == "FLAGGED_FOR_AUDIT"

    # 5. Audit history retrieval returns immutable log of both decisions
    history = get_review_history(ref)
    assert len(history) >= 2
    decisions = [h["decision"] for h in history]
    assert "APPROVED" in decisions
    assert "FLAGGED_FOR_AUDIT" in decisions


def test_features_contract_compatibility():
    """Verify that all 4 AI advisory features provide the required keys and aliases for frontend integration."""
    test_img = make_test_image(text="Sample Diploma")

    # 1. Visual tampering schema
    vt = analyze_visual_tampering(test_img, "jpeg")
    assert "regions" in vt
    assert "suspicious_regions" in vt
    assert "model_provenance" in vt
    assert "anomaly_score" in vt
    for r in vt["regions"]:
        assert "box" in r
        assert "bbox" in r
        assert "confidence" in r
        assert "score" in r

    # 2. Field comparison schema
    reg_record = {
        "confirmed_metadata": json.dumps({"recipient_name": "Jane", "institution_name": "Apex", "certificate_reference": "REF1"}),
        "metadata_schema_version": "2026.1"
    }
    extracted = {"recipient_name": "Jane", "institution_name": "Apex", "certificate_reference": "REF1"}
    fa = compare_fields(reg_record, extracted)
    assert "critical_field_changed" in fa
    assert "all_fields_match" in fa
    assert "reference" in fa["fields"]
    assert "institution" in fa["fields"]

    # 3. Transformation analysis schema
    ta = analyze_transformations(test_img, "jpeg", is_hash_match=False)
    assert "outcome" in ta
    assert "advisory_outcome" in ta
    assert "image_quality" in ta
    assert "skew_angle" in ta
    assert "ocr_reliability" in ta
    assert "visual_anomaly_score" in ta

    # 4. Review routing schema
    rr = determine_review_routing("POSSIBLE_TAMPERING_OR_FILE_MISMATCH", fa, vt, ta, 90.0, "diploma", extracted)
    assert "outcome" in rr
    assert "routing_outcome" in rr
    assert "layout_familiarity" in rr
    assert "calibrated_confidence" in rr
