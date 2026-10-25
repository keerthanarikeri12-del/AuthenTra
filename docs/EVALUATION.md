# Initial validation results

Measured locally on 24 October 2026. These are prototype checks, not production certification or research proof of broad fraud-detection accuracy.

| Check | Observed result |
| --- | --- |
| Python backend test suite | 26 tests, covering decisions, authentication, private history, AI separation, network failure, OCR fallback and bulk handling |
| Solidity contract tests | 9 passed: owner-only approval, approved-issuer issuance, stored hashes, immutable IDs, cross-issuer rejection, disabled-issuer rejection, owner revocation, repeat-revocation rejection and issuer-owned revocation |
| Frontend production build | Passed |
| Real-chain end-to-end verification | 8 of 8 controlled outcomes matched expectations |
| OCR on one generated scan | 4 of 4 target fields extracted correctly |
| HTTP verification latency | Mean 1.170 seconds; p95 5.488 seconds across seven timed requests, including a scan and first-model-load overhead |
| Three-file registration batch | 2 registrations succeeded; 1 deliberate duplicate was rejected |
| Batch timing | 304 ms; 6.58 successful registrations/second for this tiny batch |
| Registration gas | 71,186 gas per successful record in that batch |
| Synthetic Random Forest | Precision 1.0, recall 1.0, F1 1.0 on 120 generated held-out examples |

## Interpretation

The trusted verification and permission checks behaved as intended in the tested cases. The scan produced Possible Tampering because it differs from the registered PDF at the byte level. It was not incorrectly labeled a proven forgery.

The synthetic model's perfect test score reflects easy generated anomalies, not realistic fraudulent documents. The browser demonstration also exposed a false positive: an unchanged registered sample received an AI anomaly warning. The application correctly kept its primary result Verified and showed the warning separately. This limitation must accompany any presentation of the AI metrics.

Only one clean generated scan was used for field accuracy. Bulk throughput was measured on three files and a local chain. Neither result supports broad accuracy or scalability claims. Public-network transaction prices were not measured.

## Repeatability

Run the commands in the README. Model training uses a fixed random seed and a template-group split. System timings depend on machine load, OCR startup and caching. The evaluation scripts write their measured JSON reports to `.local/`; the UI reads those reports. Backend test databases and smart-contract test chains are isolated from the demonstration database and chain.

Browser checks confirmed sign-in, original-file verification, modified-file classification, independent check evidence and the separate AI warning. The responsive workspace was inspected in the in-app browser at a narrow viewport.
