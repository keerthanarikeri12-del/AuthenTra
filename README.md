# AuthenTra

**AI assisted Digital Certificate Authenticity Verification using Blockchain**

A working local research prototype with React, FastAPI, SHA-256, Tesseract OCR, an experimental Random Forest model and a Solidity registry running on a persistent local Ethereum-compatible blockchain.

## Open the application

The application is served at **http://127.0.0.1:8000** while its local services are running.

On this Windows machine, start or restart it from the project directory:

```powershell
.\Start-AuthenTra.ps1
```

The script starts the local blockchain and backend in hidden background processes, prepares missing demonstration data, and prints the application URL. It does not publish a website or use real cryptocurrency. It requires the dependencies described below.

Choose **User Portal**, **Institution Portal**, or the dedicated **Admin Portal** (`#admin`), then enter your credentials. For local demo login:

| Role (Canonical) | Alias / Legacy | Email | Permissions & Scope |
| --- | --- | --- | --- |
| **`USER`** | `verifier` | `verifier@authentra.demo` | Upload & verify certificates (max 5 per batch); view own private verification history. Strictly cannot register certificates or approve institutions. |
| **`INSTITUTION_ADMIN`** | `institution` | `issuer@authentra.demo` | Accredited institutional login; bulk register certificates on blockchain (up to 100 files); OCR extraction; manage & revoke own issued credentials. Strictly cannot approve institutions or view private user records. |
| **`SYSTEM_ADMIN`** | `owner` | `owner@authentra.demo` | Dedicated admin login portal (`#admin`); approve/suspend/reject/revoke institutions with on-chain `setIssuer` sync; platform-wide certificate oversight, verification logs, and immutable audit trail. **Strictly prohibited from uploading/registering certificates.** |

All development accounts use `AuthenTra-demo-2026!`. These accounts are created only in explicit demonstration mode. Never use them or the deterministic development wallets on a public deployment.

## Three-Role Architecture & Separation of Duties

### ROLE 1: USER
- **Authentication**: Native email/password or Google OAuth / Apple ID integration (`/api/auth/oauth/{provider}/url`). Public sign-up always assigns the `USER` role; self-escalation is blocked.
- **Access & Permissions**:
  - Access to dedicated **User Dashboard**.
  - Upload single certificates or batches strictly capped at a **maximum of 5 files** per batch.
  - View personal, private verification history (`GET /api/history` filtered by authenticated `user_id`).
  - Read-only access to system architecture and evaluation metrics.
  - Forbidden from accessing certificate registration (`POST /api/certificates`), bulk issuance, or institution management (returns HTTP 403).

### ROLE 2: INSTITUTION_ADMIN
- **Authentication**: Sign in using an accredited institutional email address (`.edu`, `.ac.in`, `.edu.in`, `.res.in`, or verified allowlist domain).
- **Registration & Approval Lifecycle**:
  1. Institution submits application via `POST /api/auth/institution-signup`.
  2. Requires 6-digit confirmation code verification (`POST /api/auth/verify-email`).
  3. Placed into `PENDING_APPROVAL` status until vetted and authorized by a `SYSTEM_ADMIN`.
  4. Only approved and active institutions (`approval_status == 'APPROVED'`) with configured on-chain signer wallets can execute institutional operations.
- **Access & Permissions**:
  - Access to dedicated **Institution Dashboard** displaying signer wallet, accredited domain, and issuance metrics.
  - Bulk upload certificates without the 5-file limit (configurable up to 100 files / 100 MB).
  - Register certificates on the blockchain registry (`POST /api/certificates`, `POST /api/certificates/bulk`) after validation and OCR text extraction.
  - View own institution's registration history and outcomes (`GET /api/certificates` scoped to issuing wallet).
  - Revoke own issued credentials (`POST /api/certificates/{reference}/revoke`).
  - Cannot approve own or other institutions (returns HTTP 403).
  - Cannot view private histories belonging to unrelated users or institutions.

