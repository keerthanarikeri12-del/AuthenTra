# AuthenTra

**AI-Assisted Digital Certificate Authenticity Verification Using Blockchain**

AuthenTra provides a verifiable, privacy-conscious integration of decentralized issuer governance, byte-level file integrity, off-chain cryptographic metadata commitments, multi-scale visual tampering localization, rescan transformation advisory synthesis, and calibrated human-review routing.

---

## 1. Non-Negotiable Trust Rules & System Invariants

1. **Untouched File Integrity**: SHA-256 digests are calculated exclusively over the untouched, raw uploaded binary bytes as received from the network. Preprocessed, normalized, or rasterized images are used strictly as secondary working copies for visual analysis.
2. **Cryptographic Authority vs. Advisory AI**: Verification decisions (`VERIFIED`, `REVOKED`, `ISSUER_NOT_AUTHORIZED`, `POSSIBLE_TAMPERING_OR_FILE_MISMATCH`, `NOT_REGISTERED_OR_INCONCLUSIVE`) are strictly governed by immutable blockchain records and exact cryptographic hashes. AI similarity metrics, matching extracted fields, or low anomaly scores **must never** promote a mismatched, unregistered, revoked, or unauthorized certificate to "Verified".
3. **Transparent Uncertainty**: When document quality is degraded, OCR text is unreadable, or reference metadata is absent, the system explicitly reports uncertainty (`INSUFFICIENT_EVIDENCE`, `BETTER_QUALITY_REQUIRED`, or `UNAVAILABLE`) rather than guessing or asserting confirmed alterations.
4. **Off-Chain Personal Data Protection**: Recipient names, qualifications, grades, and full document files are strictly kept off-chain. Only pseudonymous identifiers, file digests, and cryptographic commitments interact with smart contracts.
5. **No Synthetic Validation Fallacy**: Documented benchmarks explicitly distinguish rule-based normalization, ELA forensic signals, and heuristic baselines from learned models, avoiding exaggerated claims of fraud detection accuracy.

---

## 2. System Architecture & Intelligence Capabilities

### 2.1 Capability 1: Field-Level Change Detection (`backend/fields.py`)
- **Schema Versioning**: Versioned under `FIELD_SCHEMA_VERSION = "2026.1"`.
- **Cryptographic Commitment**: Confirmed metadata is bound via a deterministic canonical JSON payload and SHA-256 commitment:
  $$\text{Commitment} = \text{SHA-256}(\text{CanonicalJSON}(\text{reference}, \text{file\_hash}, \text{confirmed\_fields}))$$
  Stored in the `registrations` table alongside optional issuer signature proofs.
- **Conservative Deterministic Normalization**:
  - `recipient_name`: Unicode NFKC normalization, whitespace compression, canonical honorific stripping (e.g., "Mr.", "Dr."). Non-fuzzy matching prevents erroneously equating distinct individuals.
  - `course`: Case-insensitive canonical alias mapping (e.g., "B.Sc" vs "Bachelor of Science").
  - `issue_date`: Unambiguous conversion to ISO 8601 (`YYYY-MM-DD`) supporting numerical and textual formats (e.g., "12 June 2025" $\rightarrow$ "2025-06-12").
  - `grade`: Standardized honors, GPA, and classification formatting.
- **Field Status Taxonomy**: `matched`, `changed`, `missing`, `ambiguous`, `unreadable`, `unregistered_field`.
- **Backward Compatibility**: Records without confirmed reference metadata return an honest `UNAVAILABLE` status without interrupting verification.

### 2.2 Capability 2: Visual Tampering Localization (`backend/visual_tampering.py`)
- **Resource Bounds**: Enforces limits: max 5 pages, 20 megapixels, 15 seconds CPU execution timeout, and bounded memory allocation.
- **Forensic Pipeline**:
  1. Separate raster working copy generation using `pypdfium2` (for PDFs) or `Pillow` (for raster images).
  2. Multi-scale Error Level Analysis (ELA) at quality $Q=90$ to detect localized compression-rate discontinuities indicative of cut-and-paste or digital splicing.
  3. Structural gradient and patch anomaly detection with connected-component bounding box merging.
  4. Template alignment difference mapping when an authorized reference image is available.
- **Output Contract**: Normalized bounding boxes `[x, y, w, h]` (0.0 to 1.0), anomaly scores, model provenance declarations, and accessible textual descriptions for screen readers.
- **Privacy & Asset Lifecycle**: Previews and reference assets stored in `reference_assets` table with access control and instant deletion support via `DELETE /api/storage/previews/{reference}`.

### 2.3 Capability 3: Rescan & Compression Transformation Advisory (`backend/transformations.py`)
- **Evidence Synthesis**: Combines objective image quality metrics, skew estimation, OCR reliability, and field comparison results to interpret hash mismatches caused by non-malicious environmental transformations:
  - **Laplacian Sharpness**: High-frequency edge energy ($\nabla^2$).
  - **Noise Sigma**: Standard deviation of high-frequency residual after median filtering.
  - **8x8 Blockiness**: Inter-block vs. intra-block boundary discontinuity along JPEG grid seams.
  - **Estimated Skew**: Hough-like horizontal projection variance across angular search space.
- **Advisory Outcomes**:
  - `MATCH_CONFIRMED`: Exact byte-level match on registered file.
  - `FIELDS_AGREE_RESAVE_OR_REEXPORT`: Authenticated fields match confirmed metadata; discrepancies consistent with rescan, photo, recompression, or PDF re-export.
  - `CONTENT_DIFFERENCES_DETECTED`: Critical fields (name, grade, course, date) differ from authenticated reference.
  - `MIXED_EVIDENCE_REVIEW_REQUIRED`: Text matches but localized visual anomalies or structural seams are detected.
  - `INSUFFICIENT_EVIDENCE`: Upload image is too degraded, blurry, or noisy to assess.

