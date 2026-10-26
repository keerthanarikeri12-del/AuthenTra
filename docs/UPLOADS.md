# Certificate upload workflows

## Scope and interface

The existing React/FastAPI/SQLite application and Ethereum registry remain in use. `CertificateUpload.jsx` is shared by the verifier and institution pages; it uses the existing panels, badges, buttons and verification result component. It supports keyboard-operable Browse Files, multiple selection, drag and drop, removal, per-file references, inline validation, PDF/image thumbnails, transfer progress, asynchronous processing progress, interactive human review cards, and individual result cards with block explorer links. Layouts stack on mobile and do not require drag-and-drop access.

Users may upload **1–5 certificates per verification batch**. This is enforced on the server for every account using verification mode. Institution registration requires an authenticated administrator whose institution is active and approved (`role == 'institution'` and `approval_status == 'APPROVED'`) and verified on-chain via `approvedIssuers`; ordinary users and pending/suspended/revoked institutions cannot register certificates. Institution identity is derived strictly from verified authentication context, never from untrusted request bodies.

Uploading initiates asynchronous processing through an explicit per-certificate lifecycle. For institution registration, **no blockchain registration is simulated and no mock transaction hashes are returned**. A certificate is marked as registered in the UI *only after* a real blockchain transaction receipt is confirmed and an independent on-chain read-back verifies the recorded hash and issuer.

ZIP archives and CSV manifests are intentionally **not implemented**. Only individual PDF, PNG, JPG and JPEG files are accepted. Archives are rejected without extraction, including renamed archives. There is no archive extraction or path interpretation in the upload workflow; submitted filenames are display/report metadata only.

## Registration status lifecycle

Each certificate in a registration batch transitions through explicit states:

| Status | Description |
| --- | --- |
| `QUEUED` | File validated for size, MIME type and format, and safely enqueued in durable storage. |
| `VALIDATING` | Magic bytes, page limits, image dimensions, and byte integrity are checked. |
| `OCR_PROCESSING` | Text extraction directly from PDF objects, or local Tesseract OCR for scanned PDFs and raster images. Fields (reference, recipient, institution, course, issue date) and OCR confidence are analyzed. |
| `AWAITING_REVIEW` | Required when OCR confidence is low (<50%) or critical metadata cannot be reliably extracted. Displays a human review card in the UI allowing the administrator to confirm or correct metadata before on-chain submission. |
| `PENDING_BLOCKCHAIN` | Real transaction has been broadcast to the EVM blockchain node; waiting for mined block receipt. |
| `REGISTERED_ON_BLOCKCHAIN` | **Terminal success state.** Set *only* after the transaction receipt confirms status `1` AND an independent on-chain read (`lookup(reference)`) verifies that the on-chain hash matches the original file hash and the issuer matches the authorized wallet. |
| `REGISTRATION_FAILED` | **Terminal failure state.** Set if transaction reverts, duplicate reference is detected with conflicting hash, or review is rejected. |
| `REGISTRATION_STATUS_UNCERTAIN` | **Uncertain state.** Occurs when transaction broadcast timed out or the blockchain confirmation was interrupted before a definitive receipt could be verified. Displays transaction hash and a Retry button that first checks on-chain state before resubmitting. |

## Canonical original-byte hashing

- **Exact raw bytes:** SHA-256 is computed directly on the original uploaded file bytes before OCR parsing, PDF rasterization, image format conversion, compression, or any preprocessing.
- **Canonical format:** Preserved as a lowercase 64-character hexadecimal digest.
- **Rescanning / Re-exporting caveat:** In digital document verification, SHA-256 is sensitive to the underlying file byte stream. Re-exporting a document from Word/LaTeX, re-saving a PDF with different metadata, or scanning a physical paper copy introduces different binary compression, font streams, or image rasterization. This alters the cryptographic hash even when visual contents appear identical to a human observer.
- **Idempotency:** Re-registering an identical document with the same reference by the same approved institution is handled idempotently without submitting redundant blockchain transactions or incurring duplicate gas fees. Attempting to register an existing reference with different file bytes is rejected with HTTP 409 Conflict.

## Central policy

Set these in the backend process environment and restart the service. The UI retrieves the effective limits from the authenticated limits endpoint.

