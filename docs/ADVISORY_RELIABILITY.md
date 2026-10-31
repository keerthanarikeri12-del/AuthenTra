# Advisory reliability corrections

The four advisory panels previously overstated what their implementations could establish. The corrections deliberately preserve unknown results instead of generating scores or claims unsupported by evidence.

## Current behavior

- **Fields:** extracted values are never filled from the expected registration. Every registered field must be observed and match before returning `ALL_MATCHED`. Missing values remain missing; ambiguous aliases remain ambiguous; grades are critical. The verification endpoint checks the metadata signature against the blockchain issuer and binds the metadata commitment to the blockchain file hash. Legacy unsigned records return unavailable. Registration no longer fabricates a signature when signing fails. A signature establishes the signer, not the accuracy of OCR or whether a human reviewed each field.
- **Visual localization:** no trained localization weights exist in this implementation. With no reference image, the endpoint reports unavailable. The optional supplied-image comparison reports connected pixel-difference regions, without tampering probabilities. It only resizes the reference; it does not provide geometric registration, explain causation, or establish the reference's authorization. The verification endpoint does not currently provide retained reference images. JPEG error-level heuristics are not used as model predictions.
- **Rescan/compression:** measured quality values are advisory. A single image cannot establish its transformation history. Matching registered text does not exclude edits elsewhere. Exact byte matches skip quality assessment and return null for measurements not performed.
- **Routing:** nonverified documents cannot be cleared by advisory similarity. OCR confidence is not calibrated forgery confidence. The returned calibrated confidence is null; the layout score is explicitly an uncalibrated keyword heuristic.

The visual preview now follows the loaded image's proportions instead of a fixed landscape canvas. Boxes are only shown after the image loads, use the returned coordinates without minimum-size inflation, and keep labels inside the box. Historical compression-heuristic findings are explicitly labeled unreliable instead of redisplaying their boxes. Exact blockchain file-hash matches skip visual accusations, while issuer and revocation checks still control authenticity.

## Repeatability and limitations

For identical bytes, reference state, dependencies and policy, the decision rules are deterministic. Runtime duration, record identifiers, timestamps and blockchain state are not fixed. Previously saved verification reports are historical snapshots and are not rewritten; submit a fresh verification after restarting the backend to see the corrections.

This change does **not** supply a trained forensic localization model, a rescan classifier, an unfamiliar-layout model, or held-out calibration data. It does not establish perfect accuracy. Those capabilities require licensed model artifacts, representative labeled originals and altered variants, institution/template-separated evaluation, and calibration on separate data. Protected authorized reference storage and real image alignment are also outstanding. Do not use the older comprehensive evaluation's heuristic scores as evidence of real-world model accuracy.

## Regression checks

`tests/test_advisory_evidence.py` covers missing fields, ambiguity, optional fields, metadata tampering, signature/hash binding, repeated visual results, unmeasured values and review routing. `tests/test_features_1_to_4.py` covers the existing feature interfaces with corrected expectations. Run these against a disposable database with `AUTHENTRA_DB` set; never use production records for tests.
