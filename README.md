# AuthenTra

**AI-Assisted Digital Certificate Authenticity Verification Using Blockchain**

AuthenTra is a certificate verification platform that combines cryptographic proof on an Ethereum-compatible blockchain with local OCR and machine learning anomaly detection. 

The system uses **React/Vite** on the frontend, **FastAPI** on the backend, a **Solidity** smart contract running on a local **Ganache** blockchain, and an advisory **Random Forest** classifier.

---

## Quick Start

On Windows, start the entire local stack with one command from the project root:

```powershell
.\Start-AuthenTra.ps1
```

This starts the local blockchain (port 8545) and FastAPI backend (port 8000), checks the advisory ML model, seeds sample demo certificates, builds the production frontend, and validates service readiness.

Once started, open **http://127.0.0.1:8000** in your browser.

### Demo Accounts

All demo accounts use password: `AuthenTra-demo-2026!`

| Portal | Role | Demo Email | Purpose & Permissions |
| --- | --- | --- | --- |
| **User Portal** | `USER` | `verifier@authentra.demo` | Upload & verify certificates (up to 5 per batch); view private personal verification history. Cannot register credentials. |
| **Institution Portal** | `INSTITUTION_ADMIN` | `issuer@authentra.demo` | Accredited institution workspace; bulk issue certificates (up to 100 files) with on-chain registration; revoke credentials. |
| **Admin Portal** (`#admin`) | `SYSTEM_ADMIN` | `owner@authentra.demo` | Governance portal; approve, suspend, or revoke institutions on-chain (`setIssuer`); view platform audit logs. Strictly cannot upload or register certificates. |

---

## Recent Fixes & Reliability Improvements

We recently resolved several startup and end-to-end integration issues to make local runs rock-solid:

1. **Sequential Blockchain Transactions & Nonce Fix**
   - Wrapped the deployer wallet in `ethers.NonceManager` in `scripts/chain.mjs`. Sequential contract deployment and initial issuer approval transactions no longer fail due to stale nonces or pending transaction collisions.
   - Added two-stage bootstrapping (`bootstrapComplete` flag) so interrupted setups resume approvals without redeploying over existing data.

2. **Smart Chain Startup & Non-Destructive Readiness Probes**
   - `scripts/chain.mjs` now validates existing deployed bytecode, ABI functions (`lookupByHash`), and owner addresses before proceeding.
   - Added `scripts/chain.mjs --check` to quickly verify an already-running chain without submitting transactions or altering chain state.
   - Existing chain databases (`.local/chain-db`) are preserved without accidental redeployment.

3. **Accurate Subsystem Health Reporting**
   - The `/api/health` endpoint now verifies real database connectivity, live blockchain RPC communication, and actual advisory model prediction via `model_ready()`.
   - The server reports `"status": "ready"` only when all components are operational, returning `"degraded"` if any subsystem is unavailable.

4. **Preserved Administrative States During Demo Seeding**
   - `scripts/seed_demo.py` now respects existing on-chain issuer authorization status rather than unconditionally re-approving suspended issuers.

5. **Isolated Disposable Test Environments**
   - Live blockchain integration tests (`tests/conftest.py`) now spin up isolated disposable Ganache nodes on ephemeral ports with isolated directories. Running test suites will never overwrite, lock, or corrupt your local development demo database.

---

## Three-Role Architecture & Separation of Duties

AuthenTra enforces strict role separation across both the UI and backend APIs:

- **USER (Verifier)**
  - Access to verification dashboard and personal history.
  - Capped at 5 files per verification batch.
  - Blocked with HTTP 403 from registration endpoints.
- **INSTITUTION_ADMIN (Issuer)**
  - Restricted to accredited educational domains (`.edu`, `.ac.in`, `.edu.in`, `.res.in`, etc.) or vetted allowlists.
  - Requires email verification and system admin approval (`APPROVED` status) before issuing certificates.
  - Can bulk upload up to 100 certificates with OCR extraction and commit them to the blockchain.
  - Can revoke certificates issued by their own institution wallet.