### 2.4 Capability 4: Confidence-Based Review Routing & Audit Trail (`backend/routing.py`)
- **Uncertainty & Policy Routing**: Combines OCR confidence, image sharpness, layout familiarity, and field match integrity into a versioned routing policy (`ROUTING_POLICY_VERSION = "2026.1"`).
- **Routing Outcomes**:
  - `COMPLETED_NO_REVIEW`: High OCR reliability, familiar template, all fields match.
  - `INSTITUTION_REVIEW_REQUIRED`: Discrepancy in recipient name, grade, or course; routed to the issuing institution.
  - `ADMIN_REVIEW_REQUIRED`: Unfamiliar foreign template layout, unapproved issuer, or platform-level escalation.
  - `BETTER_QUALITY_REQUIRED`: Blurry or noisy upload with low OCR reliability; user must provide a clearer copy.
  - `ANALYSIS_UNAVAILABLE`: Corrupted or unparseable input.
- **Immutable Review Audit Trail**: Persisted in `review_decisions` table:
  - Columns: `id`, `certificate_reference`, `actor_user_id`, `actor_role`, `decision` (`APPROVED`, `REJECTED`, `FLAGGED_FOR_AUDIT`), `reason`, `evidence_hash`, `model_version`, `recorded_at`.
  - Server-side permission enforcement: `INSTITUTION_ADMIN` is strictly restricted to credentials issued by their own institution; `SYSTEM_ADMIN` handles platform-wide escalations.

---

## 3. Database Schema Migrations & Storage Architecture

All database schema updates are non-destructive and backward-compatible:

```sql
-- Extended registrations table for authenticated reference binding
ALTER TABLE registrations ADD COLUMN metadata_schema_version TEXT DEFAULT '2026.1';
ALTER TABLE registrations ADD COLUMN confirmed_metadata TEXT;
ALTER TABLE registrations ADD COLUMN metadata_commitment TEXT;
ALTER TABLE registrations ADD COLUMN issuer_signature TEXT;
ALTER TABLE registrations ADD COLUMN committed_at TEXT;

-- Extended verifications table for independent intelligence outcomes
ALTER TABLE verifications ADD COLUMN field_analysis TEXT;
ALTER TABLE verifications ADD COLUMN visual_tampering TEXT;
ALTER TABLE verifications ADD COLUMN transformation_analysis TEXT;
ALTER TABLE verifications ADD COLUMN review_routing TEXT;

-- Extended upload_items table for background worker persistence
ALTER TABLE upload_items ADD COLUMN field_analysis TEXT;
ALTER TABLE upload_items ADD COLUMN visual_tampering TEXT;
ALTER TABLE upload_items ADD COLUMN transformation_analysis TEXT;
ALTER TABLE upload_items ADD COLUMN review_routing TEXT;

-- Immutable audit log for human reviewer decisions
CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    certificate_reference TEXT NOT NULL,
    actor_user_id INTEGER NOT NULL,
    actor_role TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    evidence_hash TEXT,
    model_version TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(actor_user_id) REFERENCES users(id)
);

-- Reference assets for visual template alignment (with consent & TTL)
CREATE TABLE IF NOT EXISTS reference_assets (
    reference TEXT PRIMARY KEY,
    institution_id INTEGER NOT NULL,
    asset_type TEXT NOT NULL,
    data BLOB NOT NULL,
    consent_recorded INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(institution_id) REFERENCES users(id)
);
```

---

## 4. API Specification & Endpoints

| Method | Endpoint | Authorization | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/verify` | Authenticated (`USER`+) | Primary verification endpoint returning authoritative blockchain result and all 4 advisory analyses. |
| `POST` | `/api/certificates` | `INSTITUTION_ADMIN` | Register certificates with metadata commitment, off-chain storage, and smart contract issuance. |
| `POST` | `/api/certificates/confirm-metadata` | `INSTITUTION_ADMIN` | Preview and confirm extracted fields, compute canonical commitment before on-chain commitment. |
| `POST` | `/api/reviews/decision` | `INSTITUTION_ADMIN`, `SYSTEM_ADMIN` | Record human review decision in immutable audit trail. Enforces institution ownership boundaries. |
| `GET` | `/api/reviews/history/{reference}` | Authenticated | Fetch immutable audit trail of review decisions for a certificate reference. |
| `DELETE` | `/api/storage/previews/{reference}` | `INSTITUTION_ADMIN`, `SYSTEM_ADMIN` | Delete retained reference preview assets adhering to privacy and data deletion policies. |
| `POST` | `/api/uploads` | Authenticated | Asynchronous batch upload endpoint supporting multi-file processing and independent feature persistence. |
| `GET` | `/api/uploads/{id}` | Authenticated | Poll batch processing state, item-level progress, and snapshot results. |

---

## 5. Security & Isolation Architecture

- **Sandbox Execution**: Python backend operates under Windows sandbox isolation with bounded filesystem and resource restrictions.
- **AnyIO Blocking Portal & Loopback Networking**: Tests requiring loopback communication run with elevated privileges when necessary to prevent local socketpair deadlocks.
- **Cryptographic Independence**: Smart contract execution on the local EVM node validates ownership and issuer permissions independently of backend application state.
