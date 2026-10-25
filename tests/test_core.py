import hashlib
import pytest
from backend.core import decide, normalize_reference, reference_hash
from backend.documents import extract_fields, validate_document

HASH = hashlib.sha256(b"original").hexdigest()
RECORD = {"file_hash": HASH, "revoked": False}

@pytest.mark.parametrize("record,digest,approved,expected", [
    (RECORD, HASH, True, "verified"),
    (RECORD, "00"*32, True, "possible_tampering"),
    (None, HASH, True, "not_registered"),
    ({**RECORD, "revoked": True}, HASH, True, "revoked"),
    ({**RECORD, "revoked": True}, "00"*32, False, "revoked"),
    (RECORD, HASH, False, "not_verified"),
    (RECORD, "00"*32, False, "not_verified"),
])
def test_decision_precedence(record, digest, approved, expected):
    assert decide(record, digest, approved)[0] == expected

def test_normalized_reference():
    assert normalize_reference(" at-2026-001 ") == "AT-2026-001"
    assert reference_hash(" at-2026-001 ") == reference_hash("AT-2026-001")
    with pytest.raises(ValueError): normalize_reference("../../unsafe")

@pytest.mark.parametrize("data", [b"", b"pretend PDF", b"%PDF-broken", b"\x89PNG\r\n\x1a\nbroken", b"x"*(10*1024*1024+1)], ids=["empty", "fake-pdf", "corrupt-pdf", "corrupt-png", "oversized"])
def test_invalid_uploads(data):
    with pytest.raises(ValueError): validate_document(data)

def test_fields_and_date_validation():
    fields = extract_fields("Certificate ID: AT-001\nRecipient: Alex\nCourse: Math\nIssue Date: 2025-99-88")
    assert fields["reference"] == "AT-001"
    assert fields["name"] == "Alex"
    assert fields["date_valid"] is False
