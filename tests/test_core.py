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

@pytest.mark.parametrize('image_format,filename,mime', [('PNG','image.png','image/png'),('JPEG','image.jpg','image/jpeg'),('JPEG','image.jpeg','image/jpeg')])
def test_readable_images_and_extension_match(image_format, filename, mime):
    import io
    from PIL import Image
    from backend.uploads import validate_file
    stream=io.BytesIO()
    Image.new('RGB',(40,40),'white').save(stream,format=image_format)
    assert validate_file(stream.getvalue(),filename,mime)=='image'
    with pytest.raises(ValueError,match='extension'):
        validate_file(stream.getvalue(),'image.pdf','application/pdf')


def test_encrypted_and_over_page_limit_pdfs():
    import io
    from pypdf import PdfWriter
    writer=PdfWriter()
    for _ in range(6):
        writer.add_blank_page(width=100,height=100)
    stream=io.BytesIO();writer.write(stream)
    with pytest.raises(ValueError,match='five pages'):
        validate_document(stream.getvalue())
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.encrypt('secret')
    stream=io.BytesIO();writer.write(stream)
    with pytest.raises(ValueError,match='Encrypted'):
        validate_document(stream.getvalue())
