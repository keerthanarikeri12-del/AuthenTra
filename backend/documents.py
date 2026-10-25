import io
import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
import numpy as np
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
FEATURE_NAMES = ["text_length", "line_count", "digit_fraction", "uppercase_fraction", "mean_word_length", "reference_present", "name_present", "course_present", "valid_date", "suspicious_terms"]

def extract_fields(text):
    patterns = {
        "reference": r"(?:certificate[ \t]*(?:id|reference|no\.?|number)|credential[ \t]*id)[ \t]*[:#-]?[ \t]*([A-Za-z0-9][A-Za-z0-9_-]{2,63})",
        "name": r"(?:recipient|student[ \t]*name|awarded[ \t]*to|name)[ \t]*:[ \t]*([^\n\r]+)",
        "course": r"(?:course|programme|program|qualification)[ \t]*:[ \t]*([^\n\r]+)",
        "issue_date": r"(?:issue[ \t]*date|issued[ \t]*on|date)[ \t]*:[ \t]*(\d{4}-\d{2}-\d{2})",
    }
    fields = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        fields[name] = match.group(1).strip()[:150] if match else None
    fields["date_valid"] = False
    if fields["issue_date"]:
        try:
            fields["date_valid"] = date.fromisoformat(fields["issue_date"]) <= date.today()
        except ValueError:
            pass
    return fields

def feature_vector(text):
    fields = extract_fields(text)
    n = max(len(text), 1)
    words = text.split()
    return [len(text), len(text.splitlines()), sum(c.isdigit() for c in text) / n,
            sum(c.isupper() for c in text) / n, sum(map(len, words)) / max(len(words), 1),
            int(bool(fields["reference"])), int(bool(fields["name"])), int(bool(fields["course"])),
            int(fields["date_valid"]), len(re.findall(r"\b(?:edited|unofficial|invalid|placeholder)\b", text, re.I))]

def validate_document(data: bytes):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Upload a nonempty PDF, PNG or JPEG up to 10 MB.")
    if data.startswith(b"%PDF-"):
        try:
            pdf = PdfReader(io.BytesIO(data), strict=False)
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported.")
            if not 1 <= len(pdf.pages) <= 5:
                raise ValueError("Certificates may contain at most five pages.")
            if "/JavaScript" in pdf.trailer["/Root"] or "/OpenAction" in pdf.trailer["/Root"]:
                raise ValueError("PDFs with automatic actions are not supported.")
            return "pdf"
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The PDF could not be read.") from exc
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"):
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.width * img.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 20 megapixel limit.")
                img.verify()
            return "image"
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("The image could not be read.") from exc
    raise ValueError("Only genuine PDF, PNG and JPEG files are supported; renaming a file is insufficient.")

def analyze(data, kind):
    text, confidence, method = "", None, "unavailable"
    warnings = []
    if kind == "pdf":
        try:
            text = "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)[:30000]
            if len(text.strip()) >= 30:
                method = "PDF text extraction"
        except Exception:
            warnings.append("Embedded PDF text could not be extracted.")
    if method == "unavailable":
        try:
            # No uploads persist after this block, including errors and OCR timeouts.
            with tempfile.TemporaryDirectory(prefix="authentra-") as tmp:
                image_path = Path(tmp) / "page.png"
                if kind == "pdf":
                    import pypdfium2 as pdfium
                    pdf = pdfium.PdfDocument(data)
                    try:
                        page = pdf[0]
                        width, height = page.get_size()
                        scale = min(2.0, (20_000_000 / (width * height)) ** 0.5)
                        bitmap = page.render(scale=scale)
                        bitmap.to_pil().save(image_path)
                        bitmap.close()
                        page.close()
                    finally:
                        pdf.close()
                    warnings.append("Scanned PDFs: OCR analyzes the first page; the integrity check covers the whole file.")
                else:
                    with Image.open(io.BytesIO(data)) as img:
                        img.convert("RGB").save(image_path)
                result = subprocess.run([os.getenv("NODE_BINARY", "node"), str(ROOT / "scripts/ocr.mjs"), str(image_path)], capture_output=True, text=True, timeout=45, cwd=ROOT)
                if result.returncode:
                    raise RuntimeError("OCR failed")
                output = json.loads(result.stdout.strip().splitlines()[-1])
                text, confidence, method = output["text"][:30000], output["confidence"], "Tesseract OCR"
        except Exception:
            warnings.append("OCR is unavailable. Enter the certificate ID from the issuer to continue trusted checks.")
    fields = extract_fields(text)
    ai = {"status": "unavailable", "label": "AI analysis unavailable", "score": None, "scope": "Experimental model trained on synthetic text anomalies; not a probability of forgery."}
    model_path = ROOT / ".local/model.joblib"
    if text.strip() and model_path.exists():
        try:
            import joblib
            model = joblib.load(model_path)
            score = float(model.predict_proba(np.array([feature_vector(text)]))[0][1])
            ai.update(status="warning" if score >= .5 else "clear", label="Potential anomaly detected" if score >= .5 else "No major anomaly detected", score=round(score, 3))
        except Exception:
            warnings.append("The advisory model could not run; trusted verification is unaffected.")
    if confidence is not None and confidence < 70:
        warnings.append("OCR confidence is low. Confirm the extracted certificate ID.")
    return {"fields": fields, "extraction_method": method, "ocr_confidence": confidence, "ai": ai, "warnings": warnings}
