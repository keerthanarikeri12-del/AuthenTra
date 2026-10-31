import io
import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
import numpy as np
from PIL import Image, UnidentifiedImageError, ImageEnhance
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
FEATURE_NAMES = ["text_length", "line_count", "digit_fraction", "uppercase_fraction", "mean_word_length", "reference_present", "name_present", "course_present", "valid_date", "suspicious_terms"]

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12
}


def normalize_extracted_date(clean):
    if not clean:
        return None
    clean = " ".join(clean.strip().split())
    # ISO YYYY-MM-DD or YYYY/MM/DD
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", clean)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            pass
    # DD Month YYYY
    m_written = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,\s]+(\d{4})$", clean)
    if m_written:
        mon = MONTH_MAP.get(m_written.group(2).lower())
        if mon:
            try:
                return date(int(m_written.group(3)), mon, int(m_written.group(1))).isoformat()
            except ValueError:
                pass
    # Month DD, YYYY
    m_written2 = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", clean)
    if m_written2:
        mon = MONTH_MAP.get(m_written2.group(1).lower())
        if mon:
            try:
                return date(int(m_written2.group(3)), mon, int(m_written2.group(2))).isoformat()
            except ValueError:
                pass
    # DD/MM/YYYY or MM/DD/YYYY
    m_slash = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", clean)
    if m_slash:
        p1, p2, yr = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
        try:
            return date(yr, p2, p1).isoformat()
        except ValueError:
            try:
                return date(yr, p1, p2).isoformat()
            except ValueError:
                pass
    return clean