- **SYSTEM_ADMIN (Governance)**
  - Dedicated admin portal (`#admin`).
  - Governs institutional access with on-chain synchronization via `setIssuer(wallet, approved)`.
  - Zero certificate upload or issuance capability (calls to `/api/verify` or `/api/certificates` return HTTP 403).

---

## How Verification Works

Verification follows a strict hierarchy where cryptography is authoritative and AI is advisory:

### 1. Authoritative Blockchain & Hash Verification
The certificate file's SHA-256 digest is matched directly against the immutable smart contract registry (`AuthenTraRegistry.sol`):

- **VERIFIED**: Certificate reference exists on-chain, file SHA-256 matches exactly, issuing institution is currently approved, and certificate is not revoked.
- **POSSIBLE_TAMPERING_OR_FILE_MISMATCH**: Certificate ID exists on-chain, but the uploaded file hash does not match (e.g., altered name, modified text, or re-exported file).
- **NOT_REGISTERED_OR_INCONCLUSIVE**: No record exists on-chain for the supplied certificate ID.
- **REVOKED**: Certificate was explicitly revoked on-chain by the issuing institution or owner.
- **ISSUER_NOT_AUTHORIZED**: The issuing institution is suspended or unapproved.
- **VERIFICATION_UNAVAILABLE**: Blockchain RPC node is unreachable or transaction confirmation timed out.
- **INVALID_FILE**: Unsupported format, corrupted file, or exceeds page/size limits (max 10 MB, max 5 pages).

### 2. Advisory OCR & AI Analysis
- **Text Extraction**: Uses embedded PDF text extraction or offline English Tesseract OCR.
- **Random Forest Anomaly Detection**: An experimental model evaluates text layout, character ratios, and keywords to flag synthetic irregularities.
- **Advisory Scope**: AI findings are displayed separately and **never** override cryptographic hash and blockchain proofs.

---

## Manual Terminal Setup

If you prefer running services manually across separate terminal windows:

```powershell
# 1. Start the local blockchain
node scripts/chain.mjs

# 2. In a second terminal: Train model, seed samples, build frontend, start server
.venv\Scripts\python.exe scripts/train_model.py
.venv\Scripts\python.exe scripts/seed_demo.py
node node_modules/vite/bin/vite.js build
.venv\Scripts\python.exe scripts/server.py
```

For frontend development with live hot-reloading:
```powershell
pnpm dev
```
Vite runs at `http://127.0.0.1:5173` and proxies API requests to `http://127.0.0.1:8000`.

---

## Running Tests

All test suites can be run locally using the project commands:

```powershell
# 1. Python test suite (177 unit, integration, and live chain tests)
.venv\Scripts\python.exe -m pytest tests -q --tb=short

# 2. Smart contract EVM checks (14 tests)
node tests/contract.mjs

# 3. Frontend validation checks (4 tests)
node --test tests/uploads.test.mjs

# 4. Playwright browser E2E tests (7 tests across verifier and institution flows)
node node_modules/@playwright/test/cli.js test

# 5. Live demo evaluation benchmarks
.venv\Scripts\python.exe scripts/evaluate.py
.venv\Scripts\python.exe scripts/evaluate_bulk.py
```

---

## Project Structure

| Directory / File | Description |
| --- | --- |
| `src/` | React frontend (responsive UI, validation, dashboard, and portal views) |
| `backend/main.py` | FastAPI application endpoints, authentication, and role authorization |
| `backend/core.py` | Authoritative verification decision engine |
| `backend/documents.py` | File validation, OCR text extraction, and model loading (`model_ready`) |
| `backend/registry.py` | Web3 contract integration and transaction signing |
| `backend/storage.py` | SQLite database schema, user accounts, and audit logs |
| `contracts/AuthenTraRegistry.sol` | Solidity smart contract for issuer authorization, registrations, and revocations |
| `scripts/chain.mjs` | Local Ganache blockchain runner, contract deployer, and `--check` validator |
| `scripts/seed_demo.py` | Generates sample demo certificates (`original.pdf`, `modified.pdf`, etc.) |
| `tests/conftest.py` | Disposable chain fixture for isolated integration testing |
| `.local/` | Ignored local runtime files (chain database, model artifact, and logs) |
