"""ReportLab Platypus PDF generator for AuthenTra Certificate Verification Reports.

Produces standalone single verification reports and combined batch verification reports.
Complies strictly with safety, non-authoritative advisory disclaimers, and sanitization rules.
"""

import io
import json
import re
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FORBIDDEN_WORDS = [
    (re.compile(r"\bauthenticat\w*", re.IGNORECASE), "registered"),
    (re.compile(r"\bauthentic\w*", re.IGNORECASE), "matches the on-chain record"),
    (re.compile(r"\bgenuine\w*", re.IGNORECASE), "valid"),
    (re.compile(r"authentic", re.IGNORECASE), "matches the on-chain record"),
    (re.compile(r"genuine", re.IGNORECASE), "valid"),
]

STATUS_COLORS = {
    "VERIFIED": colors.HexColor("#16a34a"),
    "verified": colors.HexColor("#16a34a"),
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": colors.HexColor("#dc2626"),
    "possible_tampering": colors.HexColor("#dc2626"),
    "TAMPERING_DETECTED": colors.HexColor("#dc2626"),
    "tampering_detected": colors.HexColor("#dc2626"),
    "NOT_REGISTERED": colors.HexColor("#d97706"),
    "not_registered": colors.HexColor("#d97706"),
    "INCONCLUSIVE": colors.HexColor("#d97706"),
    "inconclusive": colors.HexColor("#d97706"),
    "NOT_REGISTERED_OR_INCONCLUSIVE": colors.HexColor("#d97706"),
    "REVOKED": colors.HexColor("#dc2626"),
    "revoked": colors.HexColor("#dc2626"),
    "ISSUER_NOT_AUTHORIZED": colors.HexColor("#dc2626"),
    "not_verified": colors.HexColor("#dc2626"),
    "VERIFICATION_UNAVAILABLE": colors.HexColor("#64748b"),
    "unable_to_authenticate": colors.HexColor("#64748b"),
    "INVALID_FILE": colors.HexColor("#dc2626"),
    "invalid_file": colors.HexColor("#dc2626"),
}

STATUS_LABELS = {
    "VERIFIED": "Verified",
    "verified": "Verified",
    "POSSIBLE_TAMPERING_OR_FILE_MISMATCH": "Possible Tampering or File Mismatch",
    "possible_tampering": "Possible Tampering or File Mismatch",
    "TAMPERING_DETECTED": "Tampering Detected",
    "tampering_detected": "Tampering Detected",
    "NOT_REGISTERED": "Not Registered",
    "not_registered": "Not Registered",
    "INCONCLUSIVE": "Inconclusive",
    "inconclusive": "Inconclusive",
    "NOT_REGISTERED_OR_INCONCLUSIVE": "Not Registered or Inconclusive",
    "REVOKED": "Revoked",
    "revoked": "Revoked",
    "ISSUER_NOT_AUTHORIZED": "Issuer Not Authorized",
    "not_verified": "Issuer Not Authorized",
    "VERIFICATION_UNAVAILABLE": "Verification Unavailable",
    "unable_to_authenticate": "Verification Unavailable",
    "INVALID_FILE": "Invalid File",
    "invalid_file": "Invalid File",
}


def sanitize_text(text) -> str:
    """Filter forbidden words ('authentic', 'genuine'), replace control characters, and normalize."""
    if text is None:
        return "N/A"
    s = str(text).strip()
    if not s or s.lower() == "none" or s.lower() == "null":
        return "N/A"

    for pattern, replacement in FORBIDDEN_WORDS:
        s = pattern.sub(replacement, s)

    # Filter unprintable control characters except newline and tab
    s = "".join(c if (c.isprintable() or c in "\n\r\t") else " " for c in s)
    return s.strip() or "N/A"


def escape_paragraph(text, max_len: int = None) -> str:
    """Sanitize and XML-escape text safely for ReportLab Paragraphs."""
    s = sanitize_text(text)
    if s == "N/A":
        return "N/A"
    if max_len and len(s) > max_len:
        s = s[:max_len] + "..."
    return saxutils.escape(s)


