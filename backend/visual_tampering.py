"""Visual tampering localization for certificate documents and images."""
import io
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageStat

ROOT = Path(__file__).resolve().parents[1]

# Configurable processing bounds
CONFIG = {
    "max_pages": 5,
    "max_pixels": 20_000_000,
    "max_seconds": 15.0,
    "max_memory_mb": 150,
    "ela_quality": 90,
    "ela_scale": 15,
    "anomaly_threshold": 22.0,  # Mean difference threshold for suspicious patches
    "min_patch_fraction": 0.001,  # Minimum bounding box size relative to page area
    "max_patch_fraction": 0.5,    # Discard whole-page shifts as global differences
}


def render_pdf_page(data: bytes, page_index: int = 0, target_scale: float = 1.5) -> Optional[Image.Image]:
    """Render a single PDF page safely to a PIL Image without altering original bytes."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            if page_index >= len(pdf):
                return None
            page = pdf[page_index]
            w, h = page.get_size()
            max_scale = min(target_scale, (CONFIG["max_pixels"] / (w * h)) ** 0.5)
            bitmap = page.render(scale=max_scale)
            pil_img = bitmap.to_pil().convert("RGB")
            bitmap.close()
            page.close()
            return pil_img
        finally:
            pdf.close()
    except Exception:
        return None


def load_analysis_image(data: bytes, kind: str, page_index: int = 0) -> Optional[Image.Image]:
    """Load a rendered working copy for visual analysis, preserving untouched original bytes."""
    if kind == "pdf":
        return render_pdf_page(data, page_index=page_index)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > CONFIG["max_pixels"]:
                return None
            return img.convert("RGB")
    except Exception:
        return None


def compute_ela_image(image: Image.Image, quality: int = 90, scale: int = 15) -> Tuple[Image.Image, float]:
    """Perform Error Level Analysis (ELA) to highlight compression-rate discontinuities."""
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    resaved = Image.open(buffer)

    diff = ImageChops.difference(image, resaved)
    stat = ImageStat.Stat(diff)
    mean_diff = float(np.mean(stat.mean))

    # Scale difference for visualization and thresholding
    enhanced = ImageEnhance.Brightness(diff).enhance(scale)
    return enhanced, mean_diff


def detect_suspicious_patches(ela_image: Image.Image, original_size: Tuple[int, int],
                              grid_w: int = 16, grid_h: int = 24) -> List[Dict[str, Any]]:
    """Partition ELA into grid patches and identify localized compression outliers."""
    arr = np.asarray(ela_image.convert("L"), dtype=np.float32)
    h, w = arr.shape
    step_y = max(h // grid_h, 8)
    step_x = max(w // grid_w, 8)

    patch_means = []
    patch_coords = []
    for y in range(0, h - step_y + 1, step_y):
        for x in range(0, w - step_x + 1, step_x):
            sub = arr[y:y + step_y, x:x + step_x]
            val = float(np.mean(sub))
            patch_means.append(val)
            patch_coords.append((x, y, step_x, step_y))

    if not patch_means:
        return []

    global_mean = float(np.mean(patch_means))
    global_std = float(np.std(patch_means))
    # Threshold at 2.0 standard deviations above mean, with minimum absolute floor
    cutoff = max(global_mean + 2.0 * global_std, CONFIG["anomaly_threshold"])

    anomalies = []
    for (x, y, pw, ph), val in zip(patch_coords, patch_means):
        if val > cutoff:
            # Normalized coordinates (0.0 to 1.0)
            norm_x = round(x / w, 4)
            norm_y = round(y / h, 4)
            norm_w = round(pw / w, 4)
            norm_h = round(ph / h, 4)
            area_frac = norm_w * norm_h
            if CONFIG["min_patch_fraction"] <= area_frac <= CONFIG["max_patch_fraction"]:
                confidence = round(min(0.99, max(0.5, (val - cutoff) / (global_std + 1e-5) * 0.15 + 0.5)), 2)
                anomalies.append({
                    "box": [norm_x, norm_y, norm_w, norm_h],
                    "raw_score": round(val, 2),
                    "confidence": confidence,
                    "type": "model_anomaly",
                    "label": "Suspected local compression or splicing anomaly",
                    "explanation": f"Unusual JPEG error level ({val:.1f} vs avg {global_mean:.1f}) in region [{norm_x}, {norm_y}], suggesting localized modification or insertion."
                })

    # Merge overlapping/adjacent boxes
    return _merge_boxes(anomalies)


def _merge_boxes(boxes: List[Dict[str, Any]], iou_thresh: float = 0.2) -> List[Dict[str, Any]]:
    if not boxes:
        return []
    merged = []
    used = set()
    for i, b1 in enumerate(boxes):
        if i in used:
            continue
        cur_x1, cur_y1, cur_w, cur_h = b1["box"]
        cur_x2, cur_y2 = cur_x1 + cur_w, cur_y1 + cur_h
        cur_score = b1["raw_score"]
        cur_conf = b1["confidence"]
        used.add(i)

        for j in range(i + 1, len(boxes)):
            if j in used:
                continue
            b2 = boxes[j]
            x1, y1, w, h = b2["box"]
            x2, y2 = x1 + w, y1 + h

            # Check overlap or adjacency (within 0.03 normalized distance)
            if not (x2 < cur_x1 - 0.03 or x1 > cur_x2 + 0.03 or y2 < cur_y1 - 0.03 or y1 > cur_y2 + 0.03):
                cur_x1 = min(cur_x1, x1)
                cur_y1 = min(cur_y1, y1)
                cur_x2 = max(cur_x2, x2)
                cur_y2 = max(cur_y2, y2)
                cur_score = max(cur_score, b2["raw_score"])
                cur_conf = max(cur_conf, b2["confidence"])
                used.add(j)

        box_coords = [round(cur_x1, 4), round(cur_y1, 4), round(cur_x2 - cur_x1, 4), round(cur_y2 - cur_y1, 4)]
        merged.append({
            "box": box_coords,
            "bbox": box_coords,
            "raw_score": cur_score,
            "confidence": cur_conf,
            "score": cur_conf,
            "type": "model_anomaly",
            "label": "Suspected local compression anomaly",
            "explanation": f"Localized compression level anomaly spanning coordinates [{round(cur_x1, 3)}, {round(cur_y1, 3)}, {round(cur_x2 - cur_x1, 3)}, {round(cur_y2 - cur_y1, 3)}]."
        })
    return merged[:10]  # Cap at top 10 regions to avoid clutter


def align_and_compare_reference(submitted: Image.Image, reference: Image.Image) -> Tuple[List[Dict[str, Any]], float]:
    """Align submitted document with authorized reference image and detect structural differences."""
    sub_gray = submitted.convert("L")
    ref_resized = reference.convert("L").resize(sub_gray.size, Image.Resampling.BILINEAR)

    arr_sub = np.asarray(sub_gray, dtype=np.float32)
    arr_ref = np.asarray(ref_resized, dtype=np.float32)

    # Pixel-level absolute difference
    diff = np.abs(arr_sub - arr_ref)
    mean_diff = float(np.mean(diff))

    # Difference components describe pixels, not a probability of tampering.
    from scipy import ndimage
    mask = diff > 30.0
    grouped = ndimage.binary_dilation(mask, iterations=2)
    labels, _ = ndimage.label(grouped)
    h, w = diff.shape
    regions = []
    for index, bounds in enumerate(ndimage.find_objects(labels), start=1):
        if bounds is None:
            continue
        ys, xs = bounds
        changed = int(np.count_nonzero(mask[ys, xs] & (labels[ys, xs] == index)))
        if changed < 8:
            continue
        box = [round(xs.start / w, 4), round(ys.start / h, 4),
               round((xs.stop - xs.start) / w, 4), round((ys.stop - ys.start) / h, 4)]
        regions.append({
            "box": box, "bbox": box, "changed_pixels": changed,
            "raw_score": round(float(np.mean(diff[ys, xs])), 2),
            "confidence": None, "score": None, "type": "reference_difference",
            "label": "Pixel difference from supplied reference",
            "explanation": "Pixel difference only; editing history is unknown.",
        })
    regions.sort(key=lambda r: (-r["changed_pixels"], r["box"]))
    return regions[:8], mean_diff


# Optional pluggable trained model registry
_REGISTERED_MODEL: Optional[Dict[str, Any]] = None


def register_tampering_model(
    name: str,
    predict_fn,
    technique: str = "Trained Neural Tampering Localization",
    license: Optional[str] = "Proprietary",
    limitations: Optional[str] = "Trained model inference. Requires validation on out-of-distribution certificate templates.",
) -> None:
    """Register a trained machine learning model for blind tampering localization."""
    global _REGISTERED_MODEL
    _REGISTERED_MODEL = {
        "name": name,
        "predict_fn": predict_fn,
        "technique": technique,
        "license": license,
        "limitations": limitations,
    }


def unregister_tampering_model() -> None:
    """Unregister the currently active tampering model (restoring uncalibrated default)."""
    global _REGISTERED_MODEL
    _REGISTERED_MODEL = None


def get_active_tampering_model() -> Optional[Dict[str, Any]]:
    """Return the active model configuration if available."""
    return _REGISTERED_MODEL


def analyze_visual_tampering(data: bytes, kind: str, reference_image_data: Optional[bytes] = None,
                             page_number: int = 1) -> Dict[str, Any]:
    """Comprehensive visual tampering localization supporting PDFs and images."""
    t0 = time.perf_counter()
    provenance = {
        "model_name": None,
        "technique": "Uncalibrated image comparison; no trained localization model installed",
        "license": None,
        "hardware": "CPU-optimized",
        "limitations": "Advisory evidence. Cannot distinguish deliberate forgery from intentional re-saving or multi-generation JPEG artifacts without reference verification.",
    }

    if not data or len(data) > 10 * 1024 * 1024:
        return {
            "status": "unavailable",
            "page": page_number,
            "regions": [],
            "accessible_description": "Visual tampering analysis is unavailable: input file exceeds size boundaries or is empty.",
            "provenance": provenance,
            "duration_ms": 0.0,
        }

    # Preserving original bytes: load separate rendered copy
    page_img = load_analysis_image(data, kind, page_index=max(0, page_number - 1))
    if page_img is None:
        return {
            "status": "unavailable",
            "page": page_number,
            "regions": [],
            "accessible_description": "Visual tampering analysis could not render the document page for visual inspection.",
            "provenance": provenance,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    model_config = get_active_tampering_model()

    # ELA alone cannot establish tampering, particularly on rendered PDFs/PNGs.
    # Do not turn compression edges into fabricated model predictions.
    if not reference_image_data and not model_config:
        return {
            "status": "unavailable", "page": page_number,
            "regions": [], "suspicious_regions": [], "anomaly_score": None,
            "model_provenance": provenance["technique"], "provenance": provenance,
            "accessible_description": "No trained tampering localization model or authorized reference image is available. No conclusion about visual alteration can be made.",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    model_regions = []
    anomaly_score = None
    if model_config:
        try:
            pred_regions, pred_score = model_config["predict_fn"](page_img)
            model_regions = pred_regions or []
            anomaly_score = pred_score
            provenance["model_name"] = model_config["name"]
            provenance["technique"] = model_config["technique"]
            provenance["license"] = model_config["license"]
            provenance["limitations"] = model_config["limitations"]
        except Exception:
            model_regions = []

    # Compression diagnostics are not trained-model detections.
    ela_img, ela_mean = compute_ela_image(page_img, quality=CONFIG["ela_quality"], scale=CONFIG["ela_scale"])

    # 2. Reference Image Alignment (if provided from authorized institution source)
    reference_regions = []
    ref_diff_mean = None
    if reference_image_data:
        ref_img = load_analysis_image(reference_image_data, "image", page_index=0)
        if ref_img:
            reference_regions, ref_diff_mean = align_and_compare_reference(page_img, ref_img)

    all_regions = []
    # Clearly distinguish model-detected suspicious regions from reference-image differences
    for r in model_regions:
        r["page"] = page_number
        all_regions.append(r)
    for r in reference_regions:
        r["confidence"] = None
        r["score"] = None
        r["explanation"] = "Pixel difference after resizing only; alignment and the cause of this difference are not established."
        r["page"] = page_number
        all_regions.append(r)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Construct accessible textual description
    if not all_regions:
        if reference_image_data:
            acc_text = f"Page {page_number}: No pixel differences exceeded the comparison threshold. This does not rule out edits. No trained forensic model was run."
            status = "reference_comparison_only"
        else:
            acc_text = f"Page {page_number}: Visual inspection completed by {provenance.get('model_name') or 'model'}. No anomalous regions detected."
            status = "clear"
    else:
        counts_model = sum(1 for r in all_regions if r.get("type") == "model_anomaly")
        counts_ref = sum(1 for r in all_regions if r.get("type") == "reference_difference")
        parts = [f"Page {page_number}: Visual inspection identified {len(all_regions)} region(s) of interest."]
        if counts_model:
            parts.append(f"{counts_model} region(s) exhibit anomalies detected by {provenance.get('model_name') or 'trained forensic model'}.")
        if counts_ref:
            parts.append(f"{counts_ref} region(s) exhibit visual differences compared against the authorized institutional template.")
        for idx, r in enumerate(all_regions, 1):
            box = r["box"]
            parts.append(f"Region {idx} ({r['type']}): at horizontal {box[0]*100:.0f}%, vertical {box[1]*100:.0f}%, span {box[2]*100:.0f}%x{box[3]*100:.0f}%. {r['explanation']}")
        acc_text = " ".join(parts)
        if reference_regions:
            status = "reference_comparison_only"
        else:
            status = "suspicious_regions_detected"

    return {
        "status": status,
        "page": page_number,
        "analyzed_page": page_number,
        "regions": all_regions,
        "suspicious_regions": all_regions,
        "model_provenance": provenance.get("technique") or "Error Level Analysis",
        "anomaly_score": anomaly_score,
        "summary": {
            "total_regions": len(all_regions),
            "model_anomalies": sum(1 for r in all_regions if r.get("type") == "model_anomaly"),
            "reference_differences": sum(1 for r in all_regions if r.get("type") == "reference_difference"),
            "global_ela_mean": round(ela_mean, 2),
            "reference_diff_mean": round(ref_diff_mean, 2) if ref_diff_mean is not None else None,
            "anomaly_score": anomaly_score,
        },
        "accessible_description": acc_text,
        "provenance": provenance,
        "duration_ms": elapsed_ms,
    }


def store_reference_asset(reference: str, institution_id: int, data: bytes, asset_type: str = "preview_png") -> bool:
    """Store an authorized reference asset for alignment with explicit consent."""
    if not reference or not data:
        return False
    from .storage import connect
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_file = assets_dir / f"{reference}.png"
    try:
        asset_file.write_bytes(data)
    except Exception:
        return False

    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reference_assets 
               (reference, issuer_id, preview_path, consent_to_retain, created_at) 
               VALUES (?, ?, ?, 1, ?)""",
            (reference, institution_id, f"assets/{reference}.png", now)
        )
    return True