### ROLE 3: SYSTEM_ADMIN
- **Authentication**: Separate, clearly labeled **Admin Login** entry point (`#admin`, endpoint `POST /api/auth/admin-login`). Non-admin users are rejected with HTTP 403.
- **Secure Provisioning**: Admin privileges must be assigned through a secure, trusted administrative process. Public registration or user-editable metadata cannot grant administrator rights. Use the dedicated server administrative CLI:
  ```powershell
  # Create a new administrator account
  .\.venv\Scripts\python scripts/create_admin.py --email sysadmin@authentra.gov --password "Strong-Admin-Password-123!" --name "System Administrator"

  # Or promote an existing account
  .\.venv\Scripts\python scripts/create_admin.py --promote user@example.com
  ```
- **Strict Separation of Duties**:
  - **Zero certificate-upload, bulk-upload, certificate-registration, or blockchain-writing interface or permission.**
  - Direct calls to `/api/verify`, `/api/uploads`, `/api/certificates` from a `SYSTEM_ADMIN` account return HTTP 403 Forbidden.
- **Governance & Oversight**:
  - Approve, reject, suspend, or revoke institution access (`POST /api/institutions/{id}/approval`) synchronized directly with the smart contract via `setIssuer(wallet, approved)`.
  - Add approved institutions and institutional domain allowlists.
  - Inspect platform-wide certificate registration records, active/revoked statuses, and on-chain transaction references (`GET /api/admin/certificates`).
  - Inspect global verification logs and latency analytics without exposing certificate payloads (`GET /api/admin/verifications`).
  - Inspect complete system audit history with actor, action, reference, transaction hash, client IP, and metadata (`GET /api/admin/audit`).
  - Cannot impersonate users or institutions.

## Security & Database Policies

- **Backend Enforcement**: All roles and boundaries are strictly enforced in FastAPI route dependencies (`backend/main.py`) via `canonical_role()`, ensuring frontend bypass attempts via direct API calls are blocked with HTTP 403.
- **Database Migrations**:
  - SQLite: `migrations/001_roles_and_audit.sql` updates `users` check constraints and adds IP/details columns to `audit`.
  - Supabase / PostgreSQL: `migrations/002_supabase_rls_policies.sql` defines Row Level Security (RLS) policies for `users`, `registrations`, `verifications`, and `audit` based on JWT claims (`auth.jwt() ->> 'role'`).
- **Audit Logging**: All privileged administrative and issuer operations (approvals, suspensions, revocations, admin logins) are recorded in the `audit` table with admin user ID, action, reference, transaction hash, client IP, and structured details.

## Demonstration Workflows

1. **User Verification Workflow**:
   - Sign in via **User Portal** (`verifier@authentra.demo` or OAuth).
   - Test single certificate verification or select up to 5 files.
   - Inspect SHA-256 match, blockchain status, issuer validity, and separate AI advisory score.
   - Review personal history in **Verification history** and export CSV.
2. **Institution Issuance Workflow**:
   - Sign in via **Institution Portal** (`issuer@authentra.demo`).
   - Open **Institution Dashboard** to review issuer status and signer wallet.
   - Open **Register Credentials** to bulk upload certificates (up to 100 files).
   - Commit certificates to the blockchain and inspect on-chain transaction receipts.
   - Manage credentials in **Issued Registry** and test permanent revocation.
3. **Administrator Governance Workflow**:
   - Navigate to `#admin` or select **Admin Portal**.
   - Sign in as Platform Administrator (`owner@authentra.demo`).
   - Notice the strict governance view with zero upload/registration controls.
   - Manage institutions under **Institution Governance** (approve or suspend on-chain issuers).
   - Inspect all platform certificates under **Certificate Oversight**.
   - Inspect global activity in **Verification Logs** and **System Audit Trail**.

- Authenticated verifier, institution and platform-owner roles; password hashing and HttpOnly JWT cookies.
- Content-based PDF/PNG/JPEG validation on client and server, 10 MB per file and five-page PDF limit. User batches allow five files; institution registration defaults to 100 files / 100 MB with configurable limits.
- ID-first record lookup, original-byte SHA-256, current issuer approval and permanent revocation checks.
- Separate outcomes for Verified, Possible Tampering, Not Registered, Revoked, Not Verified, Inconclusive and Unable to Authenticate.
- Embedded PDF text extraction and offline English Tesseract OCR for images or the first page of scanned PDFs.
- An experimental synthetic-data Random Forest, separate from authoritative decisions.
- Durable asynchronous batches, per-file progress and outcomes, transaction receipts, gas measurement, history, audit logs, JSON reports and CSV batch/history export.
- Responsive web UI; editable architecture SVG; documented research-gap mapping.

