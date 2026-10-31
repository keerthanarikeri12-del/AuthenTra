"""Field-level change detection and authenticated reference metadata management."""
import hashlib
import json
import re
from datetime import date
from typing import Any, Dict, Optional, Tuple

FIELD_SCHEMA_VERSION = "2026.1"

CRITICAL_FIELDS = ["recipient_name", "certificate_reference", "course", "issue_date", "grade"]
ALL_FIELDS = ["recipient_name", "institution_name", "course", "certificate_reference", "issue_date", "grade"]

FIELD_ALIASES = {
    "name": "recipient_name",
    "recipient_name": "recipient_name",
    "student_name": "recipient_name",
    "institution": "institution_name",
    "institution_name": "institution_name",
    "issuer": "institution_name",
    "course": "course",
    "qualification": "course",
    "programme": "course",
    "program": "course",
    "degree": "course",
    "reference": "certificate_reference",
    "certificate_reference": "certificate_reference",
    "certificate_id": "certificate_reference",
    "id": "certificate_reference",
    "issue_date": "issue_date",
    "date": "issue_date",
    "grade": "grade",
    "result": "grade",
    "classification": "grade",
    "gpa": "grade",
}


def canonicalize_field_key(key: str) -> str:
    norm = key.strip().lower().replace(" ", "_")
    return FIELD_ALIASES.get(norm, norm)


