import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["AUTHENTRA_DEMO"] = "1"
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import pypdfium2 as pdfium
from backend.storage import initialize, seed_demo, connect, ROOT
from backend.main import _persist_reference_preview
from backend.fields import canonical_metadata_dict, compute_metadata_commitment, FIELD_SCHEMA_VERSION

def prepare_demo():
    samples = ROOT / "samples"
    samples.mkdir(exist_ok=True)
    def certificate(filename, reference, name="Alex Morgan"):
        target = samples / filename
        if target.exists(): return
        c = canvas.Canvas(str(target), pagesize=(842,595), invariant=1)
        c.setFillColor(HexColor('#fbfcf8')); c.rect(0,0,842,595,fill=1,stroke=0)
        c.setStrokeColor(HexColor('#26574e')); c.setLineWidth(2); c.rect(25,25,792,545)
        c.setFillColor(HexColor('#18483f')); c.setFont('Helvetica-Bold',17); c.drawCentredString(421,510,'MERIDIAN INSTITUTE OF TECHNOLOGY')
        c.setFont('Helvetica',10); c.drawCentredString(421,482,'DEMONSTRATION CERTIFICATE - NOT AN ACTUAL QUALIFICATION')
        c.setFont('Times-Roman',34); c.drawCentredString(421,407,'Certificate of Completion')
        c.setFont('Helvetica',15); c.drawString(115,332,f'Recipient: {name}')
        c.drawString(115,291,'Course: Blockchain Fundamentals')
        c.drawString(115,250,'Issue Date: 2025-06-12')
        c.drawString(115,209,f'Certificate ID: {reference}')
        c.setFont('Helvetica',12); c.drawString(115,150,'Awarded for successfully completing the required training programme.')
        c.setFont('Helvetica-Bold',11); c.drawString(115,95,'AuthenTra Research Demonstration')
        c.setFont('Helvetica',9); c.drawRightString(727,95,'Original digital file / Verify by certificate ID')
        c.save()

    certificate('original.pdf','AT-2026-0001')
    certificate('modified.pdf','AT-2026-0001','Taylor Smith')
    certificate('unregistered.pdf','AT-2026-9999')
    certificate('revoked.pdf','AT-2026-0002')
    if not (samples / 'scan.png').exists():
        pdf = pdfium.PdfDocument(str(samples / 'original.pdf'))
        try:
            page = pdf[0]; bitmap = page.render(scale=1.5); bitmap.to_pil().save(samples / 'scan.png'); bitmap.close(); page.close()
        finally:
            pdf.close()
    initialize()
    chain = None
    try:
        from backend.registry import Registry
        chain = Registry()
        seed_demo(chain)
    except Exception as exc:
        print(f"Blockchain registry unavailable for demo seeding: {exc}")

    with connect() as conn:
        issuer = dict(conn.execute("SELECT * FROM users WHERE email='issuer@authentra.demo'").fetchone())
    for filename, reference in [('original.pdf','AT-2026-0001'),('revoked.pdf','AT-2026-0002')]:
        data_bytes = (samples / filename).read_bytes()
        _persist_reference_preview(data_bytes, 'pdf', reference, issuer['id'])
        meta = {
            "recipient_name": "Alex Morgan",
            "institution_name": "Meridian Institute of Technology",
            "course": "Blockchain Fundamentals",
            "certificate_reference": reference,
            "issue_date": "2025-06-12",
            "grade": None,
            "venue": None,
        }
        canon = canonical_metadata_dict(meta)
        meta_json = json.dumps(canon)
        comm = compute_metadata_commitment(meta, reference, hashlib.sha256(data_bytes).hexdigest().lower())
        with connect() as conn:
            conn.execute(
                "UPDATE registrations SET confirmed_metadata=?, metadata_commitment=?, metadata_schema_version=? WHERE reference=?",
                (meta_json, comm, FIELD_SCHEMA_VERSION, reference)
            )
            if chain:
                try:
                    if chain.lookup(reference) is None:
                        from backend.main import register_document
                        register_document(data_bytes, 'pdf', reference, issuer)
                except Exception:
                    pass

    if chain:
        try:
            rec = chain.lookup('AT-2026-0002')
            if rec and not rec['revoked']:
                chain.revoke('AT-2026-0002', issuer['wallet'])
        except Exception:
            pass
    print('Demo certificates ready: original, modified, unregistered, revoked and scanned copy.')


if __name__ == "__main__":
    prepare_demo()