## Install on another machine

Use Python 3.12 and a recent Node.js runtime. `pnpm-lock.yaml` records the JavaScript dependency resolution. Python's resolved versions are recorded in `requirements.lock.txt` when present.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
pnpm install
pnpm rebuild esbuild
.venv\Scripts\python.exe scripts\make_architecture.py
```

If using a fresh development environment before a lock file is available, install `requirements.txt` instead. The generated model is version-dependent: train it using the same environment that runs the backend.

Run the blockchain first in one terminal:

```powershell
node scripts/chain.mjs
```

In another terminal:

```powershell
.venv\Scripts\python.exe scripts/train_model.py
.venv\Scripts\python.exe scripts/seed_demo.py
node node_modules/vite/bin/vite.js build
.venv\Scripts\python.exe scripts/server.py
```

For frontend development, run `pnpm dev` in a third terminal. Vite at port 5173 proxies API calls to port 8000. API documentation is at `http://127.0.0.1:8000/docs`.

`scripts/server.py` explicitly enables local demonstration mode and binds to loopback. Production configuration uses `uvicorn backend.main:app` with a strong `JWT_SECRET`, `RPC_URL`, `CONTRACT_ADDRESS`, `OWNER_PRIVATE_KEY` and a JSON `ISSUER_PRIVATE_KEYS` mapping. This configuration path is provided for further development; a public deployment has not been performed or validated. Production cookies require HTTPS.

## Validate

```powershell
.venv\Scripts\python.exe -m pytest tests -q --tb=short
node tests/contract.mjs
.venv\Scripts\python.exe scripts/evaluate.py
.venv\Scripts\python.exe scripts/evaluate_bulk.py
```

The first two commands test backend decisions, authentication and contract permissions. `evaluate.py` requires running services and sample setup. It temporarily disables the demonstration issuer to test that outcome and restores approval in a `finally` block. Run it against the local demonstration only, when no other demo workflow is using that issuer.

The evaluation page reads `.local/model-metrics.json` and `.local/system-metrics.json`. Model data is synthetic; the scan test uses one generated certificate. No real-world fraud-detection, public-network cost or scalability claim is justified by these results.

`evaluate_bulk.py` registers two new demonstration records and submits a third file with a deliberately duplicate ID. It verifies that the batch reports two successes and one explicit failure, and saves measured throughput and gas to the system metrics file.

## Project map

| Location | Purpose |
| --- | --- |
| `src/` | React application and responsive styling |
| `backend/main.py` | API, authentication and workflows |
| `backend/core.py` | Authoritative verification decision logic |
| `backend/documents.py` | File validation, OCR, field extraction and advisory analysis |
| `backend/registry.py` | Blockchain reads and signed transactions |
| `backend/storage.py` | SQLite schema and password handling |
| `contracts/AuthenTraRegistry.sol` | Issuer registry, certificate registration and revocation |
| `scripts/` | Local chain, model training, sample setup, evaluation and architecture generation |
| `tests/` | Backend and isolated smart-contract tests |
| `docs/ARCHITECTURE.md` | Corrected architecture, research-gap mapping and limitations |
| `docs/architecture.svg` | Editable, standalone architecture diagram |
| `.local/` | Ignored runtime database, local chain, development signers and measured results |

Certificate bytes are staged privately in SQLite while queued and cleared after processing. Private batch reports retain per-file outcomes and extracted fields; see [Upload workflows](docs/UPLOADS.md) for storage, restart and deployment details. `.local/chain.json` contains development signing keys and must not be shared. Do not expose the local RPC port or package runtime databases and signing files in a submission.

The local chain uses a JavaScript fallback when its optional native WebSocket module does not match Node.js. This is acceptable for a small demonstration; it can affect performance measurements.

## Separate account experiences

AuthenTra provides two distinct, purpose-built authentication experiences:

### 1. User Login — Google and Apple ID
- **OAuth / OIDC Providers**: Users authenticate via **Continue with Google** or **Continue with Apple** buttons.
- **Security & Privacy**: Client secrets, signing keys, and tokens remain strictly server-side. The frontend only consumes provider initialization URLs and anti-CSRF state parameters generated by the backend.
- **Workflow & Scoping**: On successful OAuth callback and token exchange, the backend provisions or links the user with role erifier. The browser session receives a secure, HttpOnly, SameSite=Strict JWT cookie, and redirects to the **User Dashboard** (/).
- **User Capabilities**: Verifiers can upload 1–5 certificates simultaneously, initiate SHA-256 integrity checks against immutable blockchain records, inspect advisory OCR/AI anomaly context, and review their private verification history.

### 2. Institution Login — Accredited Institutional Email
- **Domain Hierarchy Validation (ackend/domains.py)**:
  - Acceptable institutional email domains must end with authorized educational suffixes: .edu, .edu.in, .ac.in, .res.in, .gov.in, .nic.in, .ac.uk, .edu.au, .edu.sg, .ac.nz, etc., or be explicitly registered in the verified institution_domains allowlist table.
  - Personal freemail providers (@gmail.com, @yahoo.com, @outlook.com, @proton.me, etc.) are rejected with clear error guidance.
  - Substring spoofing is strictly prevented (e.g. akeedu.com and spoof.in.net are rejected).
  - Generic .in domains without educational multi-part suffixes (e.g. company.in) are rejected unless accredited and allowlisted.
- **Official Email Ownership Verification (ackend/email_verification.py)**:
  - Registration generates a cryptographically secure 32-byte verification token and a 6-digit confirmation code with a 1-hour expiration.
  - Institutions must verify email ownership (POST /api/auth/verify-email) before sign-in is permitted.
- **Governance & Approval Boundary**:
  - All new institutions start with status PENDING_APPROVAL.
  - Pending institutions are restricted to the **Pending Approval** screen; all protected issuance and bulk-upload routes are denied (HTTP 403).
  - An authorized platform administrator (owner) reviews verification details under the Governance panel, provisions a funded signer in ISSUER_PRIVATE_KEYS, and executes an on-chain setIssuer(wallet, true) transaction.
  - Only after confirmed on-chain approval and database status update to APPROVED can the institution access the **Certificate Registry** and bulk registration endpoints.
  - Suspended, rejected, or revoked institutions are immediately denied issuance operations.

### 3. Administrator Login
- Platform administrators authenticate to manage institutional allowlists, approve or suspend issuer wallets on the smart contract, and inspect immutable audit logs.

Existing database roles are retained: `verifier` = USER, `institution` = INSTITUTION_ADMIN, `owner` = SYSTEM_ADMIN. Users land on verification, approved institutions on their certificate registry, and owners on institution review. Navigation uses internal React state; no protected URL grants access. All protected APIs independently validate the cookie JWT (signature, issuer, expiry and subject), reload the database account, and deny institutions whose status is not APPROVED. Certificate issuance also requires on-chain issuer approval. Histories, registrations and institution audit queries are scoped by the authenticated account; SQLite is backend-only and has no RLS facility.

The administrator reviews application details under Institutions, provisions a funded server-side signer in `ISSUER_PRIVATE_KEYS`, and approves the wallet. Approve, reject, suspend and revoke authorization all write the corresponding blockchain approval first, then persist the application status and audit event. A failed chain action leaves the database status unchanged. These two stores do not share a transaction: if the chain succeeds but the database write fails, retry the administrative action to reconcile them. Revoking institutional authorization disables issuance; individual certificate revocation remains a separate permanent operation. Existing sessions are denied on their next protected request after suspension.

`backend/storage.py:initialize` performs an idempotent additive migration on startup, preserving existing accounts and certificate history. Legacy accounts receive APPROVED application eligibility for compatibility, while the existing on-chain issuer check remains authoritative for issuance. New institution accounts default to PENDING_APPROVAL. Back up the SQLite database before upgrading. Existing duplicate wallet addresses (case-insensitive) must be resolved before the unique wallet index can be created.

Copy `.env.example` values into your backend process environment (the server does not automatically load dotenv files). Keep signing keys and JWT_SECRET server-side and use HTTPS outside explicit local demo mode. Existing owners remain the only administrator accounts; there is no public administrator registration. No Supabase or second authentication provider is introduced.

### Automated test suites

Testing is strictly partitioned between mocked unit/integration tests and live blockchain tests:

