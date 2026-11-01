"""Automatic certificate search and matching based on extracted content and metadata."""
import json
import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from .fields import (
    canonical_metadata_dict,
    normalize_recipient_name,
    normalize_institution_name,
    normalize_course,
    normalize_reference,
    normalize_date,
    normalize_grade,
    normalize_venue,
)

MATCH_THRESHOLD = 65
AMBIGUITY_MARGIN = 20

def has_usable_identity_info(ext_fields: Dict[str, Any], raw_text: str = "") -> bool:
    """Check whether the extracted document contains sufficient identity information to search."""
    if not ext_fields:
        return False
    # Check for presence of at least one meaningful identity field
    name = ext_fields.get("name")
    course = ext_fields.get("course")
    inst = ext_fields.get("institution")
    ref = ext_fields.get("reference")
    date_val = ext_fields.get("issue_date")
    ident = ext_fields.get("identifier")
    
    meaningful_fields = 0
    if name and len(str(name).strip()) >= 2:
        meaningful_fields += 1
    if course and len(str(course).strip()) >= 3:
        meaningful_fields += 1
    if inst and len(str(inst).strip()) >= 3:
        meaningful_fields += 1
    if ref and len(str(ref).strip()) >= 3:
        meaningful_fields += 1
    if date_val and len(str(date_val).strip()) >= 4:
        meaningful_fields += 1
    if ident and len(str(ident).strip()) >= 2:
        meaningful_fields += 1
        
    if meaningful_fields >= 1:
        return True
    
    # Also check if raw_text has enough certificate keywords
    clean_text = (raw_text or "").lower()
    keywords = ["certificate", "certify", "awarded", "completion", "degree", "diploma", "recipient", "institution", "university"]
    keyword_count = sum(1 for kw in keywords if kw in clean_text)
    return keyword_count >= 2


def score_candidate(
    reg_row: Dict[str, Any],
    ext_fields: Dict[str, Any],
    raw_text: str = ""
) -> Tuple[float, int, Dict[str, Any]]:
    """
    Score how closely a registered certificate matches the extracted document information.
    Returns (score, num_matching_dimensions, field_breakdown).
    """
    score = 0.0
    matching_dims = 0
    breakdown = {}

    # Extract registered metadata
    reg_meta = {}
    if reg_row.get("confirmed_metadata"):
        try:
            reg_meta = json.loads(reg_row["confirmed_metadata"])
        except Exception:
            pass
    if not reg_meta and reg_row.get("metadata"):
        try:
            reg_meta = json.loads(reg_row["metadata"])
        except Exception:
            pass

    reg_ref = reg_row.get("reference")
    reg_name = reg_meta.get("recipient_name")
    reg_course = reg_meta.get("course")
    reg_inst = reg_meta.get("institution_name") or reg_row.get("issuer_institution_name")
    reg_date = reg_meta.get("issue_date")
    reg_grade = reg_meta.get("grade")
    reg_venue = reg_meta.get("venue")

    obs_ref = ext_fields.get("reference")
    obs_name = ext_fields.get("name")
    obs_course = ext_fields.get("course")
    obs_inst = ext_fields.get("institution")
    obs_date = ext_fields.get("issue_date")
    obs_grade = ext_fields.get("grade")
    obs_venue = ext_fields.get("venue")

    text_lower = (raw_text or "").lower()
    text_upper = (raw_text or "").upper()

    # 1. Certificate ID / Reference
    if reg_ref:
        norm_reg_ref = normalize_reference(reg_ref)
        if obs_ref and normalize_reference(obs_ref) == norm_reg_ref:
            score += 100.0
            matching_dims += 1
            breakdown["reference"] = {"match": True, "type": "exact", "points": 100.0}
        elif norm_reg_ref in text_upper:
            score += 85.0
            matching_dims += 1
            breakdown["reference"] = {"match": True, "type": "text_contains", "points": 85.0}

    # 2. Recipient Name
    if reg_name:
        norm_reg_name = normalize_recipient_name(reg_name)
        if obs_name:
            norm_obs_name = normalize_recipient_name(obs_name)
            if norm_reg_name and norm_obs_name:
                if norm_reg_name == norm_obs_name:
                    score += 60.0
                    matching_dims += 1
                    breakdown["name"] = {"match": True, "type": "exact", "points": 60.0}
                else:
                    ratio = difflib.SequenceMatcher(None, norm_reg_name, norm_obs_name).ratio()
                    if ratio >= 0.82:
                        pts = round(45.0 * ratio, 1)
                        score += pts
                        matching_dims += 1
                        breakdown["name"] = {"match": True, "type": f"fuzzy_{round(ratio*100)}%", "points": pts}
                    elif norm_reg_name in norm_obs_name or norm_obs_name in norm_reg_name:
                        score += 30.0
                        matching_dims += 1
                        breakdown["name"] = {"match": True, "type": "substring", "points": 30.0}
        elif norm_reg_name and norm_reg_name in text_lower:
            score += 40.0
            matching_dims += 1
            breakdown["name"] = {"match": True, "type": "text_contains", "points": 40.0}

    # 3. Course / Award Title
    if reg_course:
        norm_reg_course = normalize_course(reg_course)
        if obs_course:
            norm_obs_course = normalize_course(obs_course)
            if norm_reg_course and norm_obs_course:
                if norm_reg_course == norm_obs_course:
                    score += 55.0
                    matching_dims += 1
                    breakdown["course"] = {"match": True, "type": "exact", "points": 55.0}
                else:
                    ratio = difflib.SequenceMatcher(None, norm_reg_course, norm_obs_course).ratio()
                    if ratio >= 0.82:
                        pts = round(45.0 * ratio, 1)
                        score += pts
                        matching_dims += 1
                        breakdown["course"] = {"match": True, "type": f"fuzzy_{round(ratio*100)}%", "points": pts}
                    elif norm_reg_course in norm_obs_course or norm_obs_course in norm_reg_course:
                        score += 30.0
                        matching_dims += 1
                        breakdown["course"] = {"match": True, "type": "substring", "points": 30.0}
        elif norm_reg_course and norm_reg_course in text_lower:
            score += 35.0
            matching_dims += 1
            breakdown["course"] = {"match": True, "type": "text_contains", "points": 35.0}

    # 4. Issuing Institution
    if reg_inst:
        norm_reg_inst = normalize_institution_name(reg_inst)
        if obs_inst:
            norm_obs_inst = normalize_institution_name(obs_inst)
            if norm_reg_inst and norm_obs_inst:
                if norm_reg_inst == norm_obs_inst:
                    score += 40.0
                    matching_dims += 1
                    breakdown["institution"] = {"match": True, "type": "exact", "points": 40.0}
                else:
                    ratio = difflib.SequenceMatcher(None, norm_reg_inst, norm_obs_inst).ratio()
                    if ratio >= 0.82:
                        pts = round(30.0 * ratio, 1)
                        score += pts
                        matching_dims += 1
                        breakdown["institution"] = {"match": True, "type": f"fuzzy_{round(ratio*100)}%", "points": pts}
                    elif norm_reg_inst in norm_obs_inst or norm_obs_inst in norm_reg_inst:
                        score += 20.0
                        matching_dims += 1
                        breakdown["institution"] = {"match": True, "type": "substring", "points": 20.0}
        elif norm_reg_inst and norm_reg_inst in text_lower:
            score += 25.0
            matching_dims += 1
            breakdown["institution"] = {"match": True, "type": "text_contains", "points": 25.0}

    # 5. Issue Date
    if reg_date:
        norm_reg_date = normalize_date(reg_date)
        if obs_date:
            norm_obs_date = normalize_date(obs_date)
            if norm_reg_date and norm_obs_date and norm_reg_date == norm_obs_date:
                score += 40.0
                matching_dims += 1
                breakdown["issue_date"] = {"match": True, "type": "exact", "points": 40.0}
        elif norm_reg_date and norm_reg_date in (raw_text or ""):
            score += 25.0
            matching_dims += 1
            breakdown["issue_date"] = {"match": True, "type": "text_contains", "points": 25.0}

    # 6. Grade / Marks
    if reg_grade and obs_grade:
        norm_reg_grade = normalize_grade(reg_grade)
        norm_obs_grade = normalize_grade(obs_grade)
        if norm_reg_grade and norm_obs_grade and norm_reg_grade == norm_obs_grade:
            score += 20.0
            matching_dims += 1
            breakdown["grade"] = {"match": True, "type": "exact", "points": 20.0}

    # 7. Venue
    if reg_venue and obs_venue:
        norm_reg_venue = normalize_venue(reg_venue)
        norm_obs_venue = normalize_venue(obs_venue)
        if norm_reg_venue and norm_obs_venue and norm_reg_venue == norm_obs_venue:
            score += 15.0
            matching_dims += 1
            breakdown["venue"] = {"match": True, "type": "exact", "points": 15.0}

    return score, matching_dims, breakdown