def format_bytes(b) -> str:
    if b is None or b == "" or b == "N/A":
        return "N/A"
    try:
        n = int(b)
        if n >= 1024 * 1024:
            return f"{n / (1024 * 1024):.2f} MB ({n:,} bytes)"
        if n >= 1024:
            return f"{n / 1024:.1f} KB ({n:,} bytes)"
        return f"{n} bytes"
    except (ValueError, TypeError):
        return "N/A"


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw total page count and footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#475569"))

        # Footer divider line
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 42, 612 - 36, 42)

        # Left / Right top line of footer
        v_id = getattr(self, "_verification_id_str", "AuthenTra")
        gen_at = getattr(self, "_generated_at_str", datetime.now(timezone.utc).isoformat())

        left_text = f"Verification #{v_id} | Generated: {gen_at}"
        right_text = f"Page {self._pageNumber} of {page_count}"

        # Safe encoding for drawString
        left_text = left_text.encode("latin-1", "replace").decode("latin-1")
        right_text = right_text.encode("latin-1", "replace").decode("latin-1")

        self.drawString(36, 30, left_text)
        self.drawRightString(612 - 36, 30, right_text)

        # Bottom disclaimer
        footer_note = (
            "This report reflects the state at the time shown. "
            "A certificate may be revoked or an issuer suspended later."
        )
        self.drawString(36, 18, footer_note)

        self.restoreState()


