# Synthetic formal raster protocol cases

Six positive/negative pairs cover the new branches of PreparedDataBundle,
RenderScene, RenderReceipt, ResolvedMap, MapSpecLock and GenerateRequest.
These are structural Schema examples, **not runnable projects or approvals**.
All references are synthetic/project-relative. Digests are illustrative after
path sanitization and renderer attestation is zeroed, so these fixtures cannot
pass runtime digest/HMAC verification. No source TIFF/CSV or keys are bundled.

`test_schemas.py` checks these cases without optional GIS/rendering dependencies.
`test_raster_formal.py` separately creates actual tiny TIFFs, immutable artifacts,
valid HMAC receipts and test-only G2/G3 grants in temporary directories. That suite
checks real runtime bindings and rejection/recovery, and never registers a
production scenario or claims to test T1/TP/G1 template publication.