def search_matching_certificate(
    conn,
    ext_fields: Dict[str, Any],
    raw_text: str = "",
    threshold: float = MATCH_THRESHOLD,
    ambiguity_margin: float = AMBIGUITY_MARGIN
) -> Tuple[str, Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
    """
    Search registered certificate records and identify the matching original certificate.

    Returns:
        (status, matched_row, best_score, candidate_list)
    where status is:
        - "UNIQUE_MATCH": Exactly one registered certificate clearly matched.
        - "MULTIPLE_MATCHES": Multiple registered certificates matched closely (ambiguous).
        - "NO_MATCH": No registered certificate reached the required threshold.
        - "NO_USABLE_INFO": Uploaded document lacked usable identity fields to perform search.
        - "NO_RECORDS": Database has no registered certificate records.
    """
    if not has_usable_identity_info(ext_fields, raw_text):
        return "NO_USABLE_INFO", None, 0.0, []

    rows = conn.execute(
        """
        SELECT r.*, u.name as issuer_institution_name, u.wallet as issuer_wallet
        FROM registrations r
        LEFT JOIN users u ON r.issuer_id = u.id
        """
    ).fetchall()

    if not rows:
        return "NO_RECORDS", None, 0.0, []

    candidates = []
    for r in rows:
        r_dict = dict(r)
        score, dims, breakdown = score_candidate(r_dict, ext_fields, raw_text)
        # Viable candidate requires either reference match, or score >= threshold and dims >= 2
        is_viable = (
            score >= threshold and dims >= 2
        ) or (
            breakdown.get("reference", {}).get("match") and score >= 80.0
        )
        if is_viable:
            candidates.append({
                "row": r_dict,
                "score": score,
                "dims": dims,
                "breakdown": breakdown,
                "reference": r_dict.get("reference")
            })

    if not candidates:
        return "NO_MATCH", None, 0.0, []

    # Sort descending by score
    candidates.sort(key=lambda c: c["score"], reverse=True)

    top = candidates[0]
    if len(candidates) == 1:
        return "UNIQUE_MATCH", top["row"], top["score"], candidates

    second = candidates[1]
    score_diff = top["score"] - second["score"]

    if score_diff < ambiguity_margin:
        # Check if top and second have the same reference (duplicate rows)
        if top["reference"] == second["reference"]:
            return "UNIQUE_MATCH", top["row"], top["score"], candidates
        return "MULTIPLE_MATCHES", None, top["score"], candidates

    return "UNIQUE_MATCH", top["row"], top["score"], candidates

