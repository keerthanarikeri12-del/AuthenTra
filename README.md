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

Choose **User Login**, **Institution Login**, or **Administrator**, then enter your credentials. For local demo login:

| Role | Email |
| --- | --- |
| Verifier | `verifier@authentra.demo` |
| Approved institution | `issuer@authentra.demo` |
| Pending institution | `pending@authentra.demo` |
| Platform administrator | `owner@authentra.demo` |

All development accounts use `AuthenTra-demo-2026!`. These accounts are created only in explicit demonstration mode. Never use them or the deterministic development wallets on a public deployment.

## Demonstration

1. Open the Verifier workspace.
2. Choose **Original**, then **Verify certificate**: expect **Verified**.
3. Choose **Modified**: expect **Possible Tampering**.
4. Choose **Unregistered**: expect **Not Registered**.
5. Choose **Revoked**: expect **Revoked**.
6. Choose **Scanned copy**: expect **Possible Tampering**, because the scan is not byte-identical to the PDF. Clear the ID to exercise OCR extraction.
7. Inspect the independent check results and the separate AI advisory. Save the JSON report or export your history as CSV.
8. Sign in as Institution to register one or several original files and revoke your records. Assign a unique ID per file. Reusing an ID returns an explicit error.
9. Sign in as Administrator to inspect institutions, approve or disable them and review activity. Issuer approval is an on-chain action.
10. Open **System architecture** and **Evaluation & evidence** to explain the research contribution and its limitations.

The generated certificates are clearly marked as demonstrations, not real qualifications. Their files are in `samples/`.

## Included capabilities

- Authenticated verifier, institution and platform-owner roles; password hashing and HttpOnly JWT cookies.
- Content-based PDF/PNG/JPEG validation, 10 MB per file, 20-file / 50 MB batch limit and five-page PDF limit.
- ID-first record lookup, original-byte SHA-256, current issuer approval and permanent revocation checks.
- Separate outcomes for Verified, Possible Tampering, Not Registered, Revoked, Not Verified, Inconclusive and Unable to Authenticate.
- Embedded PDF text extraction and offline English Tesseract OCR for images or the first page of scanned PDFs.
- An experimental synthetic-data Random Forest, separate from authoritative decisions.
- Per-file bulk results, transaction receipts, gas measurement, history, audit logs, JSON reports and CSV history export.
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

Full certificate uploads are not retained. `.local/chain.json` contains development signing keys and must not be shared. Do not expose the local RPC port or package runtime databases and signing files in a submission.

The local chain uses a JavaScript fallback when its optional native WebSocket module does not match Node.js. This is acceptable for a small demonstration; it can affect performance measurements.

## Separate account experiences

User Login creates ordinary verifier accounts. Institution Login accepts applications with institution name, official email, registration reference, verification information and a nonzero Ethereum wallet address. Official-email ownership and institutional identity are reviewed manually by the administrator; submitting an address does not prove ownership. Applications always start at `PENDING_APPROVAL`. Public registration ignores privileged role/status fields and cannot create administrators.

Existing database roles are retained: `verifier` = USER, `institution` = INSTITUTION_ADMIN, `owner` = SYSTEM_ADMIN. Users land on verification, approved institutions on their certificate registry, and owners on institution review. Navigation uses internal React state; no protected URL grants access. All protected APIs independently validate the cookie JWT (signature, issuer, expiry and subject), reload the database account, and deny institutions whose status is not APPROVED. Certificate issuance also requires on-chain issuer approval. Histories, registrations and institution audit queries are scoped by the authenticated account; SQLite is backend-only and has no RLS facility.

The administrator reviews application details under Institutions, provisions a funded server-side signer in `ISSUER_PRIVATE_KEYS`, and approves the wallet. Approve, reject, suspend and revoke authorization all write the corresponding blockchain approval first, then persist the application status and audit event. A failed chain action leaves the database status unchanged. These two stores do not share a transaction: if the chain succeeds but the database write fails, retry the administrative action to reconcile them. Revoking institutional authorization disables issuance; individual certificate revocation remains a separate permanent operation. Existing sessions are denied on their next protected request after suspension.

`backend/storage.py:initialize` performs an idempotent additive migration on startup, preserving existing accounts and certificate history. Legacy accounts receive APPROVED application eligibility for compatibility, while the existing on-chain issuer check remains authoritative for issuance. New institution accounts default to PENDING_APPROVAL. Back up the SQLite database before upgrading. Existing duplicate wallet addresses (case-insensitive) must be resolved before the unique wallet index can be created.

Copy `.env.example` values into your backend process environment (the server does not automatically load dotenv files). Keep signing keys and JWT_SECRET server-side and use HTTPS outside explicit local demo mode. Existing owners remain the only administrator accounts; there is no public administrator registration. No Supabase or second authentication provider is introduced.

Authentication regression tests, including failed login, portal mismatch, privilege injection, pending approval, suspension of an existing session, administrative transitions, private history and missing/expired JWT claims:

```powershell
.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=.local/auth-tests
node node_modules/vite/bin/vite.js build
```
