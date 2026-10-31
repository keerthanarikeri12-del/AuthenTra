"""Confidence-based review routing and immutable reviewer decision audit trail."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from .storage import connect, canonical_role, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN

POLICY_VERSION = "2026.2"

# Configurable routing policy parameters
DEFAULT_POLICY = {
    "version": POLICY_VERSION,
    "min_ocr_confidence_clean": 75.0,
    "min_ocr_confidence_usable": 45.0,
    "max_acceptable_blur": 50.0,  # Below this, request better quality
    "require_critical_fields_match": True,
    "abstain_on_unfamiliar_layout": True,
}


def assess_layout_familiarity(text: str, fields: Dict[str, Any], quality: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Detect whether a document presents an unfamiliar layout or unrecognized institution format."""
    # Check for known template signatures
    text_lower = text.lower()
    has_cert_header = any(term in text_lower for term in ["certificate", "credential", "diploma", "degree", "transcript", "award"])
    has_institution_keyword = any(term in text_lower for term in ["university", "institute", "college", "academy", "school", "board"])

    # Check structural coherence
    known_fields_found = sum(1 for f in ["reference", "name", "course", "issue_date"] if fields.get(f))

    if not has_cert_header and known_fields_found <= 1:
        familiarity_score = 0.25
        label = "Unfamiliar or non-certificate document layout"
        is_unfamiliar = True
    elif not has_institution_keyword or known_fields_found < 2:
        familiarity_score = 0.55
        label = "Unfamiliar institution formatting or sparse layout"
        is_unfamiliar = True
    else:
        familiarity_score = 0.90
        label = "Standard certificate layout"
        is_unfamiliar = False

    return {
        "familiarity_score": round(familiarity_score, 2),
        "is_unfamiliar": is_unfamiliar,
        "label": label,
        "calibration_note": "Uncalibrated keyword heuristic; not evidence of familiarity with an issuer's template.",
        "method": "keyword_heuristic",
    }