def canonical_metadata_dict(raw: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Produce a standardized, versioned dictionary containing canonical certificate fields."""
    canonical = {field: None for field in ALL_FIELDS}
    if not isinstance(raw, dict):
        return canonical

    for k, v in raw.items():
        ck = canonicalize_field_key(k)
        if ck in canonical and v is not None:
            val_str = str(v).strip()
            if val_str:
                canonical[ck] = val_str[:200]
    return canonical


def compute_metadata_commitment(fields: Dict[str, Any], reference: str, file_hash: str) -> str:
    """Deterministic cryptographic commitment binding confirmed metadata to reference and file bytes."""
    canonical = canonical_metadata_dict(fields)
    payload = {
        "schema_version": FIELD_SCHEMA_VERSION,
        "reference": reference.strip().upper(),
        "file_hash": file_hash.strip().lower(),
        "fields": {k: canonical[k] for k in sorted(canonical.keys())},
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# Conservative, field-specific normalizers (never silently equate different values)

def _normalize_whitespace(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    return " ".join(val.strip().split())


def normalize_recipient_name(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    # Strip honorific prefixes conservatively if identical name follows
    clean = re.sub(r"^(?:mr\.?|ms\.?|mrs\.?|dr\.?|prof\.?)\s+", "", clean, flags=re.IGNORECASE)
    return clean.lower()


def normalize_institution_name(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    return clean.lower()


def normalize_course(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    return clean.lower()


def normalize_reference(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    return clean.upper()


MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12
}


def normalize_date(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    # Strict ISO 8601 YYYY-MM-DD or YYYY/MM/DD
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", clean)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return clean

    # Written format e.g. "12 June 2025" or "12th June 2025"
    m_written = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})$", clean)
    if m_written:
        day, mon_str, year = int(m_written.group(1)), m_written.group(2).lower(), int(m_written.group(3))
        mon = MONTH_MAP.get(mon_str)
        if mon:
            try:
                return date(year, mon, day).isoformat()
            except ValueError:
                pass

    # Written format e.g. "June 12, 2025"
    m_written2 = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", clean)
    if m_written2:
        mon_str, day, year = m_written2.group(1).lower(), int(m_written2.group(2)), int(m_written2.group(3))
        mon = MONTH_MAP.get(mon_str)
        if mon:
            try:
                return date(year, mon, day).isoformat()
            except ValueError:
                pass

    return clean.lower()


def normalize_grade(val: Optional[str]) -> Optional[str]:
    clean = _normalize_whitespace(val)
    if not clean:
        return None
    # Strip unnecessary spaces around slashes e.g. "3.8 / 4.0" -> "3.8/4.0"
    clean = re.sub(r"\s*/\s*", "/", clean)
    return clean.upper()


NORMALIZERS = {
    "recipient_name": normalize_recipient_name,
    "institution_name": normalize_institution_name,
    "course": normalize_course,
    "certificate_reference": normalize_reference,
    "issue_date": normalize_date,
    "grade": normalize_grade,
}


def compare_single_field(field_name: str, registered_val: Optional[str], observed_val: Optional[str],
                         ambiguous_fields: Optional[list] = None, unreadable: bool = False,
                         extraction_method: Optional[str] = None) -> Dict[str, Any]:
    """Compare a single field conservatively with transparent reasoning and explicit uncertainty."""
    ambiguous_fields = ambiguous_fields or []
    registered_clean = _normalize_whitespace(registered_val)
    observed_clean = _normalize_whitespace(observed_val)

    normalizer = NORMALIZERS.get(field_name, _normalize_whitespace)
    reg_norm = normalizer(registered_val)
    obs_norm = normalizer(observed_val)

    if unreadable:
        return {
            "registered_value": registered_clean,
            "observed_value": observed_clean,
            "status": "unreadable",
            "explanation": f"Document text was unreadable or OCR confidence was insufficient to extract {field_name.replace('_', ' ')}.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }

    if field_name in ambiguous_fields:
        return {
            "registered_value": registered_clean,
            "observed_value": observed_clean,
            "status": "ambiguous",
            "explanation": f"Multiple conflicting values were observed for {field_name.replace('_', ' ')} in document text.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }

    if not registered_clean:
        if not observed_clean:
            return {
                "registered_value": None,
                "observed_value": None,
                "status": "missing",
                "explanation": f"No registered or observed value present for {field_name.replace('_', ' ')}.",
                "extraction_method": extraction_method or "unknown",
                "is_critical": field_name in CRITICAL_FIELDS,
            }
        return {
            "registered_value": None,
            "observed_value": observed_clean,
            "status": "unregistered_field",
            "explanation": f"Observed in document, but no reference value was confirmed by issuer.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }

    if not observed_clean:
        return {
            "registered_value": registered_clean,
            "observed_value": None,
            "status": "missing",
            "explanation": f"Expected {field_name.replace('_', ' ')} '{registered_clean}' was not found in document text.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }

    # Both values exist: compare normalized forms
    if reg_norm == obs_norm:
        return {
            "registered_value": registered_clean,
            "observed_value": observed_clean,
            "status": "matched",
            "explanation": f"Observed value matches institution-confirmed reference.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }
    else:
        return {
            "registered_value": registered_clean,
            "observed_value": observed_clean,
            "status": "changed",
            "explanation": f"Observed '{observed_clean}' differs from institution-confirmed '{registered_clean}'.",
            "extraction_method": extraction_method or "unknown",
            "is_critical": field_name in CRITICAL_FIELDS,
        }


def compare_fields(registered_record: Optional[Dict[str, Any]], extracted_fields: Dict[str, Any],
                   extraction_method: Optional[str] = None, ocr_confidence: Optional[float] = None,
                   trusted_issuer: Optional[str] = None, trusted_hash: Optional[str] = None) -> Dict[str, Any]:
    """Execute conservative, deterministic field-level comparison against authenticated reference."""
    if not registered_record or not registered_record.get("confirmed_metadata"):
        return {
            "status": "unavailable",
            "schema_version": FIELD_SCHEMA_VERSION,
            "explanation": "No authenticated reference metadata is bound to this registration record. Field comparison is unavailable.",
            "summary": {
                "total_fields": 0,
                "matched": 0,
                "changed": 0,
                "missing": 0,
                "ambiguous": 0,
                "unreadable": 0,
            },
            "fields": {},
            "commitment_verified": False,
        }

    try:
        confirmed = json.loads(registered_record["confirmed_metadata"])
        if not isinstance(confirmed, dict):
            raise ValueError("Metadata must be an object")
    except (TypeError, ValueError):
        return {
            "status": "unavailable",
            "schema_version": registered_record.get("metadata_schema_version", FIELD_SCHEMA_VERSION),
            "explanation": "Corrupted reference metadata payload in registration record.",
            "summary": {"total_fields": 0, "matched": 0, "changed": 0, "missing": 0, "ambiguous": 0, "unreadable": 0},
            "fields": {},
            "commitment_verified": False,
        }

    # Verify commitment if stored
    commitment_stored = registered_record.get("metadata_commitment")
    file_hash = registered_record.get("file_hash", "")
    reference = registered_record.get("reference", "")
    commitment_verified = False
    if commitment_stored:
        expected = compute_metadata_commitment(confirmed, reference, file_hash)
        commitment_verified = (expected.lower() == commitment_stored.lower())

    signature_verified = False
    if trusted_issuer is not None:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            signer = Account.recover_message(
                encode_defunct(hexstr=commitment_stored),
                signature=registered_record.get("issuer_signature"),
            )
            signature_verified = signer.lower() == trusted_issuer.lower()
            commitment_verified = commitment_verified and signature_verified and (
                file_hash.lower().removeprefix("0x") == (trusted_hash or "").lower().removeprefix("0x")
            )
        except Exception:
            commitment_verified = False

    if not commitment_verified:
        return {
            "status": "unavailable", "schema_version": FIELD_SCHEMA_VERSION,
            "explanation": "Reference metadata commitment, issuer signature, or blockchain binding is missing or invalid; comparison cannot be trusted.",
            "fields": {}, "summary": {}, "commitment_verified": False,
            "critical_field_changed": False, "all_fields_match": False,
        }

    ambiguous = [canonicalize_field_key(f) for f in extracted_fields.get("ambiguous_fields", [])]
    unreadable = extraction_method == "unavailable" or (ocr_confidence is not None and ocr_confidence < 30)

    canonical_observed = canonical_metadata_dict(extracted_fields)
    canonical_reg = canonical_metadata_dict(confirmed)

    field_results = {}
    counts = {"matched": 0, "changed": 0, "missing": 0, "ambiguous": 0, "unreadable": 0, "unregistered_field": 0}

    for f in ALL_FIELDS:
        reg_val = canonical_reg.get(f)
        obs_val = canonical_observed.get(f)
        # Check alias in extracted_fields
        if not obs_val:
            for alias, target in FIELD_ALIASES.items():
                if target == f and extracted_fields.get(alias):
                    obs_val = str(extracted_fields[alias])
                    break

        f_res = compare_single_field(
            f, reg_val, obs_val,
            ambiguous_fields=ambiguous,
            unreadable=unreadable,
            extraction_method=extraction_method
        )
        field_results[f] = f_res
        st = f_res["status"]
        if st in counts:
            counts[st] += 1

    # Determine overall status
    critical_changed = any(field_results[f]["status"] == "changed" for f in CRITICAL_FIELDS if field_results[f]["registered_value"])
    any_changed = counts["changed"] > 0
    expected_results = [r for r in field_results.values() if r["registered_value"]]
    all_matched = bool(expected_results) and all(r["status"] == "matched" for r in expected_results)

    if critical_changed:
        overall_status = "CRITICAL_FIELDS_CHANGED"
        summary_explanation = "One or more critical fields (recipient name, reference, course, or date) differ from the institution record."
    elif any_changed:
        overall_status = "FIELDS_CHANGED"
        summary_explanation = "Secondary fields differ from the registered reference record."
    elif counts["ambiguous"] > 0 or counts["unreadable"] > 0:
        overall_status = "INDETERMINATE"
        summary_explanation = "Document fields contain ambiguous or low-confidence unreadable values. Human review required."
    elif all_matched:
        overall_status = "ALL_MATCHED"
        summary_explanation = "All registered fields were extracted and match the stored reference. This does not establish authenticity of unregistered content."
    else:
        overall_status = "INSUFFICIENT_DATA"
        summary_explanation = "No fields could be reliably extracted or compared against the reference record."

    if "certificate_reference" in field_results and "reference" not in field_results:
        field_results["reference"] = field_results["certificate_reference"]
    if "institution_name" in field_results and "institution" not in field_results:
        field_results["institution"] = field_results["institution_name"]

    return {
        "status": overall_status,
        "schema_version": registered_record.get("metadata_schema_version", FIELD_SCHEMA_VERSION),
        "explanation": summary_explanation,
        "critical_field_changed": critical_changed,
        "all_fields_match": all_matched,
        "summary": counts,
        "fields": field_results,
        "commitment_verified": commitment_verified,
        "reference_trust": "issuer_signature_and_chain_hash" if signature_verified else "database_commitment_integrity_only",
        "signature_verified": signature_verified,
        "issuer_signature": registered_record.get("issuer_signature"),
        "committed_at": registered_record.get("committed_at"),
    }
