# Task 4 — session verification profiles

Completed on 2026-09-27, Asia/Calcutta. Scope: profile infrastructure only.

## Changes

- `config.py` reads `VERIFICATION_PROFILE`, defaulting to `legacy`. `.env.example` documents that default. Only exact `legacy` and `v2` values are accepted; invalid startup settings raise a clear error before database initialization.
- `init_db()` applies an additive, repeatable migration adding `sessions.verification_profile` with `NOT NULL`, a SQL default of `legacy`, and a check restricting values to `legacy` and `v2`. Historical attempts become legacy even when the startup setting is v2.
- Session start stores the server-selected profile. The setting is not accepted from the student's request. Existing direct callers retain the prior positional arguments and legacy default; explicit profiles use a new keyword argument.
- Look, Speak, and trust fusion resolve the stored session profile through `app/services/verification_profiles.py`. The existing Look/Speak calculations were extracted there, retaining their scores, detail fields, fallback behavior, and error responses. Both registered profiles currently use those same calculations and the existing risk fusion.
- Configuration changes and restarts affect newly started sessions. Reopening continues to use the stored profile on the same attempt, preserving existing reopening behavior until Task 19.
- No template, CSS, browser capture, role, certificate snapshot/hash, model, or dependency changes were made. No later verification upgrade was implemented.

## Verification

Run from `D:\AI PROJECT`:

```powershell
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\verification_profiles.py
```

The baseline smoke suite passed all 42 checks (`smoke ok`, exit 0). SMTP credentials were blanked only in its subprocess so the OTP test could not send email.

The Task 4 suite passed 10 tests (exit 0). It covers:

- Defaults, explicit profile selection, ignored client profile requests, old direct-call compatibility, and invalid profile/database constraints.
- Additive migration of pre-profile sessions, full row preservation, repeat initialization, SQLite integrity, and certificate chain preservation.
- Every scoring step retaining its starting profile across configuration changes and app restart, in both directions. Distinct test handlers make selection of the wrong profile fail even though both real profiles currently share scoring.
- Reopening retaining its original profile; legacy Look success/failure results; v2 placeholder equivalence, including silence and the three baseline trust fixtures.
- Migration on a temporary SQLite online backup of the existing database, with all original columns/rows and certificate chain statuses compared before and after. The real source is opened read-only.

The Task 4 test log and exit/preservation record are saved in `backups/task4-20260927-profiles/verification-profiles.log` and `result.json`. A source comparison against the Task 1 snapshot confirmed that the extracted Look algorithm is identical at the Python syntax-tree level and that original files outside the intended Task 4 changes (plus Task 2's prior `.gitignore` edit) remain unchanged.

## Preservation and limits

The real `authx.db` was not initialized or migrated during this task. Its SHA-256 remained `EF2A8941EEA53701388D1B593B755A2AEE49252CAC6D62B89FB0ACB1D4DD279B`. Accounts, enrollment embeddings, results, and certificates were unchanged. Starting the updated application will apply the migration automatically, assigning legacy to all existing attempts.

`v2` is a reserved profile using legacy algorithms at this stage. This task does not improve measured accuracy or establish readiness to enable the upgraded verifier. No live camera/microphone evaluation was performed. The profile selector is pinned; arbitrary changes to individual scoring thresholds/model files are not snapshotted by this infrastructure. Model/configuration evidence versions remain later work.

OpenCV's existing graph-engine target warnings appeared in the baseline suite; all checks passed. Historical certificate bytes and hashes are preserved; adding profile evidence to certificates remains Task 18.

**Task 4 is complete. Task 5 has not started. No GitHub push was performed.**