def get_reference_asset(reference: str) -> Optional[bytes]:
    """Retrieve the authorized reference asset bytes for a given certificate reference."""
    if not reference:
        return None
    from .storage import connect
    try:
        with connect() as conn:
            row = conn.execute("SELECT preview_path FROM reference_assets WHERE reference=?", (reference,)).fetchone()
            if not row or not row["preview_path"]:
                return None
            p = Path(row["preview_path"])
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                return p.read_bytes()
    except Exception:
        pass
    return None


def delete_reference_asset(reference: str, user_id: int, user_role: str) -> bool:
    """Safely delete retained reference assets with role access checks."""
    from .storage import connect, canonical_role, ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN
    from fastapi import HTTPException
    canon = canonical_role(user_role)
    if canon not in (ROLE_INSTITUTION_ADMIN, ROLE_SYSTEM_ADMIN):
        raise HTTPException(403, "Not authorized to delete reference assets.")
    with connect() as conn:
        row = conn.execute("SELECT * FROM reference_assets WHERE reference=?", (reference,)).fetchone()
        if not row:
            return False
        if canon == ROLE_INSTITUTION_ADMIN and row["issuer_id"] != user_id:
            raise HTTPException(403, "Institutions can only delete their own reference preview assets.")
        if row["preview_path"]:
            p = Path(row["preview_path"])
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                p.unlink(missing_ok=True)
        conn.execute("DELETE FROM reference_assets WHERE reference=?", (reference,))
    return True
