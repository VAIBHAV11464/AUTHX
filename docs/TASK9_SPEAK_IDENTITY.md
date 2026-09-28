# Task 9 — identity checking during Speak

Completed on 2026-09-27, Asia/Calcutta. Scope: Task 9 only, following the completed Tasks 4–8. Legacy remains the default.

## Changes

- V2 session Speak now receives the authenticated account's stored enrollment and calls the Task 8 quality-approved matcher with no flash cutoff. It checks quality across the full Speak capture, reuses the quality pass's detected face rows for SFace extraction, and compares the three highest-confidence approved frames against enrollment. Their median cosine is retained without rounding. Old scaled and new normalized enrollment vectors remain compatible.
- Startup applies an additive, repeatable migration adding nullable `results.speak_cosine`. Historical values remain NULL. `save_voice()` stores the new cosine alongside existing voice measurements in the same update. Look's cosine remains separate. No raw images or audio are stored.
- V2 machine SAFE requires both server-stored cosines to be finite, valid, and >= `COSINE_MATCH` (`0.363`). Missing, malformed, or below-threshold Speak identity cannot be compensated by voice, blink, or flash scores. An otherwise SAFE score is capped at 74/SUSPICIOUS; lower labels retain the existing arithmetic and classification.
- A usable wrong-person Speak capture saves its voice/identity measurements and proceeds through the existing result and certificate flow with the gated label. Existing Speak locking applies. Unusable quality, missing enrollment, invalid model features, missing models, or unsuccessful lip scoring do not save Speak. The existing retry/error handling remains available.
- Speak and trust resolve the session's pinned profile. Switching the global setting cannot bypass v2 identity or alter legacy behavior. Legacy Speak receives its original arguments and retains its algorithms. The standalone `/api/voice/score` endpoint retains quality-only scoring and cannot supply session identity evidence.
- The design, roles, Enroll → Look → Speak → Certificate flow, weights, response fields, recording timing, dependencies, and certificate hash format are unchanged. Faculty overrides retain their existing behavior; this gate applies to machine scoring.

## Verification

Commands run with the project-local Python environment:

```powershell
.\.venv\Scripts\python.exe tests\speak_identity.py
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\verification_profiles.py
.\.venv\Scripts\python.exe tests\uploads_quality.py
.\.venv\Scripts\python.exe tests\enrollment_matching.py
```

All passed: **12 Task 9 tests, 42 baseline smoke checks, 10 profile tests, 17 upload/quality tests, and 17 enrollment/matching tests.** Python compilation of modified application modules and the new test file also passed. SMTP credentials were blanked only in the smoke subprocess. No persistent server was started.

Task 9 coverage includes:

- A successful Look followed by a different face in Speak, through both API scoring routes, producing SUSPICIOUS with high non-face scores and a certificate with an intact chain.
- Same-person success, old unnormalized enrollment compatibility, unchanged Speak response fields, and repeat-submission locking.
- Independent valid/raw threshold requirements in both steps, exact `0.363` acceptance at fusion, and stored `0.36296` rejection despite its rounded display value. Client-submitted cosine fields cannot override stored evidence.
- Missing historical Speak identity, pinned profiles in both directions, and unchanged standalone voice scoring.
- Full-clip Speak matching including late frames; skipping poor-quality high-confidence frames; three-feature median aggregation; reuse of quality detections.
- Multiple faces, absent faces, missing models, invalid enrollment, and invalid model features preserving Look and leaving Speak open for retry.
- Migration with row preservation, repeated initialization, historical certificate preservation, and intact chains. The profile suite also migrates a temporary read-only backup of the real database and compares original rows and chain statuses.

Existing test fixtures were updated to supply valid Speak cosine where they exercise unrelated v2 Look/profile behavior. The Task 9 migration fixture explicitly closes its SQLite connection so Windows can remove its temporary database.

Logs, pre-change source copies, and preservation hashes are in `backups/task9-speak-identity/`.

## Preservation and limits

All database writes used temporary databases. The real `authx.db` was not initialized or migrated during this task, and its SHA-256 remained unchanged. Existing accounts, enrollment vectors, results, and certificates are preserved. Model binaries, configuration, and dependency files also retained their checksums. The next ordinary app startup adds the new nullable column automatically.

Historical legacy attempts continue to use legacy behavior. Historical v2 Speak results without measured cosine cannot qualify for machine SAFE when trust is recalculated. Stored certificates are not rewritten.

Tests use synthetic vectors/images and controlled detector/audio/lip results. They verify routing, score gates, data preservation, and failure behavior; they do not measure biometric accuracy, spoof resistance, or ordinary-laptop processing latency. The three-frame median is a step-level identity check, not continuous tracking of every face across the recording. Matching uses the account's enrollment available at request time, as Look already does. Thresholds remain provisional pending the planned volunteer evaluation.

**Task 9 is complete. Task 10 has not started. No GitHub push was performed.**
