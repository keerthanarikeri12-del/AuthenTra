"""Advisory transformation analysis for re-saved, compressed, rotated, or rescanned documents."""
import io
import math
from typing import Any, Dict, Optional, Tuple
import numpy as np
from PIL import Image
from scipy import ndimage


def assess_image_quality(image: Image.Image) -> Dict[str, Any]:
    """Measure edge sharpness, sensor noise, contrast, and resolution."""
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = gray.shape

    # 1. Edge sharpness via Laplacian variance
    lap = ndimage.laplace(gray)
    sharpness = float(np.var(lap))

    # 2. Noise estimation via median filter difference in background
    med = ndimage.median_filter(gray, size=3)
    noise_sigma = float(np.std(gray - med))

    # 3. Dynamic range / contrast
    p5, p95 = np.percentile(gray, [5, 95])
    contrast_range = float(p95 - p5)

    # 4. 8x8 Blockiness estimation (indicates heavy JPEG compression)
    rows_a = gray[7:-1:8, :]
    rows_b = gray[8::8, :]
    min_r = min(len(rows_a), len(rows_b))
    diff_h = np.abs(rows_a[:min_r] - rows_b[:min_r]) if min_r > 0 else np.array([0.0])

    cols_a = gray[:, 7:-1:8]
    cols_b = gray[:, 8::8]
    min_c = min(cols_a.shape[1], cols_b.shape[1])
    diff_v = np.abs(cols_a[:, :min_c] - cols_b[:, :min_c]) if min_c > 0 else np.array([0.0])
    blockiness = float(np.mean(diff_h) + np.mean(diff_v)) / 2.0

    return {
        "width": w,
        "height": h,
        "megapixels": round((w * h) / 1_000_000.0, 2),
        "sharpness_laplacian": round(sharpness, 1),
        "sharpness": round(sharpness, 1),
        "noise_estimate": round(noise_sigma, 2),
        "noise_sigma": round(noise_sigma, 2),
        "contrast_range": round(contrast_range, 1),
        "blockiness": round(blockiness, 2),
        "is_blurry": bool(sharpness < 60.0),
        "is_noisy_scan": bool(noise_sigma > 4.5),
        "is_heavily_compressed": bool(blockiness > 12.0),
    }


def estimate_skew_angle(image: Image.Image) -> float:
    """Estimate document skew or rotation angle in degrees."""
    try:
        small = image.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float32)
        # Compute horizontal vs vertical gradient energies
        gx = ndimage.sobel(arr, axis=1)
        gy = ndimage.sobel(arr, axis=0)
        angle_rad = 0.5 * np.arctan2(2.0 * np.mean(gx * gy), np.mean(gx**2 - gy**2) + 1e-6)
        angle_deg = float(np.degrees(angle_rad))
        # Keep small angle estimation within [-45, 45]
        return round(angle_deg, 1) if abs(angle_deg) <= 45.0 else 0.0
    except Exception:
        return 0.0


