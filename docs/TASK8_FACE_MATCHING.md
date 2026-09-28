# Task 8 — quality-approved face matching and SAFE identity gate

Completed on 2026-09-27, Asia/Calcutta, after Task 7's initial checks passed. V2 changes only; legacy remains the default.

## Changes

`face_quality.inspect_clip()` now returns approved pre-flash frames and their detected face rows alongside the existing readiness result. It retains the minimum eight usable frames, 80% readiness ratio, and full-clip multiple-face checks from Task 6. Speak still uses the existing quality-only wrapper.

`face_matching.match_quality_frames()` selects the three highest-confidence candidates from approved pre-flash frames only, creates their SFace features, and takes the median cosine against enrollment. It reuses the quality pass's face rows, so matching does not run a second legacy face detector pass. Blink and flash scoring still receive the original full capture and keep their current algorithms.

Old unnormalized and new normalized 128-component embeddings are normalized in memory without rewriting stored enrollment. Malformed enrollment returns `not_enrolled`. Invalid/nonfinite/zero model features return `invalid_face_embedding`; unavailable model operations retain `model_missing`. Failed Look scoring does not save or lock the step.

V2 stores unrounded cosine in the existing `results.cosine` REAL column and returns it in the existing response field. Face-score mapping remains the prior mapping. The v2 trust handler uses the server-stored cosine, with the session's stored profile, to enforce an independent SAFE requirement of cosine >= `COSINE_MATCH` (`0.363`). Missing, nonfinite, nonnumeric, or impossible cosine cannot qualify. A machine result that would otherwise be SAFE is capped at 74/SUSPICIOUS when this gate fails. Lower existing labels remain unchanged.

This preserves the existing weights, label thresholds, routes, response fields, and certificate hash format. Legacy sessions continue using the original matcher and fusion. Faculty override behavior remains unchanged; the new gate applies to machine scoring. Certificate issuance records the resulting label through the existing flow, with no historical certificate rewrite.

## Verification

```powershell
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\verification_profiles.py
.\.venv\Scripts\python.exe tests\uploads_quality.py
.\.venv\Scripts\python.exe tests\enrollment_matching.py
node tests\wizard_enrollment.js
```

Results: all 42 baseline smoke checks, 10 profile tests, 17 upload/quality tests, and 17 enrollment/matching tests passed. The wizard simulation, Python compilation, and JavaScript syntax checks passed. The existing profile/quality fixtures were updated to test the new v2 matching and fusion contracts while retaining their legacy assertions.

Nine matching tests cover:

- Excluding poor-quality high-confidence frames and all flash/post-flash frames from feature extraction; median aggregation over approved candidates.
- Old scaled enrollment compatibility, invalid vectors, insufficient usable evidence, multiple faces, and reuse of the quality detections.
- Unrounded `0.36296` remaining below the gate despite rounding to `0.363`, exact `0.363` eligibility, and missing/invalid cosine evidence.
- Strong non-face scores failing to compensate for a below-threshold face match; API selection of stored cosine/profile across configuration changes; resulting certificate labels and intact chains.

All database writes used temporary databases. SMTP credentials were disabled for the smoke subprocess; no persistent application server or live camera/microphone session was started. Logs and preservation hashes are saved in `backups/task7-8-20260927-validation/`. OpenCV's pre-existing graph-engine warnings remained non-fatal.

## Preservation and limits

The real database checksum is unchanged. Existing accounts, enrollment vectors, results, certificates, model binaries, and dependency files were preserved. No new database migration was needed for Tasks 7/8.

Tests use synthetic vectors/images and controlled detector results. They establish routing, arithmetic, boundary behavior, and data preservation; they do not establish biometric accuracy or spoof resistance. The existing/provisional quality and enrollment thresholds still need volunteer validation. Laptop processing latency remains unmeasured.

Identity during Speak remains Task 9; landmark-based blink/lip checks, spoken-word recognition, other SAFE eligibility gates, evidence summaries, and evaluation are still deferred. V2 remains an intermediate implementation and has not been enabled as the default.

**Tasks 7 and 8 are complete. Task 9 has not started. No GitHub push was performed.**
