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

def decide(record, uploaded_hash: str, issuer_authorized: bool) -> tuple[str, str]:
    if record is None:
        return "not_registered", "No registration exists for the supplied certificate ID. This does not prove that the document is forged."
    if record["revoked"]:
        return "revoked", "The issuer or platform owner has revoked this certificate."
    if not issuer_authorized:
        return "not_verified", "The issuing institution is not currently approved."
    if record["file_hash"].lower() != uploaded_hash.lower():
        return "possible_tampering", "This file differs from the registered original. Re-saving, compression and scanning can also change a file. Verify the original issued file."
    return "verified", "Registered and unchanged. The file matches the registered hash, the issuer is approved, and the record is active."