| Setting | Default | Allowed range / behavior |
| --- | --- | --- |
| User verification files | 5 | Fixed, not client-controlled |
| Per-file size | 10 MiB | Existing `backend.documents.MAX_BYTES` |
| PDF pages | 1–5 | Unencrypted readable PDFs |
| Image pixels | 20 million | Fully decoded by Pillow on the server |
| `AUTHENTRA_BULK_FILES` | 100 | 1–1,000 files per registration batch |
| `AUTHENTRA_BULK_BYTES` | 104,857,600 | 10 MiB–1 GiB total registration bytes |
| `AUTHENTRA_UPLOAD_JOBS` | 4 | 1–20 unfinished jobs globally |
| Concurrent incoming uploads | 2 | Excess requests return 429 |

A byte-counting receiver authenticates before multipart parsing and bounds the entire request, even when Content-Length is missing or incorrect. A 1 MiB allowance covers multipart headers and reference fields. Uploaded bodies are spooled to temporary disk, then parsed; file contents are processed one at a time during validation. Set reverse-proxy body/time limits consistently with this policy. Size limits in the UI use binary units displayed as MB/KB for consistency with the existing app.

Browser validation checks extension, MIME type, bytes, nonempty size, total size, count, references and duplicate SHA-256 hashes. PDF.js reads all PDF pages and renders a first-page thumbnail; image decoding produces a thumbnail. The backend independently checks MIME/extension/signature agreement, parsing, image decoding, encryption, page/pixel limits, sizes and counts. Client checks are convenience checks, never authorization or authenticity evidence.

## API

All endpoints require the existing HttpOnly session cookie. Missing/expired sessions return 401, unauthorized roles or inactive institutions return 403. Reports and jobs are scoped to the submitting account; unrelated accounts receive 404.

- `GET /api/uploads/limits?mode=verify|register` — effective count and byte limits. Register mode also checks issuer approval.
- `POST /api/uploads` — multipart fields `files` (repeated), `references` (JSON array of strings in file order), and `mode` (`verify` or `register`). Blank verification references allow extraction; registration references are mandatory. Returns **202** with `id`, `mode`, `state`, `summary`, and `items`.
- `GET /api/uploads/{id}` — poll while `state` is `processing`; stop on `completed`. The UI polls about every 1.5 seconds and retries status-read errors without resubmitting the batch.
- `GET /api/uploads?mode=verify|register` — the account's latest ten batches. Active jobs resume in the UI after navigation or refresh.
- `GET /api/uploads/{id}/report` — authenticated downloadable CSV snapshot, including unfinished outcomes if still processing. Formula-like cells are escaped for spreadsheet safety.
- `POST /api/uploads/{job}/items/{item_id}/review` — allows an authenticated institution administrator to approve or reject items in `AWAITING_REVIEW`, providing verified reference and metadata fields.
- `POST /api/uploads/{job}/items/{item_id}/retry` — allows an authenticated institution administrator to re-check the blockchain for mined receipts or re-enqueue uncertain/failed upload items without re-uploading the file.
- `POST /api/certificates/bulk` — existing registration route now uses the same asynchronous queue and **202 response**, with `files` and `references`. Consumers must poll the returned job ID. `scripts/evaluate_bulk.py` has been updated.
- Legacy `POST /api/verify` and `POST /api/certificates` remain single-file operations, using the same content validation.

## Data privacy and blockchain boundary

- **On-chain:** Only minimal cryptographic identifiers are written to the smart contract: `referenceHash` (Keccak-256 of canonical reference), `fileHash` (bytes32 of original file SHA-256), `issuer` (address), `registeredAt` (uint64 timestamp), and revocation flag. Full files, recipient names, course titles, grades, and personal identifiers are **never written on-chain**.
- **Off-chain persistence:** Extracted metadata, recipient names, OCR confidence scores, and transaction receipts are stored securely off-chain in the SQLite database (`registrations` and `upload_items` tables).
- **Audit logging:** Administrative actions record timestamps, actor IDs, certificate references, transaction hashes, and error codes in the `audit` table without logging sensitive certificate contents or personal information.
- **RPC Availability:** If the blockchain network or RPC node is unreachable, the system reports this limitation honestly (HTTP 503 Service Unavailable) rather than faking success or returning mock transactions.
- **Explorer links:** The frontend renders block explorer hyperlinks (e.g. Etherscan/Sepolia) only when a valid explorer template is configured for the connected network; for local development chains (chain ID 1337), explorer links are omitted unless explicitly configured.