def prepare_image_for_ocr(img: Image.Image) -> Image.Image:
    """Preprocess certificate image to maximize Tesseract OCR recognition accuracy."""
    try:
        w, h = img.size
        if max(w, h) < 1600 and w * h > 0:
            scale = min(2.5, 1800.0 / max(w, h))
            if scale > 1.05:
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        gray = img.convert("L")
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(1.6)
        return enhanced
    except Exception:
        return img.convert("RGB")


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
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    fields = {
        "reference": None,
        "name": None,
        "institution": None,
        "course": None,
        "issue_date": None,
        "identifier": None,
        "grade": None,
        "venue": None,
    }
    missing_fields = []
    ambiguous_fields = []

    # 1. Reference / Certificate ID
    ref_patterns = [
        r"(?:(?:certificate[ \t]*(?:id|reference|ref|no\.?|number|code)|credential[ \t]*(?:id|ref|number)|cert(?:ificate)?[ \t]*(?:id|ref|no\.?)|qr(?:[ \t]*code)?[ \t]*(?:link|payload|id|ref)?)[ \t]*[:;#=-]?[ \t]*|(?:(?:verify|credential|cert|qr)/|\?ref=))([A-Za-z0-9][A-Za-z0-9_.-]{2,63})",
    ]
    ref_matches = []
    for pat in ref_patterns:
        for m in re.findall(pat, text, flags=re.IGNORECASE):
            clean_m = m.strip().rstrip(".:;,#")
            if clean_m and clean_m not in ref_matches:
                ref_matches.append(clean_m[:150])

    if not ref_matches:
        for m in re.findall(r"\b(AT-[A-Za-z0-9_-]{2,63})\b", text):
            clean_m = m.strip()
            if clean_m not in ref_matches:
                ref_matches.append(clean_m[:150])

    if not ref_matches:
        for m in re.findall(r"\b([A-Z]{2,10}-[A-Za-z0-9_.-]{2,63})\b", text):
            clean_m = m.strip().rstrip(".:;,#")
            if clean_m not in ref_matches:
                ref_matches.append(clean_m[:150])

    if len(ref_matches) == 1:
        fields["reference"] = ref_matches[0]
    elif len(ref_matches) > 1:
        fields["reference"] = ref_matches[0]
        ambiguous_fields.append("reference")
    else:
        fields["reference"] = None
        missing_fields.append("reference")

    # 2. Recipient Name
    name_patterns = [
        r"(?:this[ \t]+is[ \t]+to[ \t]+certify[ \t]+that|certifies[ \t]+that|certify[ \t]+that)[ \t]*[:;#=-]?[ \t]*([^\n\r]+)",
        r"(?:awarded[ \t]+(?:to|tc|ta)|presented[ \t]+to|conferred[ \t]+(?:upon|on)|given[ \t]+to)[ \t]*[:;#=-]?[ \t]*([^\n\r]+)",
        r"(?:recipient(?:'s)?[ \t]*(?:name)?|student[ \t]*(?:name)?|candidate(?:'s)?[ \t]*(?:name)?|graduate(?:'s)?[ \t]*(?:name)?|name)[ \t]*[:;#=-][ \t]*([^\n\r]+)",
        r"(?:recipient|student)[ \t]+([A-Z][a-zA-Z]+[ \t]+[A-Z][a-zA-Z]+)",
    ]
    name_matches = []
    for pat in name_patterns:
        found = re.findall(pat, text, flags=re.IGNORECASE)
        for m in found:
            clean_name = m.strip().strip(";:.,- ")
            clean_name = re.sub(r"^(?:mr\.?|ms\.?|mrs\.?|dr\.?|prof\.?)\s+", "", clean_name, flags=re.I)
            clean_name = re.split(r"\b(?:for|has|having|who|in|on)\b", clean_name, flags=re.I)[0].strip()
            if clean_name and len(clean_name) >= 2 and not clean_name.lower().startswith("of ") and clean_name not in name_matches:
                name_matches.append(clean_name[:150])

    if not name_matches:
        for i, line in enumerate(lines[:-1]):
            if re.match(r"^(?:this[ \t]+is[ \t]+to[ \t]+certify[ \t]+that|certifies[ \t]+that|awarded[ \t]+(?:to|tc|ta)|presented[ \t]+to|recipient(?:'s)?[ \t]*(?:name)?[ \t]*:?)$", line, re.I):
                next_line = lines[i+1].strip()
                if next_line and not re.search(r"^(?:for|in|course|date|certificate|demonstration)", next_line, re.I):
                    name_matches.append(next_line[:150])
                    break

    if len(name_matches) == 1:
        fields["name"] = name_matches[0]
    elif len(name_matches) > 1:
        fields["name"] = name_matches[0]
        ambiguous_fields.append("name")
    else:
        fields["name"] = None
        missing_fields.append("name")

    # 3. Institution / Issuer
    inst_patterns = [
        r"(?:institution|issuer|issuing[ \t]+authority|organization|academy|university|college)[ \t]*[:;#=-][ \t]*([^\n\r]+)",
        r"(?:issued[ \t]+by|awarded[ \t]+by|authorized[ \t]+by)[ \t]*[:;#=-]?[ \t]*([^\n\r]+)",
    ]
    inst_matches = []
    for pat in inst_patterns:
        found = re.findall(pat, text, flags=re.IGNORECASE)
        for m in found:
            clean_inst = m.strip().strip(";:.,- ")
            if clean_inst and len(clean_inst) >= 3 and clean_inst not in inst_matches:
                inst_matches.append(clean_inst[:150])

    if not inst_matches:
        for line in lines[:4]:
            if re.search(r"\b(?:university|institute|college|academy|school|polytechnic|board)\b", line, re.I):
                if not re.search(r"^(?:certificate|diploma|degree|recipient|awarded|course|date|demonstration)\b", line, re.I):
                    inst_matches.append(line.strip()[:150])
                    break

    if len(inst_matches) == 1:
        fields["institution"] = inst_matches[0]
    elif len(inst_matches) > 1:
        fields["institution"] = inst_matches[0]
        ambiguous_fields.append("institution")
    else:
        fields["institution"] = None

    # 4. Course / Qualification
    course_patterns = [
        r"(?:course|programme|program|qualification|degree|major)[ \t]*[:;#=-][ \t]*([^\n\r]+)",
        r"(?:course|programme|program)[ \t]+([A-Z][^\n\r]+)",
        r"(?:for[ \t]+successfully[ \t]+completing[ \t]+(?:the[ \t]+course[ \t]+in[ \t]+)?)([^\n\r]+)",
        r"(?:certificate[ \t]+of[ \t]+completion[ \t]+in[ \t]+)([^\n\r]+)",
        r"(?:degree[ \t]+of[ \t]+(?:bachelor|master|doctor)[ \t]+of[ \t]+[^\n\r]+)",
    ]
    course_matches = []
    for pat in course_patterns:
        found = re.findall(pat, text, flags=re.IGNORECASE)
        for m in found:
            clean_course = m.strip().strip(";:.,- ")
            clean_course = re.sub(r"^(?:in|of)\s+", "", clean_course, flags=re.I)
            clean_course = re.split(r"\b(?:with|held|on|dated|at|grade|issued|awarded)\b", clean_course, flags=re.I)[0].strip()
            if clean_course and len(clean_course) >= 3 and clean_course not in course_matches:
                course_matches.append(clean_course[:150])

    if len(course_matches) == 1:
        fields["course"] = course_matches[0]
    elif len(course_matches) > 1:
        fields["course"] = course_matches[0]
        ambiguous_fields.append("course")
    else:
        fields["course"] = None
        missing_fields.append("course")

    # 5. Issue Date
    date_patterns = [
        r"(?:issue[ \t]*date|issued[ \t]*(?:on|date)?|date[ \t]*(?:of[ \t]*issue)?|dated|awarded[ \t]*on|date)[ \t]*[:;#=-]?[ \t]*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        r"(?:issue[ \t]*date|issued[ \t]*(?:on|date)?|date[ \t]*(?:of[ \t]*issue)?|dated|awarded[ \t]*on|date)[ \t]*[:;#=-]?[ \t]*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+[,\s]+\d{4})",
        r"(?:issue[ \t]*date|issued[ \t]*(?:on|date)?|date[ \t]*(?:of[ \t]*issue)?|dated|awarded[ \t]*on|date)[ \t]*[:;#=-]?[ \t]*([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
        r"(?:issue[ \t]*date|issued[ \t]*(?:on|date)?|date[ \t]*(?:of[ \t]*issue)?|dated|awarded[ \t]*on|date)[ \t]*[:;#=-]?[ \t]*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[,\s]+\d{4})\b",
    ]
    date_matches = []
    for pat in date_patterns:
        found = re.findall(pat, text, flags=re.IGNORECASE)
        for d in found:
            norm = normalize_extracted_date(d.strip())
            if norm and norm not in date_matches:
                date_matches.append(norm)

    if len(date_matches) == 1:
        fields["issue_date"] = date_matches[0]
    elif len(date_matches) > 1:
        fields["issue_date"] = date_matches[0]
        ambiguous_fields.append("issue_date")
    else:
        fields["issue_date"] = None
        missing_fields.append("issue_date")

    # 6. Venue / Location ("yeenu")
    venue_patterns = [
        r"(?:venue|location|place|centre|center|campus|city|held[ \t]+at)[ \t]*[:;#=-]?[ \t]*([^\n\r]+)",
    ]
    for pat in venue_patterns:
        v_matches = re.findall(pat, text, flags=re.IGNORECASE)
        if v_matches:
            fields["venue"] = v_matches[0].strip().strip(";:.,- ")[:150]
            break

    # 7. Grade / Classification
    grade_patterns = [
        r"(?:grade|result|classification|gpa|marks|honours|honors|class)[ \t]*[:;#=-]?[ \t]*([^\n\r]+)",
        r"\b(First[ \t]*Class[ \t]*Honours|Second[ \t]*Class[ \t]*Honours|Distinction|Merit|Pass|Summa[ \t]*Cum[ \t]*Laude|Magna[ \t]*Cum[ \t]*Laude)\b",
    ]
    for pat in grade_patterns:
        g_matches = re.findall(pat, text, flags=re.IGNORECASE)
        if g_matches:
            fields["grade"] = g_matches[0].strip().strip(";:.,- ")[:150]
            break

    # 8. Identifier (Student ID / Registration NO)
    id_patterns = [
        r"(?:student[ \t]*id|student[ \t]*no|registration[ \t]*no|reg[ \t]*no|id[ \t]*no|roll[ \t]*no)[ \t]*[:;#=-]?[ \t]*([A-Za-z0-9_-]{2,63})",
    ]
    for pat in id_patterns:
        id_matches = re.findall(pat, text, flags=re.IGNORECASE)
        if id_matches:
            fields["identifier"] = id_matches[0].strip()[:150]
            break

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
                        prep_img = prepare_image_for_ocr(bitmap.to_pil())
                        prep_img.save(image_path)
                        bitmap.close()
                        page.close()
                    finally:
                        pdf.close()
                    warnings.append("Scanned PDFs: OCR analyzes the first page; the integrity check covers the whole file.")
                else:
                    with Image.open(io.BytesIO(data)) as img:
                        prep_img = prepare_image_for_ocr(img)
                        prep_img.save(image_path)
                result = subprocess.run([get_node_binary(), str(ROOT / "scripts/ocr.mjs"), str(image_path)], capture_output=True, text=True, timeout=45, cwd=ROOT)
                if result.returncode:
                    raise RuntimeError("OCR failed")
                json_candidates = [l for l in result.stdout.strip().splitlines() if l.strip().startswith("{")]
                output = json.loads(json_candidates[-1] if json_candidates else result.stdout.strip().splitlines()[-1])
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
