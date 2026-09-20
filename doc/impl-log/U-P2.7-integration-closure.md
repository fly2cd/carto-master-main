# U-P2.7 Integration Closure

Date: 2026-09-18
Branch: `U-P2`

## Implemented

- Added `revision` to `JobState` and strict stale-state rejection.
- Added the Draft 2020-12 `state-transition` protocol with valid/invalid fixtures.
- Added a cross-process run lock and held it across complete workflow mutations.
- Added receipt-first/state-second transition journaling with automatic recovery.
- Preserved `waiting_approval` in job state instead of collapsing it to `pending`.
- Added constrained failed-state retry and immutable receipt queries.
- Added `status`, `retry`, and `receipts` integration to both routes through the single `carto` CLI.
- Verified that template approval cannot be reused for map G1.
- Made deterministic template YAML evidence writes idempotent for identical content and conflicting for changed content.
- Preserved failed validation evidence and wrote retries to attempt-scoped directories; publication resolves the successful evidence from immutable step receipts instead of a fixed path.
- Closed all implemented approval-consumption crash windows without weakening nonce replay protection.
- T1 and G1 persist a claims-validated workflow-local approval intent before nonce consumption, then recover only by reconstructing and exactly verifying the deterministic staging package or candidate artifact set.
- TP recovers from the immutable publication transaction and its retained authenticated approval; G2 recovers only from an exact immutable `MapSpecLock` and matching approval context.

## Verification

- Full suite: `python -m unittest discover -s skills/carto-agent/scripts/tests -v`
- Result: 110 tests run: 109 passed, 1 skipped (symbolic-link creation unavailable on Windows), 0 failures.
- Schema check: 43 registered schemas checked successfully.
- Python compilation completed successfully.
- Real controlled Chromium SVG/PNG/PDF tests passed in the full suite.

## Environment fingerprint

- Probe time: `2026-09-18T04:27:04.005124Z`
- Platform: `Windows-11-10.0.26200-SP0`
- Python: `3.14.7`
- Browser: `Chromium 152.0.7977.83`
- Node: `v24.20.0`
- Renderer fingerprint: `sha256:2f581a82f086272d2467d40c362d44ea1f926de9d6269ff0a46134bf7534aa4b`
- Offline rendering, WebGL, SVG composition, headless export, and SVG/PNG/PDF export were available.

## Explicit limits

- No real CRS transformation.
- No G3 or formal delivery transaction.
- No production-data flood assessment claim.
- No external basemap networking.
- No business creation routes for `map-brand`, `map-style`, or `map-layout`.
- Approval nonces remain strict one-time values. Recovery is allowed only when authenticated immutable recovery evidence proves the exact already-consumed approval and the deterministic artifact/context; ordinary nonce replay remains rejected.
- `retry` does not overwrite or delete immutable artifacts. Validation retries use `validation/attempt-N/`; publication follows the successful immutable receipt reference. Identical deterministic writes may be replayed; changed content is rejected.
