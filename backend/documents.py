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

def model_ready():
    """Check that the advisory artifact can actually load and predict."""
    try:
        import joblib
        model = joblib.load(ROOT / ".local/model.joblib")
        probabilities = model.predict_proba(np.zeros((1, len(FEATURE_NAMES))))
        return probabilities.shape == (1, 2) and bool(np.isfinite(probabilities).all())
    except Exception:
        return False


def extract_fields(text):
    patterns = {
        "reference": r"(?:(?:certificate[ \t]*(?:id|reference|no\.?|number)|credential[ \t]*id|qr(?:[ \t]*code)?[ \t]*(?:link|payload|id|ref)?)[ \t]*[:#-]?[ \t]*|(?:(?:verify|credential|cert|qr)/|\?ref=))([A-Za-z0-9][A-Za-z0-9_-]{2,63})",
        "name": r"(?:recipient|student[ \t]*name|awarded[ \t]*to|name)[ \t]*:[ \t]*([^\n\r]+)",
        "institution": r"(?:institution|issuer|university|college|organization|academy|issuing[ \t]*authority)[ \t]*:[ \t]*([^\n\r]+)",
        "course": r"(?:course|programme|program|qualification|degree)[ \t]*:[ \t]*([^\n\r]+)",
        "issue_date": r"(?:issue[ \t]*date|issued[ \t]*on|date)[ \t]*:[ \t]*(\d{4}-\d{2}-\d{2})",
        "identifier": r"(?:student[ \t]*id|student[ \t]*no|registration[ \t]*no|reg[ \t]*no|id[ \t]*no)[ \t]*:[ \t]*([A-Za-z0-9_-]{2,63})",
    }
    fields = {}
    missing_fields = []
    ambiguous_fields = []
    for name, pattern in patterns.items():
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if len(matches) > 1:
            ambiguous_fields.append(name)
            fields[name] = matches[0].strip()[:150]
        elif len(matches) == 1:
            fields[name] = matches[0].strip()[:150]
        else:
            fields[name] = None
            if name in ("reference", "name", "course", "issue_date"):
                missing_fields.append(name)

    if not fields["reference"]:
        standalone = re.findall(r"\b(AT-[A-Za-z0-9_-]{2,63})\b", text)
        if len(standalone) == 1:
            fields["reference"] = standalone[0].strip()[:150]
            if "reference" in missing_fields:
                missing_fields.remove("reference")
        elif len(standalone) > 1:
            fields["reference"] = standalone[0].strip()[:150]
            ambiguous_fields.append("reference")
            if "reference" in missing_fields:
                missing_fields.remove("reference")

    fields["date_valid"] = False
    if fields["issue_date"]:
        try:
            fields["date_valid"] = date.fromisoformat(fields["issue_date"]) <= date.today()
        except ValueError:
            ambiguous_fields.append("issue_date")

    fields["missing_fields"] = missing_fields
    fields["ambiguous_fields"] = ambiguous_fields
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
            for page in pdf.pages:
                contents = page.get_contents()
                if contents is not None:
                    contents.get_data()
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
            with Image.open(io.BytesIO(data)) as img:
                img.load()
            return "image"
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("The image could not be read.") from exc
    raise ValueError("Only genuine PDF, PNG and JPEG files are supported; renaming a file is insufficient.")

def get_node_binary():
    env_node = os.getenv("NODE_BINARY")
    if env_node and (Path(env_node).exists() or env_node == "node"):
        return env_node
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if bundled.exists():
        return str(bundled)
    return "node"

def analyze(data, kind):
    text, confidence, method = "", None, "unavailable"
    warnings = []
    if kind == "pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)[:30000]
            uris = []
            for page in reader.pages:
                if page.annotations:
                    for annot in page.annotations:
                        obj = annot.get_object()
                        if obj and isinstance(obj, dict) and "/A" in obj and isinstance(obj["/A"], dict) and "/URI" in obj["/A"]:
                            uris.append(str(obj["/A"]["/URI"]))
            if uris:
                text += "\n" + "\n".join(uris)
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
                result = subprocess.run([get_node_binary(), str(ROOT / "scripts/ocr.mjs"), str(image_path)], capture_output=True, text=True, timeout=45, cwd=ROOT)
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