| Test suite | Execution target | What it proves |
| --- | --- | --- |
| 	ests/test_authentication_experiences.py | API & Domain Unit/Integration (30 tests) | Google/Apple OAuth flows, anti-CSRF state tokens, replay prevention, institutional domain validation (.edu, .ac.in, .res.in vs. fake substrings and generic .in), email ownership verification codes, pending approval boundary, and approved institution access. |
| 	ests/browser/authentication_experiences.spec.js | **Playwright E2E Browser** (2 tests) | Complete visual and interactive flows: Google/Apple OAuth buttons, verifier dashboard access, domain rejection alerts, valid institutional application, email verification UI, and approved institution registry access. |
| 	ests/test_live_chain.py | **Live Blockchain** (Ganache on EVM) | Real Web3 signed transactions, mining, receipts, gas tracking, independent on-chain read-back verification, idempotency, unapproved issuer reverts, permanent revocation, and end-to-end API integration. |
| 	ests/contract.mjs | **Live Smart Contract** (Ganache / solc) | Direct EVM execution of AuthenTraRegistry.sol: owner-only approvals, duplicate prevention, issuer isolation, and revocation immutability. |
| 	ests/test_registration_workflow.py | Mocked RPC / Controlled | Institution registration edge cases: reverts, timeouts, offline nodes, OCR confidence thresholds, human review, and duplicate handling without flakiness. |
| 	ests/test_verification_workflow.py | Mocked RPC / Controlled | All 10 user verification scenarios: the 7 result categories, 5-file limits, tampered vs. re-exported byte mismatches, and user history privacy. |
| 	ests/test_api.py | Mocked / API unit | 45 API route tests: authentication, JWT cookies, role boundaries, CSRF/privilege escalation prevention, and rate-limiting. |
| 	ests/test_core.py | Unit | Decision precedence, canonical SHA-256 computation, reference normalization, and file validation. |
| 	ests/uploads.test.mjs | Unit | Frontend file inspection, MIME validation, 5-file limits, and reference checks. |
| 	ests/browser/uploads.spec.js | **Playwright E2E Browser** | Real browser execution: user verification, institution registration with real tx receipts, UI state progression (PENDING -> AWAITING_REVIEW -> FAILED -> REGISTERED), and mobile layout. |

#### Running the tests

`powershell
# 1. Run all Python unit, integration, and live blockchain tests (88 tests)
.venv\Scripts\python.exe -m pytest tests -v --tb=short

# 2. Run smart contract direct EVM tests (9 tests)
node tests/contract.mjs

# 3. Run frontend validation unit tests (4 tests)
node tests/uploads.test.mjs

# 4. Run Playwright end-to-end browser test suite (5 tests, requires background server & chain)
node node_modules/@playwright/test/cli.js test
`

## Role-specific certificate uploads

Both upload experiences reuse the existing panels, status badges, buttons and result details. Users can drop or browse up to five files, inspect thumbnails, edit optional references, remove files and begin verification. Approved institutions can select a configurable bulk batch and enter a required unique reference for each file. Uploading or finishing a check never implies authenticity: the authoritative result still comes from registry, issuer, revocation and file-hash checks.

See [docs/UPLOADS.md](docs/UPLOADS.md) for configuration, API examples, limits, asynchronous compatibility changes, CSV reports, failure handling and test instructions. ZIP files and CSV manifests are not supported; archives are rejected without extraction.


### The 7 Authoritative Result Categories

1. **VERIFIED**: Trusted record exists on-chain, original uploaded file hash matches exactly, issuer is authorized, and certificate is active.
2. **POSSIBLE_TAMPERING_OR_FILE_MISMATCH**: A trusted certificate ID was identified, but the uploaded file hash differs from the registered on-chain hash. Re-exporting or rescanning may also produce a mismatch.
3. **NOT_REGISTERED_OR_INCONCLUSIVE**: No trusted registration exists on-chain for the supplied reference. Not labeled as tampering.
4. **REVOKED**: The certificate was permanently marked as revoked on the blockchain by its issuer or owner.
5. **ISSUER_NOT_AUTHORIZED**: The issuing institution is currently unapproved or suspended on the blockchain.
6. **VERIFICATION_UNAVAILABLE**: The blockchain RPC node is unreachable or the transaction receipt cannot be confirmed.
7. **INVALID_FILE**: The file is corrupted, empty, unsupported, or exceeds size limits.
