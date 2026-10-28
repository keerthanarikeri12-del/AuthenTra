# AuthenTra Dataset & Evaluation Specification

Document Version: 2026.1  
Status: Active Specification  

This document defines the dataset structure, ground truth schema, augmentation pipeline, data leakage safeguards, and split partitions required to evaluate AuthenTra's certificate analysis capabilities:
1. Field-level change detection against issuer-confirmed metadata.
2. Visual tampering localization (PDF and raster images).
3. Rescan, recompression, and re-export transformation interpretation.
4. Confidence-based review routing and layout familiarity.

---

## 1. Trust Principles & Non-Negotiable Dataset Invariants

1. **Untouched Byte Integrity**: The primary SHA-256 hash check is always computed over the untouched raw file bytes as received from the upload stream. Rendered or preprocessed copies are used strictly as secondary working representations for visual analysis.
2. **AI Is Strictly Advisory**: Model predictions, visual anomaly heatmaps, and similarity metrics are categorized as supporting evidence or suspected changes—never as definitive proof of deliberate fraud, and never as authority to promote a certificate to "Verified".
3. **No Synthetic Validation Fallacy**: The existing 480-example synthetic text dataset does not validate visual localization or transformation classification. Claims of operational capability must explicitly separate trained/calibrated components from rule-based and limited-state baselines.
4. **Zero Live PII**: All recipient names, student identifiers, and grades in evaluation datasets must be synthetically generated or provided under documented explicit consent.

---

## 2. Dataset Schema & Structure

The canonical dataset directory layout is organized into template groups to guarantee clean split boundaries without data leakage:

```
dataset/
├── manifest.json                  # Top-level manifest and license declarations
├── templates/                     # Institution template layout definitions
│   ├── TMPL-001/                  # Standard university diploma (landscape)
│   ├── TMPL-002/                  # Technical institute certificate (portrait)
│   ├── TMPL-003/                  # Professional accreditation certificate
│   └── TMPL-UNSEEN/               # Unseen layouts reserved exclusively for test split
├── groups/                        # Template groups (one original + all variants per group)
│   ├── GRP-0001/
│   │   ├── metadata.json          # Issuer-confirmed canonical metadata & commitment
│   │   ├── original.pdf           # Untouched registered digital certificate
│   │   ├── variants/
│   │   │   ├── benign_rescan_300dpi.png
│   │   │   ├── benign_photo_mobile.jpg
│   │   │   ├── benign_recompress_q40.jpg
│   │   │   ├── benign_pdf_reexport.pdf
│   │   │   ├── altered_recipient_name.pdf
│   │   │   ├── altered_grade.png
│   │   │   ├── altered_course_rescan.jpg
│   │   │   └── low_quality_blur.jpg
│   │   └── annotations/
│   │       ├── regions.json       # Bounding box & mask annotations for alterations
│   │       └── layout_zones.json  # Expected bounding boxes for canonical fields
│   └── GRP-0002/ ...
```

### 2.1 Metadata Schema (`metadata.json`)

Each certificate record contains an issuer-confirmed reference record matching schema version `2026.1`:

```json
{
  "schema_version": "2026.1",
  "certificate_reference": "AT-2026-0001",
  "template_id": "TMPL-001",
  "issuer_institution_id": "INST-001",
  "issuer_wallet_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
  "confirmed_metadata": {
    "reference": "AT-2026-0001",
    "recipient_name": "Alex Morgan",
    "institution": "Apex Institute of Technology",
    "course": "Blockchain Architecture",
    "issue_date": "2025-06-12",
    "grade": "Distinction"
  },
  "metadata_commitment": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
  "issuer_signature": "0x4b7c8...confirmed_proof",
  "committed_at": "2026-01-15T10:00:00Z"
}
```

### 2.2 Region Annotation Schema (`regions.json`)

Region coordinates are normalized floating-point values `[x, y, w, h]` relative to the page width and height:

```json
{
  "certificate_reference": "AT-2026-0001",
  "page_count": 1,
  "annotations": [
    {
      "variant_filename": "altered_recipient_name.pdf",
      "page": 1,
      "field_affected": "recipient_name",
      "original_text": "Alex Morgan",
      "tampered_text": "Jordan Vance",
      "bbox_normalized": [0.320, 0.450, 0.360, 0.055],
      "alteration_type": "text_substitution",
      "splicing_detected": true
    },
    {
      "variant_filename": "altered_grade.png",
      "page": 1,
      "field_affected": "grade",
      "original_text": "Distinction",
      "tampered_text": "First Class Honours",
      "bbox_normalized": [0.410, 0.620, 0.220, 0.040],
      "alteration_type": "patch_overlay",
      "splicing_detected": true
    }
  ]
}
```

