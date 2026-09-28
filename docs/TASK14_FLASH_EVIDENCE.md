# Task 14 — missing versus measured flash evidence

Completed in the authorized Tasks 12–14 batch, after the Task 10–11 checkpoint and 30-second pause.

V2 now distinguishes missing/unusable observations from an observed weak response. Flash samples reuse cached YuNet face detections within the current scoring call. Before/during brightness windows retain the server-selected flash start and 400 ms duration.

Each window needs at least four face brightness samples spanning >= 150 ms. Samples must be finite, increasing, and separated by <= 150 ms, including the transition between windows. Near-black or fully saturated window means cannot measure a reliable brightness change and request retry. Missing data returns `insufficient_flash_evidence`; invalid brightness returns `invalid_flash_evidence`. Both return `ok: false`, with no score or reflection measurements, so a failed Look cannot save/lock or earn the old neutral contribution.

With valid samples, the existing brightness delta thresholds remain: >= 0.08 scores 90, >= 0.03 scores 60, weaker response scores 25. An observed flat response therefore gets score 25 and delta zero. Out-of-window brightness changes do not increase the response score. Reflection correlation remains measured from the actual brightness and flash gate.

Legacy retains its existing missing-data score 50 and algorithms. V2 missing evidence uses retry guidance in the current wizard without changing its layout. Measurement snapshots/sample counts use existing detail JSON; response fields and certificate hash format remain intact.

All 19 combined evidence tests passed. Flash checks cover strong/weak responses, missing either window, insufficient/sparse samples, ordering, nonfinite/saturated/black observations, out-of-window jumps, API failures that preserve retry availability, and legacy's neutral fallback. Other suites passed: 42 baseline smoke checks, 56 previous regression tests, six runtime tests, four timing tests, and both Node simulations. Python compilation and `pip check` passed.

Preservation hashes confirm the original database, original ONNX models, local landmark model, and batch-start dependency files remain unchanged during Tasks 12–14. API/database tests used temporary databases. Certificate chains remain intact; historical certificates were not rewritten. Logs, pre-change source copies, pause evidence, and preservation records: `backups/task12-14/`.

Limits: brightness is a demo heuristic affected by camera exposure, screen brightness, movement, and illumination. Thresholds/sample bounds require real-camera evaluation. A measured weak response still participates in the existing weighted trust formula; Task 17's further eligibility policy is deferred. Old stored v2 records are not retroactively reevaluated by this capture check.

**Tasks 10–14 complete. Task 15 has not started. No GitHub push performed.**
