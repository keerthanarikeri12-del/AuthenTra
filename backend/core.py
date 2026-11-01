"""Trusted decision logic, kept independent of OCR and machine learning."""
import hashlib
import re

REFERENCE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")

def normalize_reference(value: str) -> str:
    reference = value.strip().upper()
    if not REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError("Use a certificate ID of 3–64 letters, numbers, hyphens or underscores.")
    return reference

def reference_hash(reference: str) -> bytes:
    return hashlib.sha256(normalize_reference(reference).encode()).digest()

CATEGORY_MAP = {
    "verified": "VERIFIED",
    "VERIFIED": "VERIFIED",
    "possible_tampering": "POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
    "tampering_detected": "TAMPERING_DETECTED",
    "TAMPERING_DETECTED": "TAMPERING_DETECTED",
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
    "not_registered": "NOT_REGISTERED",
    "NOT_REGISTERED": "NOT_REGISTERED",
    "inconclusive": "INCONCLUSIVE",
    "INCONCLUSIVE": "INCONCLUSIVE",
    "manual_review_required": "MANUAL_REVIEW_REQUIRED",
    "MANUAL_REVIEW_REQUIRED": "MANUAL_REVIEW_REQUIRED",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "NOT_REGISTERED_OR_INCONCLUSIVE",
    "revoked": "REVOKED",
    "REVOKED": "REVOKED",
    "expired": "EXPIRED",
    "EXPIRED": "EXPIRED",
    "not_verified": "ISSUER_NOT_AUTHORIZED",
    "ISSUER_NOT_AUTHORIZED": "ISSUER_NOT_AUTHORIZED",
    "unable_to_authenticate": "VERIFICATION_UNAVAILABLE",
    "VERIFICATION_UNAVAILABLE": "VERIFICATION_UNAVAILABLE",
    "invalid_file": "INVALID_FILE",
    "INVALID_FILE": "INVALID_FILE",
}

CATEGORY_ACTIONS = {
    "VERIFIED": "No further action is required. This credential matches the on-chain record, is active, and was issued by an authorized institution.",
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "Verify that you have uploaded the exact original digital file issued by the institution. Re-exporting, re-saving, PDF compression, or rescanning alters file bytes. If this is the original file, contact the issuing institution to review.",
    "TAMPERING_DETECTED": "Protected certificate data differs from the verified issuer reference. Contact the issuing institution to review this credential.",
    "NOT_REGISTERED": "No matching registered certificate was found in the AuthenTra database. Authenticity could not be established.",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "Confirm the certificate ID with the recipient or issuing institution and re-enter the reference manually.",
    "MANUAL_REVIEW_REQUIRED": "Multiple possible registered certificates or ambiguous verification evidence were detected. Manual review by the issuing institution is required.",
    "INCONCLUSIVE": "The uploaded document could not be matched due to unreadable text, corrupted data, or insufficient certificate identity details.",
    "REVOKED": "Contact the issuing institution to inquire why this credential was revoked or to request an updated certificate.",
    "EXPIRED": "This credential has passed its validity period. Contact the issuing institution to request renewal or re-certification.",
    "ISSUER_NOT_AUTHORIZED": "Contact the institution to ensure their accreditation and wallet authorization are active on the registry.",
    "VERIFICATION_UNAVAILABLE": "Retry the verification in a few moments, or check blockchain connectivity.",
    "INVALID_FILE": "Ensure the file is an unencrypted, valid PDF, PNG, or JPEG under the maximum size limit and try again.",
}

def decide(record, uploaded_hash: str, issuer_authorized: bool) -> tuple[str, str]:
    if record is None:
        return "not_registered", "No registration exists for the supplied certificate ID. This does not prove that the document is forged."
    if record["revoked"]:
        return "revoked", "The issuer or platform owner has revoked this certificate."
    if not issuer_authorized:
        return "not_verified", "The issuing institution is not currently approved."
    if record["file_hash"].lower() != uploaded_hash.lower():
        return "possible_tampering", "This file differs from the registered original. Re-saving, re-exporting, compression, and rescanning also change file bytes. Verify the original issued file."
    return "verified", "Registered and unchanged. The file matches the registered hash, the issuer is approved, and the record is active."