def get_styles():
    ss = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )
    h2_style = ParagraphStyle(
        "SectionHeading",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b"),
    )
    bold_label = ParagraphStyle(
        "ReportBoldLabel",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
    )
    hash_style = ParagraphStyle(
        "HashStyle",
        parent=ss["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        wordWrap="CJK",
        textColor=colors.HexColor("#0f172a"),
    )
    advisory_quote = ParagraphStyle(
        "AdvisoryQuote",
        parent=ss["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#475569"),
    )
    disclaimer_style = ParagraphStyle(
        "DisclaimerStyle",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#475569"),
    )
    callout_style = ParagraphStyle(
        "CalloutStyle",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#b45309"),
    )

    return {
        "title": title_style,
        "subtitle": subtitle_style,
        "h2": h2_style,
        "body": body_style,
        "label": bold_label,
        "hash": hash_style,
        "advisory": advisory_quote,
        "disclaimer": disclaimer_style,
        "callout": callout_style,
    }


def normalize_snapshot(snapshot: dict) -> dict:
    """Normalize snapshot data, ensuring compatibility with old/legacy rows."""
    s = dict(snapshot or {})

    # Strip any sensitive internal keys
    for secret_key in [
        "jwt", "token", "access_token", "refresh_token", "cookie", "cookies",
        "private_key", "secret", "password", "file_bytes", "data", "data_bytes",
        "issuer_signature", "raw_bytes"
    ]:
        s.pop(secret_key, None)

    # Normalize status & category
    status_raw = s.get("verification_status") or s.get("category") or s.get("status") or "INCONCLUSIVE"
    status_key = status_raw.upper() if isinstance(status_raw, str) else "INCONCLUSIVE"
    label = s.get("label") or STATUS_LABELS.get(status_raw) or STATUS_LABELS.get(status_key, status_raw)

    checks = s.get("checks")
    if isinstance(checks, str):
        try:
            checks = json.loads(checks)
        except Exception:
            checks = {}
    elif not isinstance(checks, dict):
        checks = {}

    fields = s.get("fields")
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except Exception:
            fields = {}
    elif not isinstance(fields, dict):
        fields = {}

    ai = s.get("ai")
    if isinstance(ai, str):
        try:
            ai = json.loads(ai)
        except Exception:
            ai = {}
    elif not isinstance(ai, dict):
        ai = {}

    def parse_dict(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return {}
        return val if isinstance(val, dict) else {}

    field_analysis = parse_dict(s.get("field_analysis"))
    visual_tampering = parse_dict(s.get("visual_tampering"))
    transformation_analysis = parse_dict(s.get("transformation_analysis"))
    review_routing = parse_dict(s.get("review_routing"))

    # Hash match evaluation
    hash_matches = s.get("hash_matches")
    if hash_matches is None and "hash_matches" in checks:
        hash_matches = checks.get("hash_matches")

    if hash_matches is True:
        hash_match_str = "Yes (Exact Match)"
    elif hash_matches is False:
        hash_match_str = "No (Mismatch)"
    else:
        hash_match_str = "N/A"

    # Issuer authorized evaluation
    issuer_auth = s.get("issuer_authorized")
    if issuer_auth is None and "issuer_approved" in checks:
        issuer_auth = checks.get("issuer_approved")

    if issuer_auth is True:
        issuer_auth_str = "Yes"
    elif issuer_auth is False:
        issuer_auth_str = "No"
    else:
        issuer_auth_str = "N/A"

    # Active / Revoked evaluation
    is_active = checks.get("active")
    if is_active is True:
        record_status_str = "Active (Not Revoked)"
    elif is_active is False or status_key == "REVOKED":
        record_status_str = "Revoked"
    elif s.get("blockchain_record_status") in ("ACTIVE", "REVOKED"):
        record_status_str = "Active (Not Revoked)" if s.get("blockchain_record_status") == "ACTIVE" else "Revoked"
    else:
        record_status_str = "N/A"

    return {
        **s,
        "normalized_status": status_key,
        "label": label,
        "checks": checks,
        "fields": fields,
        "ai": ai,
        "field_analysis": field_analysis,
        "visual_tampering": visual_tampering,
        "transformation_analysis": transformation_analysis,
        "review_routing": review_routing,
        "hash_match_str": hash_match_str,
        "issuer_auth_str": issuer_auth_str,
        "record_status_str": record_status_str,
    }


def build_verification_story(snap: dict, verifier_email: str, styles: dict) -> list:
    """Build the flowable elements for a single verification report."""
    story = []

    # 4.a Header
    story.append(Paragraph("AuthenTra - Certificate Verification Report", styles["title"]))
    story.append(Spacer(1, 2))
    story.append(
        Paragraph(
            "Independent cryptographic verification record and blockchain registry confirmation.",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#087d6a"), spaceAfter=8))

    # Legacy snapshot notice if applicable
    if snap.get("is_legacy") or snap.get("legacy_note"):
        legacy_table = Table(
            [[Paragraph("<b>Notice:</b> This record was recorded before report snapshots were enabled. "
                        "Some detailed metadata may be unavailable (N/A).", styles["callout"])]],
            colWidths=[540],
        )
        legacy_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fefce8")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#f59e0b")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(legacy_table)
        story.append(Spacer(1, 6))

    # 4.b Summary Table
    story.append(Paragraph("Verification Summary", styles["h2"]))

    status_color = STATUS_COLORS.get(snap["normalized_status"], colors.HexColor("#0f172a"))
    status_label_text = snap["label"]

    status_badge_html = f'<font color="{status_color.hexval()}"><b>{escape_paragraph(status_label_text)}</b></font>'

    summary_data = [
        [
            Paragraph("Verification ID", styles["label"]),
            Paragraph(f"#{snap.get('id') or 'N/A'}", styles["body"]),
            Paragraph("Verified At (UTC)", styles["label"]),
            Paragraph(escape_paragraph(snap.get("verified_at")), styles["body"]),
        ],
        [
            Paragraph("File Name", styles["label"]),
            Paragraph(escape_paragraph(snap.get("file_name"), max_len=120), styles["body"]),
            Paragraph("File Size", styles["label"]),
            Paragraph(format_bytes(snap.get("file_size")), styles["body"]),
        ],
        [
            Paragraph("Verifier Account", styles["label"]),
            Paragraph(escape_paragraph(verifier_email), styles["body"]),
            Paragraph("Certificate ID", styles["label"]),
            Paragraph(f"<b>{escape_paragraph(snap.get('reference'))}</b>", styles["body"]),
        ],
        [
            Paragraph("Verification Result", styles["label"]),
            Paragraph(status_badge_html, styles["body"]),
            Paragraph("Processing Time", styles["label"]),
            Paragraph(f"{snap.get('duration_ms')} ms" if snap.get("duration_ms") is not None else "N/A", styles["body"]),
        ],
    ]

    summary_table = Table(summary_data, colWidths=[110, 160, 110, 160])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(summary_table)
    story.append(Spacer(1, 6))

    # 4.c Plain-language meaning and next_action
    msg_text = escape_paragraph(snap.get("message"))
    next_action_text = escape_paragraph(snap.get("next_action"))

    action_data = [
        [
            Paragraph("<b>Status Meaning</b>", styles["label"]),
            Paragraph(msg_text, styles["body"]),
        ],
        [
            Paragraph("<b>Recommended Next Action</b>", styles["label"]),
            Paragraph(next_action_text, styles["body"]),
        ],
    ]
    action_table = Table(action_data, colWidths=[130, 410])
    action_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(action_table)
    story.append(Spacer(1, 8))

    # 4.d Blockchain & Cryptographic Evidence
    story.append(Paragraph("Blockchain & Cryptographic Evidence", styles["h2"]))

    uploaded_hash = snap.get("file_hash") or "N/A"
    onchain_hash = snap.get("registered_hash") or "N/A"
    issuer_name = snap.get("issuer_name") or "N/A"
    issuer_wallet = snap.get("issuer") or "N/A"
    contract_addr = snap.get("contract_address") or "N/A"
    tx_hash = snap.get("transaction_hash") or "N/A"
    block_num = str(snap.get("block_number")) if snap.get("block_number") is not None else "N/A"
    net_str = f"{snap.get('network_name') or 'Chain'} (ID: {snap.get('chain_id') or 'N/A'})"

    evidence_data = [
        [
            Paragraph("Uploaded SHA-256", styles["label"]),
            Paragraph(escape_paragraph(uploaded_hash), styles["hash"]),
        ],
        [
            Paragraph("On-Chain Registered Hash", styles["label"]),
            Paragraph(escape_paragraph(onchain_hash), styles["hash"]),
        ],
        [
            Paragraph("Hash Match", styles["label"]),
            Paragraph(f"<b>{snap['hash_match_str']}</b>", styles["body"]),
        ],
        [
            Paragraph("Issuing Institution", styles["label"]),
            Paragraph(f"{escape_paragraph(issuer_name)} (Wallet: <code>{escape_paragraph(issuer_wallet)}</code>)", styles["body"]),
        ],
        [
            Paragraph("Issuer Authorization", styles["label"]),
            Paragraph(f"<b>{snap['issuer_auth_str']}</b>", styles["body"]),
        ],
        [
            Paragraph("Blockchain Status", styles["label"]),
            Paragraph(f"<b>{snap['record_status_str']}</b>", styles["body"]),
        ],
        [
            Paragraph("Registry Smart Contract", styles["label"]),
            Paragraph(escape_paragraph(contract_addr), styles["hash"]),
        ],
        [
            Paragraph("Blockchain Network", styles["label"]),
            Paragraph(escape_paragraph(net_str), styles["body"]),
        ],
        [
            Paragraph("Registration Transaction", styles["label"]),
            Paragraph(escape_paragraph(tx_hash), styles["hash"]),
        ],
        [
            Paragraph("Block Number", styles["label"]),
            Paragraph(escape_paragraph(block_num), styles["body"]),
        ],
    ]

    evidence_table = Table(evidence_data, colWidths=[150, 390])
    evidence_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(evidence_table)
    story.append(Spacer(1, 8))

    # 4.e Advisory Analysis (non-authoritative)
    story.append(Paragraph("Advisory Analysis (non-authoritative)", styles["h2"]))

    # Mandatory disclaimer sentence
    story.append(
        Paragraph(
            "AI and field analysis are advisory and never override the blockchain and hash result.",
            styles["advisory"],
        )
    )
    story.append(Spacer(1, 4))

    ai_obj = snap["ai"]
    ai_status = ai_obj.get("status") or "N/A"
    ai_label = ai_obj.get("label") or "N/A"
    ai_score_raw = ai_obj.get("score")
    if ai_score_raw is not None and str(ai_score_raw).strip() not in ("", "N/A", "None", "null"):
        try:
            ai_score = f"{float(ai_score_raw):.3f}"
        except (ValueError, TypeError):
            ai_score = "N/A"
    else:
        ai_score = "N/A"
    ai_summary = f"{ai_status.upper()} - {ai_label} (Score: {ai_score})"

    ocr_raw = snap.get("ocr_confidence")
    if ocr_raw is not None and str(ocr_raw).strip() not in ("", "N/A", "None", "null"):
        try:
            ocr_conf = f"{round(float(ocr_raw))}%"
        except (ValueError, TypeError):
            ocr_conf = "N/A"
    else:
        ocr_conf = "N/A"
    extract_method = snap.get("extraction_method") or "N/A"

    # Extracted fields summary
    fields = snap["fields"]
    field_items = []
    for k in ["name", "course", "institution", "issue_date", "grade", "reference"]:
        if fields.get(k):
            field_items.append(f"<b>{k.replace('_', ' ').capitalize()}:</b> {escape_paragraph(fields[k])}")
    fields_str = "<br/>".join(field_items) if field_items else "N/A"

    # Analysis sub-modules
    fa = snap["field_analysis"]
    fa_summary = fa.get("explanation") or fa.get("status") or "N/A"

    vt = snap["visual_tampering"]
    vt_headline = vt.get("headline")
    if vt_headline:
        vt_text = escape_paragraph(vt_headline)
    elif vt.get("status") == "clean":
        vt_text = "No suspicious visual editing or compression anomalies detected."
    elif vt.get("accessible_description"):
        desc = vt["accessible_description"]
        if "Region 1" in desc:
            desc = desc.split("Region 1")[0].strip()
        elif "region(s) of interest" in desc:
            parts = re.split(r"(?:Region\s+\d+|\[\d+\.\d+)", desc)
            desc = parts[0].strip()
        desc = desc.rstrip(" .:,")
        vt_text = escape_paragraph(desc + "." if desc else "Visual inspection completed.")
    elif vt.get("status") == "suspicious_regions_detected":
        total_regions = vt.get("summary", {}).get("total_regions") or len(vt.get("regions", []))
        vt_text = f"Visual inspection identified {total_regions} region(s) with compression variations (advisory only)."
    else:
        st = vt.get("status")
        vt_text = escape_paragraph(st.replace("_", " ").capitalize()) if st else "N/A"

    ta = snap["transformation_analysis"]
    ta_headline = ta.get("headline") or ta.get("advisory_outcome") or "N/A"
    ta_expl = ta.get("explanation") or ""
    if ta_expl:
        ta_html = f"<b>{escape_paragraph(ta_headline)}</b>: {escape_paragraph(ta_expl)}"
    else:
        ta_html = f"<b>{escape_paragraph(ta_headline)}</b>"

    rr = snap["review_routing"]
    rr_headline = rr.get("headline") or rr.get("routing_outcome") or "N/A"
    rr_review = "Yes" if rr.get("requires_human_review") else "No"
    rr_html = f"<b>{escape_paragraph(rr_headline)}</b> (Human Review Required: {rr_review})"

    advisory_data = [
        [
            Paragraph("AI Heuristic Model", styles["label"]),
            Paragraph(escape_paragraph(ai_summary), styles["body"]),
        ],
        [
            Paragraph("OCR Confidence & Method", styles["label"]),
            Paragraph(f"{ocr_conf} ({escape_paragraph(extract_method)})", styles["body"]),
        ],
        [
            Paragraph("Extracted Document Data", styles["label"]),
            Paragraph(fields_str, styles["body"]),
        ],
        [
            Paragraph("Field Comparison", styles["label"]),
            Paragraph(escape_paragraph(fa_summary), styles["body"]),
        ],
        [
            Paragraph("Visual Tampering", styles["label"]),
            Paragraph(vt_text, styles["body"]),
        ],
        [
            Paragraph("Transformation Advisory", styles["label"]),
            Paragraph(ta_html, styles["body"]),
        ],
        [
            Paragraph("Review Routing", styles["label"]),
            Paragraph(rr_html, styles["body"]),
        ],
    ]

    advisory_table = Table(advisory_data, colWidths=[150, 390])
    advisory_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(advisory_table)
    story.append(Spacer(1, 10))

    # 4.g Disclaimer
    disclaimer_box = Table(
        [[
            Paragraph(
                "<b>Disclaimer:</b> This is a record of a verification check, not a legal certificate or guarantee.",
                styles["disclaimer"],
            )
        ]],
        colWidths=[540],
    )
    disclaimer_box.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(KeepTogether(disclaimer_box))

    return story


def build_report_pdf(snapshot: dict, verifier_email: str) -> bytes:
    """Build a downloadable PDF verification report for a single certificate check."""
    snap = normalize_snapshot(snapshot)
    styles = get_styles()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48,
    )

    story = build_verification_story(snap, verifier_email, styles)

    # Pass dynamic footer metadata to NumberedCanvas
    class BoundCanvas(NumberedCanvas):
        _verification_id_str = str(snap.get("id") or "Report")
        _generated_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    doc.build(story, canvasmaker=BoundCanvas)
    return buffer.getvalue()


def build_batch_report_pdf(snapshots: list[dict], verifier_email: str) -> bytes:
    """Build a combined PDF report for multiple certificate checks with a summary table first."""
    normalized_list = [normalize_snapshot(s) for s in (snapshots or [])]
    styles = get_styles()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48,
    )

    story = []

    # Summary Page
    story.append(Paragraph("AuthenTra - Batch Verification Summary Report", styles["title"]))
    story.append(Spacer(1, 2))
    story.append(
        Paragraph(
            "Consolidated multi-file verification review and cryptographic audit record.",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#087d6a"), spaceAfter=10))

    meta_table = Table(
        [
            [
                Paragraph("<b>Total Certificates Verified:</b>", styles["body"]),
                Paragraph(str(len(normalized_list)), styles["body"]),
                Paragraph("<b>Verifier Email:</b>", styles["body"]),
                Paragraph(escape_paragraph(verifier_email), styles["body"]),
            ],
            [
                Paragraph("<b>Generated At (UTC):</b>", styles["body"]),
                Paragraph(datetime.now(timezone.utc).isoformat(), styles["body"]),
                Paragraph("<b>Verification IDs:</b>", styles["body"]),
                Paragraph(", ".join(f"#{s.get('id')}" for s in normalized_list), styles["body"]),
            ],
        ],
        colWidths=[140, 130, 120, 150],
    )
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # Consolidated Batch Table
    story.append(Paragraph("Batch Summary Table", styles["h2"]))

    table_rows = [
        [
            Paragraph("<b>ID</b>", styles["label"]),
            Paragraph("<b>Reference</b>", styles["label"]),
            Paragraph("<b>File Name</b>", styles["label"]),
            Paragraph("<b>Result</b>", styles["label"]),
            Paragraph("<b>Hash Match</b>", styles["label"]),
            Paragraph("<b>Active</b>", styles["label"]),
        ]
    ]

    for item in normalized_list:
        st_color = STATUS_COLORS.get(item["normalized_status"], colors.HexColor("#0f172a"))
        st_html = f'<font color="{st_color.hexval()}"><b>{escape_paragraph(item["label"])}</b></font>'

        table_rows.append([
            Paragraph(f"#{item.get('id') or 'N/A'}", styles["body"]),
            Paragraph(f"<b>{escape_paragraph(item.get('reference'))}</b>", styles["body"]),
            Paragraph(escape_paragraph(item.get("file_name"), max_len=40), styles["body"]),
            Paragraph(st_html, styles["body"]),
            Paragraph(item["hash_match_str"], styles["body"]),
            Paragraph(item["record_status_str"], styles["body"]),
        ])

    batch_summary_table = Table(table_rows, colWidths=[40, 95, 145, 125, 70, 65])
    batch_summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(batch_summary_table)
    story.append(Spacer(1, 14))

    # Page break before individual certificate reports
    story.append(PageBreak())

    for idx, snap in enumerate(normalized_list):
        story.extend(build_verification_story(snap, verifier_email, styles))
        if idx < len(normalized_list) - 1:
            story.append(PageBreak())

    all_ids_str = ",".join(str(s.get("id")) for s in normalized_list)

    class BoundBatchCanvas(NumberedCanvas):
        _verification_id_str = f"Batch ({all_ids_str})"
        _generated_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    doc.build(story, canvasmaker=BoundBatchCanvas)
    return buffer.getvalue()
