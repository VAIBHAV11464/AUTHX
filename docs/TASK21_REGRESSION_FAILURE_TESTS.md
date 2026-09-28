# Task 21 — regression and failure tests

Completed in the authorized Tasks 21–22 batch, 2026-09-28. Legacy remains the default. All writes use temporary databases or read-only-derived copies; no real database initialization, dependency/model changes, commit, push or deployment.

## Reproducible suite and retained evidence

```powershell
Set-Location 'D:\AI PROJECT'
.\.venv\Scripts\python.exe backups\task21-22\check.py a-new-run-name --extra regression_failures
```

Use a new run name: log files are created exclusively. The explicit runner executes all 14 prior Python scripts, the new failure suite, five Node simulations, Python compilation, all eight application JavaScript syntax checks and `pip check`. Every unittest suite must report a nonzero completed count. SMTP is disabled in subprocesses, the configuration default stays legacy, and public/synthetic inference records go to the new run directory. The offline speech test no longer overwrites Task 15's historical output. Tests reuse helper modules by module name, avoiding discovery of imported TestCase classes; duplicate historical method text is not counted twice.

The authoritative reviewed run is `backups/task21-22/task21-reviewed-result.json`: **42 smoke checks, 172 unittest cases, zero skips and five Node simulations passed**, together with compilation, all eight JS syntax checks and `pip check` (30 commands, all exit 0). Counts: profiles10, uploads17, enrollment17, identity12, runtime6, timing4, landmarks19, speech5, challenge16, gates12, summaries9, lifecycle17, atomic14, new failures14. Initial suite/gap logs are retained separately. The first gap run reproduced three failures and three errors in twelve cases. The initial full run encountered one import failure during the short interval between related source edits; it is not presented as a passing checkpoint. The reviewed run uses the completed source.

## Coverage and demonstrated fixes

| Roadmap area | Executable coverage |
| --- | --- |
| Old enrollment and migration | Profile, enrollment/matching, Speak identity and lifecycle suites: scaled old vectors; old direct-call signatures; repeated additive migrations on read-only clones; complete original-column and certificate preservation. |
| Roles, OTP and JWT | New failure suite: full password → OTP → JWT faculty/admin login; replay, wrong-code and replacement login; two synchronized concurrent verifiers; stale selected code; exact expiry and expiry during hash verification; corrupt timestamps; failed-write rollback; malformed input and UTF-8 byte bounds; signature/expiry/subject and current database role; ownership before evidence. |
| Retries and concurrency | Word/lifecycle suites: four total submissions, fourth success, restart/reopen, crash lease recovery, invalid/setup failures without charge, stale worker/refund isolation, generation/result guards, expiry during processing, concurrent submissions/connections. |
| Malformed captures and missing models | Upload/quality/timing, landmark runtime/evidence, speech and new failure suites: body limits, image/WAV/container/timestamps/audio alignment, no failed-step writes, real missing model paths, integrity faults and controlled native exceptions. |
| Overrides | Lifecycle/summary/atomic suites: authenticated actor, spoofed actor fields ignored, transaction rollback, separate machine result, generations, history and frozen issuance. |
| Revocation and certificate chains | Smoke/atomic/lifecycle plus new API test: admin-only repeated revocation, byte-preserved revoked snapshot, certified rotation and idempotent reissuance, one-session and different-session concurrency, collision/insert/status/serialization rollback, broken history retained. |

The completed OTP tests demonstrated application defects and led to focused fixes in `app/routes/auth.py` and `app/models.py`:

- A successful verifier now consumes the OTP under `BEGIN IMMEDIATE`, rereads unused state and expiry after obtaining the lock, and issues a token only after the consume commit. Two requests selecting the same code cannot both succeed. A newer login invalidating that row also blocks a stale verifier.
- Expiry is `now >= expires_at`, including a code expiring during bcrypt verification. Invalid timestamps fail closed; old naive UTC timestamps retain compatibility.
- Non-object login/OTP JSON returns the existing 401 errors. Inputs exceeding bcrypt's 72-byte UTF-8 bound and malformed hash values fail authentication without truncation or server exceptions.
- A failed OTP update rolls back, issues no token and allows a later valid retry.

No verification thresholds, enrollment representations, media inference, risk arithmetic, roles, UI, routes, certificate serializer or hash algorithm changed. No schema migration was added in Task 21. The existing local demo console OTP delivery behavior remains.

## Preservation and limits

`backups/task21-22/preserve.py before` verified all handoff/reference checksums, archived 103 source files and recorded 23 protected hashes. It made a SQLite backup using a read-only source and compared every original table row without printing account/OTP/embedding values. The reviewed checkpoint archive/manifest compares all original rows again and verifies the original fusion, legacy Look/Speak and certificate hash function syntax trees.

The real database SHA-256 remains `ef2a8941eea53701388d1b593b755a2aee49252cac6d62b89fb0acb1d4dd279b`. Source/dependency/model inventories and local preservation backup contain sensitive original data and must stay local.

Evidence categories are distinct: synthetic rule tests, mocked API integration, actual local native/model inference on public or SAPI synthetic fixtures, and Node DOM/device simulations. They establish tested policy, failure and storage behavior. They do not establish volunteer accuracy, live blink/lip sensitivity, spoof resistance, accent coverage, calibrated hardware timing or reference-laptop end-to-end latency. Task 22 follows only after this reviewed checkpoint; Tasks 23–24 remain outside this batch.