---

## 3. Augmentation & Variant Generation

To reflect realistic certificate verification conditions, evaluation variants must simulate both benign environmental transformations and adversarial attacks:

| Variant Category | Transformation Pipeline | Expected Outcome |
| :--- | :--- | :--- |
| **Pristine Original** | Untouched digital file as generated by the issuing authority. | `VERIFIED` (Exact SHA-256 match). |
| **Benign Rescan** | Printed & flatbed scanned at 300 DPI, rotation $\pm 0.5^\circ \text{--} 2^\circ$, sensor noise ($\sigma = 2 \text{--} 5$), mild descreening blur. | Hash mismatch; advisory: `FIELDS_AGREE_RESAVE_OR_REEXPORT`. |
| **Benign Mobile Photo** | Perspective warp ($\le 5^\circ$), non-uniform illumination gradient, JPEG compression artifacts ($Q = 65 \text{--} 80$). | Hash mismatch; advisory: `FIELDS_AGREE_RESAVE_OR_REEXPORT` or `MIXED_EVIDENCE_REVIEW_REQUIRED`. |
| **Benign Re-export** | PDF print-to-PDF or rasterized re-export altering internal xref table or font subsetting without modifying glyphs. | Hash mismatch; advisory: `FIELDS_AGREE_RESAVE_OR_REEXPORT`. |
| **Benign Compression** | Repeated JPEG compression cycles ($Q = 25 \text{--} 50$) inducing blockiness without textual alteration. | Hash mismatch; advisory: `FIELDS_AGREE_RESAVE_OR_REEXPORT`. |
| **Malicious Name Edit** | Digital font-matched substitution of recipient name. | Hash mismatch; advisory: `CONTENT_DIFFERENCES_DETECTED`; routing: `INSTITUTION_REVIEW_REQUIRED`. |
| **Malicious Grade Edit** | Splicing of higher honor/grade string onto issued certificate. | Hash mismatch; advisory: `CONTENT_DIFFERENCES_DETECTED`; localization bbox detected. |
| **Malicious Rescanned Tamper** | Spliced document subsequently printed, scanned, and compressed to mask digital seams. | Hash mismatch; advisory: `CONTENT_DIFFERENCES_DETECTED`; field mismatch flagged. |
| **Severe Degradation** | Heavy motion blur, extreme contrast loss, or dark capture. | Hash mismatch; advisory: `INSUFFICIENT_EVIDENCE`; routing: `BETTER_QUALITY_REQUIRED`. |
| **Unseen Layout** | Non-standard certificate layout from an unpartnered foreign institution. | Hash mismatch; layout familiarity $< 0.4$; routing: `ADMIN_REVIEW_REQUIRED`. |

---

## 4. Split Strategy & Data Leakage Prevention

To prevent synthetic leakage and overoptimistic performance reports:
1. **Template Group Splitting**: All variants derived from a base certificate $G_i$ reside exclusively within one split. A model or feature evaluated on test variants has never seen the pristine template or clean text of that group during training or tuning.
2. **Three-Way Partition**:
   - **Training Set (60%)**: Used for feature learning, gradient priors, and transformation metric baselines.
   - **Calibration & Tuning Set (20%)**: Strictly isolated. Used solely for probability calibration (Platt scaling / isotonic regression) and routing threshold optimization.
   - **Test Set (20%)**: Held-out partition containing both standard templates and **unseen institution layouts** (e.g., `TMPL-UNSEEN`). Evaluated only for final reporting.

---

## 5. Licensing, Ethics, and Storage Policy

- **Licensing**: All benchmark templates and synthetic certificate assets are distributed under the Creative Commons Attribution 4.0 International (CC BY 4.0) or CC0 public domain dedication.
- **Privacy Policy**: Reference images and working preview copies stored by institutions are protected with strict access control:
  - Accessible only to authorized institution administrators or platform administrators.
  - No uploads are permanently retained without institutional consent.
  - Instant removal is supported via the authenticated endpoint:
    `DELETE /api/storage/previews/{reference}`