def determine_review_routing(
    verification_status: str,
    field_comparison: Optional[Dict[str, Any]],
    visual_tampering: Optional[Dict[str, Any]],
    transformation_advisory: Optional[Dict[str, Any]],
    ocr_confidence: Optional[float],
    document_text: str,
    extracted_fields: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Route document to appropriate review workflow or automatic advisory completion."""
    pol = policy or DEFAULT_POLICY
    reasons = []
    if verification_status != "VERIFIED":
        reasons.append("Cryptographic authenticity was not established; advisory similarity cannot clear this document.")

    # 1. Check for corrupted/invalid/unreadable input
    if verification_status in ("INVALID_FILE", "VERIFICATION_UNAVAILABLE"):
        return {
            "routing_outcome": "ANALYSIS_UNAVAILABLE",
            "headline": "Analysis Unavailable",
            "policy_version": pol["version"],
            "requires_human_review": False,
            "target_reviewer": None,
            "reasons": [f"Document status is {verification_status}. Upstream verification unavailable."],
            "evidence_summary": {"verification_status": verification_status},
        }

    # 2. Check image quality for illegible uploads
    image_quality = transformation_advisory.get("evidence", {}).get("image_quality") if transformation_advisory else None
    if image_quality and image_quality.get("is_blurry") and (ocr_confidence is not None and ocr_confidence < pol["min_ocr_confidence_usable"]):
        reasons.append(f"Image sharpness is critically low ({image_quality.get('sharpness_laplacian')}) and text cannot be legibly parsed.")
        return {
            "routing_outcome": "BETTER_QUALITY_REQUIRED",
            "headline": "Better-Quality Upload Required",
            "policy_version": pol["version"],
            "requires_human_review": False,
            "target_reviewer": None,
            "reasons": reasons,
            "evidence_summary": {"ocr_confidence": ocr_confidence, "image_quality": image_quality},
        }

    # 3. Layout familiarity assessment
    layout = assess_layout_familiarity(document_text, extracted_fields, image_quality)

    # 4. Check for unapproved issuer or platform administrative concern
    if verification_status == "ISSUER_NOT_AUTHORIZED":
        reasons.append("Issuing institution authorization is suspended or pending approval on the blockchain.")
        return {
            "routing_outcome": "ADMIN_REVIEW_REQUIRED",
            "headline": "Platform Administrator Review Required",
            "policy_version": pol["version"],
            "requires_human_review": True,
            "target_reviewer": "SYSTEM_ADMIN",
            "reasons": reasons,
            "evidence_summary": {"issuer_authorized": False, "layout": layout},
        }

    # 5. Check field comparison discrepancies
    field_status = field_comparison.get("status") if field_comparison else "unavailable"
    if field_status == "CRITICAL_FIELDS_CHANGED":
        reasons.append("Critical credential fields (recipient name, grade, or course) differ from authenticated institutional records.")
    elif field_status == "FIELDS_CHANGED":
        reasons.append("Secondary credential fields differ from authenticated reference data.")
    elif field_status == "INDETERMINATE":
        reasons.append("Extracted fields contain ambiguous or low-confidence readings.")

    # 6. Check visual tampering anomalies
    visual_status = visual_tampering.get("status") if visual_tampering else "clear"
    if visual_status == "suspicious_regions_detected":
        anom_count = visual_tampering.get("summary", {}).get("model_anomalies", 0)
        ref_count = visual_tampering.get("summary", {}).get("reference_differences", 0)
        reasons.append(f"Visual forensic analysis detected {anom_count} compression anomaly patch(es) and {ref_count} reference difference(s).")

    # 7. Check model disagreement
    if field_status == "ALL_MATCHED" and visual_status == "suspicious_regions_detected":
        reasons.append("Model disagreement: Field comparison confirms text agreement, but visual forensics flags anomalous localized compression.")

    if layout["is_unfamiliar"] and verification_status != "VERIFIED":
        reasons.append(f"Unfamiliar layout: {layout['label']} ({layout['familiarity_score']:.2f}).")

    if ocr_confidence is not None and ocr_confidence < pol["min_ocr_confidence_clean"] and verification_status != "VERIFIED":
        reasons.append(f"Moderate OCR confidence ({ocr_confidence:.0f}%). Visual confirmation recommended.")

    # Routing Decision
    if any("Critical credential fields" in r for r in reasons) or any("Model disagreement" in r for r in reasons):
        outcome = "INSTITUTION_REVIEW_REQUIRED"
        headline = "Institution Review Required"
        target_reviewer = "INSTITUTION_ADMIN"
        requires_review = True
    elif reasons and verification_status != "VERIFIED":
        outcome = "INSTITUTION_REVIEW_REQUIRED"
        headline = "Institution Review Required"
        target_reviewer = "INSTITUTION_ADMIN"
        requires_review = True
    else:
        outcome = "COMPLETED_NO_REVIEW"
        headline = "Analysis Completed Without Additional Review"
        target_reviewer = None
        requires_review = False
        reasons = ["Cryptographic and advisory checks completed within nominal confidence tolerances."]

    return {
        "routing_outcome": outcome,
        "outcome": outcome,
        "headline": headline,
        "policy_version": pol["version"],
        "requires_human_review": requires_review,
        "target_reviewer": target_reviewer,
        "reasons": reasons,
        "layout_assessment": layout,
        "layout_familiarity": layout.get("familiarity_score", 0.9),
        "calibrated_confidence": None,
        "calibration_status": "unavailable",
        "evidence_summary": {
            "field_status": field_status,
            "visual_status": visual_status,
            "ocr_confidence": ocr_confidence,
            "verification_status": verification_status,
        },
    }


def record_review_decision(
    reference: str,
    user: Dict[str, Any],
    decision: str,
    reason: str,
    item_id: Optional[int] = None,
    evidence_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist an immutable human reviewer decision with actor audit trail."""
    role_canon = canonical_role(user["role"])
    if role_canon not in (ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN):
        raise HTTPException(403, "Only approved institution administrators and system administrators can submit review decisions.")

    valid_decisions = (
        "CONFIRM_VERIFIED", "FLAG_ALTERED", "REQUEST_REUPLOAD", "DISMISS",
        "APPROVED", "REJECTED", "FLAGGED_FOR_AUDIT"
    )
    if decision not in valid_decisions:
        raise HTTPException(422, f"Invalid review decision. Must be one of {', '.join(valid_decisions)}.")

    if not reason or len(reason.strip()) < 5:
        raise HTTPException(422, "A detailed explanation is required for audit compliance.")

    now_iso = datetime.now(timezone.utc).isoformat()
    evidence_json = json.dumps(evidence_snapshot or {})

    with connect() as conn:
        # Check institution boundary: institutions can only review their own certificates
        if role_canon == ROLE_INSTITUTION_ADMIN:
            reg = conn.execute("SELECT issuer_id FROM registrations WHERE reference=?", (reference,)).fetchone()
            if reg and reg["issuer_id"] != user["id"]:
                raise HTTPException(403, "Institutions may only submit review decisions for certificates they issued.")

        cursor = conn.execute(
            """
            INSERT INTO review_decisions(
                reference, item_id, actor_id, actor_role, actor_email,
                decision, reason, evidence_version, model_versions, policy_version, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference,
                item_id,
                user["id"],
                role_canon,
                user["email"],
                decision,
                reason.strip(),
                "2026.1",
                "AuthenTra Suite v1.0",
                POLICY_VERSION,
                now_iso,
            )
        )
        decision_id = cursor.lastrowid

    return {
        "id": decision_id,
        "reference": reference,
        "actor_email": user["email"],
        "actor_role": role_canon,
        "decision": decision,
        "reason": reason.strip(),
        "policy_version": POLICY_VERSION,
        "created_at": now_iso,
    }


def get_review_history(reference: str, user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Fetch immutable decision history for a given credential reference."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, reference, item_id, actor_role, actor_email, decision, reason,
                   evidence_version, model_versions, policy_version, created_at
            FROM review_decisions
            WHERE reference=?
            ORDER BY id DESC
            """,
            (reference,)
        ).fetchall()
        return [dict(r) for r in rows]