Example response shape (illustrative, not a success response generated by the UI):

```json
{
  "id": "opaque-job-id",
  "mode": "register",
  "state": "processing",
  "summary": {"total": 2, "valid": 1, "rejected": 1, "pending": 1, "successful": 0, "failed": 0},
  "items": [
    {"id": 1, "filename": "first.pdf", "reference": "AT-001", "state": "pending", "result": null},
    {"id": 2, "filename": "bad.pdf", "reference": "AT-002", "state": "rejected", "result": {"error": "The PDF could not be read."}}
  ]
}
```

File states are `pending`, `processing`, `rejected`, `succeeded`, and `failed`. `valid` counts files accepted by validation, including pending and failed processing attempts. `pending` includes the currently processing file. `successful` means completed checks in verification mode and confirmed registrations in registration mode; it is never a count of Verified certificates. Overall completion means every file has a terminal outcome, not that every file succeeded.

Count/reference-array errors, total-size violations and a full queue reject the request before any job is inserted. Invalid individual files, duplicate file bytes and repeated registration references become rejected items while valid siblings proceed. Identical bytes registered previously by the same institution are rejected; already-used certificate IDs cannot be reused. Registration's duplicate checks and transaction submission are serialized across queued and legacy single-file operations.

## Worker, persistence and failures

Run **one server process per SQLite database** (`uvicorn backend.main:app --workers 1`). An operating-system file lock prevents multiple upload workers from sharing a database. The queue is persisted in `upload_jobs` and `upload_items`; migration is additive. The serial worker performs document analysis and waits for blockchain receipts off the web event loop. Existing OCR and blockchain timeouts apply. This is a bounded prototype worker, not a distributed processing service; untrusted parsing still runs in-process and should be isolated before a public deployment.

Each file's outcome is committed independently. Failed files do not roll back successful siblings. On graceful shutdown the worker finishes its current file and leaves queued files for restart. After an abrupt stop, queued files resume, but a file interrupted during processing becomes Failed with an instruction to inspect the registry before retrying. It is never automatically submitted again: a blockchain transaction may have committed before the server could save its receipt. A chain timeout or a chain/database inconsistency also requires checking the authoritative registry before retrying. Cross-system exactly-once delivery is not claimed.

Incoming request and OCR temporary files are closed on success/failure. Valid queued bytes temporarily persist in SQLite; terminal items clear the byte column, with SQLite secure-delete enabled. Raw uploads do not go on-chain or appear in a download endpoint. Batch reports **do retain filenames, reference, extracted fields, checks, hashes and receipts**, privately scoped to the owner, so reports can be restored after refresh. They have no automatic expiry in this version. Protect database files and backups and define an appropriate retention policy before deployment; clearing active database bytes does not erase earlier backups. Legacy verification history retains its existing minimal schema.

## Validation and reproducible tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=.local/upload-tests
pnpm test:uploads
pnpm build
```

API tests cover permissions, the 5-file boundary, configurable bulk limits, fake/corrupt/empty/oversized files, MIME mismatches, rejected archives, total-size rejection, duplicates, partial failures, queue saturation, job/report ownership, CSV formula escaping, restart recovery, receipt requirements and chunked request-size limits. Existing authentication and verification-decision regressions remain in the suite.

Browser tests exercise **real local services and blockchain outcomes**, including valid and corrupt PDFs, previews/removal, over-count rejection, separate verification cards, a confirmed registration beside a duplicate-ID failure, report download, restored batch history, keyboard focus and a 390-pixel mobile layout.

```powershell
.\Start-AuthenTra.ps1
pnpm test:browser
```

The browser suite requires Microsoft Edge and the project's Python virtual environment on Windows; set `AUTHENTRA_BROWSER_CHANNEL=chrome` or configure Playwright for another installed channel. `AUTHENTRA_TEST_URL` defaults to `http://127.0.0.1:8000`. Run against the local demonstration only: tests create a new clearly marked demonstration certificate registration and verification history. Generated documents and screenshots are under ignored `.local/`. Never run these tests against a production registry.

PDF previews use Mozilla's [PDF.js display API](https://mozilla.github.io/pdf.js/examples/) bundled locally; certificate contents are not sent to a third-party preview service.