def analyze_transformations(
    raw_data: bytes,
    kind: str,
    field_comparison: Optional[Dict[str, Any]] = None,
    visual_analysis: Optional[Dict[str, Any]] = None,
    ocr_confidence: Optional[float] = None,
    is_hash_match: bool = False,
) -> Dict[str, Any]:
    """Combine evidence to produce an advisory outcome explaining file differences.

    NON-NEGOTIABLE TRUST RULE:
    Similarity or matching fields NEVER promote a mismatched certificate to 'Verified'.
    The primary hash-mismatch result is strictly preserved.
    """
    if is_hash_match:
        return {
            "status": "EXACT_MATCH",
            "advisory_outcome": "MATCH_CONFIRMED",
            "outcome": "MATCH_CONFIRMED",
            "headline": "Exact Byte Match",
            "explanation": "Uploaded file is identical to the registered on-chain document byte-for-byte.",
            "transformation_type": "none",
            "confidence": 1.0,
            "image_quality": None,
            "skew_angle": None,
            "ocr_reliability": ocr_confidence,
            "visual_anomaly_score": None,
            "evidence": {
                "hash_matched": True,
                "rescan_detected": False,
                "compression_detected": False,
                "reexport_detected": False,
            },
            "limitations": "Cryptographically verified original. No transformation analysis required.",
        }

    # Render a working page for quality and transformation metrics
    from .visual_tampering import load_analysis_image
    img = load_analysis_image(raw_data, kind, page_index=0)
    if img is None:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "advisory_outcome": "INSUFFICIENT_EVIDENCE",
            "outcome": "INSUFFICIENT_EVIDENCE",
            "headline": "Insufficient Evidence to Assess Transformation",
            "explanation": "Document pixels could not be rendered for physical transformation and image quality analysis.",
            "transformation_type": "unknown",
            "confidence": 0.0,
            "image_quality": None,
            "skew_angle": 0.0,
            "ocr_reliability": ocr_confidence,
            "visual_anomaly_score": None,
            "evidence": {"renderable": False},
            "limitations": "Advisory analysis only. Upload may be corrupted, encrypted, or unsupported.",
        }

    quality = assess_image_quality(img)
    skew = estimate_skew_angle(img)

    # Check PDF vs Image characteristics
    is_pdf = (kind == "pdf")
    has_scan_artifacts = quality["is_noisy_scan"] or quality["is_blurry"] or abs(skew) > 0.8
    has_compression = quality["is_heavily_compressed"]
    is_reexport = is_pdf and not has_scan_artifacts and not has_compression

    # Determine likely transformation category
    if is_reexport:
        likely_trans = "pdf_reexport"
    elif has_scan_artifacts:
        likely_trans = "physical_scan_or_photo"
    elif has_compression:
        likely_trans = "image_recompression"
    else:
        likely_trans = "re_saved_digital_copy"

    # A single image's quality cannot determine its editing history.
    likely_trans = "unknown"

    # Evaluate field comparison evidence
    field_status = field_comparison.get("status") if field_comparison else "unavailable"
    has_changed_fields = field_status in ("CRITICAL_FIELDS_CHANGED", "FIELDS_CHANGED")
    all_fields_match = field_status == "ALL_MATCHED"
    field_data_unavailable = field_status in ("unavailable", "INSUFFICIENT_DATA")

    # Evaluate visual tampering evidence
    visual_status = visual_analysis.get("status") if visual_analysis else "clear"
    has_visual_tampering = (visual_status == "suspicious_regions_detected")

    # Evidence synthesis
    if has_changed_fields:
        advisory_outcome = "CONTENT_DIFFERENCES_DETECTED"
        headline = "Content Differences Detected"
        explanation = (
            "Extracted certificate fields (such as recipient name, qualification, or date) differ "
            "from the authenticated reference confirmed by the institution. While file re-saving "
            "or rescanning alters bytes, observed text modifications indicate a substantive content change."
        )
        risk_level = "high"
    elif has_visual_tampering:
        advisory_outcome = "MIXED_EVIDENCE_REVIEW_REQUIRED"
        headline = "Mixed Evidence; Human Review Required"
        explanation = (
            "Extracted text fields appear consistent with the reference, but visual forensic analysis "
            "detected compression or structural anomalies in specific page regions. Human review is recommended."
        )
        risk_level = "medium"
    elif all_fields_match:
        advisory_outcome = "FIELDS_AGREE_RESAVE_OR_REEXPORT"
        headline = "Registered Fields Agree; Cause of File Difference Unknown"
        if likely_trans == "pdf_reexport":
            explanation = (
                "All authenticated reference fields match the institution record. The hash mismatch is consistent "
                "with re-exporting, printing to PDF, or re-saving the certificate in a different software application."
            )
        elif likely_trans == "physical_scan_or_photo":
            explanation = (
                "All authenticated reference fields match the institution record. The hash mismatch is consistent "
                "with a scanned paper copy or digital photograph of an authentic certificate."
            )
        else:
            explanation = (
                "All authenticated reference fields match the institution record. The hash mismatch is consistent "
                "with image compression, resizing, or format conversion."
            )
        explanation = (
            "Compared registered fields agree. Scanning, compression, re-export, or edits to other "
            "content could explain the different bytes. These measurements cannot determine which "
            "occurred. Institution review is required."
        )
        risk_level = "undetermined"
    else:
        advisory_outcome = "INSUFFICIENT_EVIDENCE"
        headline = "Insufficient Evidence to Assess Transformation"
        explanation = (
            "The file hash does not match the blockchain registry, and conclusive reference fields "
            "were unavailable to verify whether differences are benign (rescan/compression) or malicious."
        )
        risk_level = "medium"

    return {
        "status": advisory_outcome,
        "advisory_outcome": advisory_outcome,
        "outcome": advisory_outcome,
        "headline": headline,
        "explanation": explanation,
        "risk_level": risk_level,
        "transformation_type": likely_trans,
        "confidence": None,
        "method": "deterministic_evidence_rules_not_trained_classifier",
        "image_quality": quality,
        "skew_angle": skew,
        "ocr_reliability": ocr_confidence,
        "visual_anomaly_score": None,
        "evidence": {
            "field_comparison_status": field_status,
            "fields_match": all_fields_match,
            "fields_changed": has_changed_fields,
            "visual_anomalies_detected": has_visual_tampering,
            "ocr_confidence": ocr_confidence,
            "estimated_skew_degrees": skew,
            "image_quality": quality,
        },
        "limitations": (
            "Advisory only: visual and field similarity must NEVER establish cryptographic authenticity "
            "or override a blockchain hash mismatch. Subtle unauthorized edits may still be present."
        ),
    }
