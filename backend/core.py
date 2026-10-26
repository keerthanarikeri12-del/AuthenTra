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
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "POSSIBLE_TAMPERING_OR_FILE_MISMATCH",
    "not_registered": "NOT_REGISTERED_OR_INCONCLUSIVE",
    "inconclusive": "NOT_REGISTERED_OR_INCONCLUSIVE",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "NOT_REGISTERED_OR_INCONCLUSIVE",
    "revoked": "REVOKED",
    "REVOKED": "REVOKED",
    "not_verified": "ISSUER_NOT_AUTHORIZED",
    "ISSUER_NOT_AUTHORIZED": "ISSUER_NOT_AUTHORIZED",
    "unable_to_authenticate": "VERIFICATION_UNAVAILABLE",
    "VERIFICATION_UNAVAILABLE": "VERIFICATION_UNAVAILABLE",
    "invalid_file": "INVALID_FILE",
    "INVALID_FILE": "INVALID_FILE",
}

CATEGORY_ACTIONS = {
    "VERIFIED": "No further action is required. This credential is confirmed authentic, active, and issued by an authorized institution.",
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "Verify that you have uploaded the exact original digital file issued by the institution. Re-exporting, re-saving, PDF compression, or rescanning alters file bytes. If this is the original file, contact the issuing institution to review.",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "Confirm the certificate ID with the recipient or issuing institution and re-enter the reference manually.",
    "REVOKED": "Contact the issuing institution to inquire why this credential was revoked or to request an updated certificate.",
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
