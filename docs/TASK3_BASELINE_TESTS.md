# Task 3 — baseline smoke-test results

Completed on 2026-09-27, Asia/Calcutta. Only Task 3 was performed. No application or test-code fixes were needed; no verification upgrades or GitHub pushes were performed.

## Result

**PASS: 42 checks; process exit code 0; final output `smoke ok`.**

Command: `.\.venv\Scripts\python.exe tests\smoke_api.py`

Environment: project-local Windows CPython 3.11.15 with Task 2's pinned dependencies, including NumPy 2.4.6 and OpenCV 5.0.0.93.

Artifacts: `backups/task3-20260927-020353/smoke-api.log` and `result.json`. The log contains the individual check results; the JSON records exit status and preservation checks.

## Existing coverage exercised

| Area | Checks |
| --- | --- |
| Face scoring and model handling | Identical/different vectors, cosine mapping, model-file presence, blank image rejection, missing-model handling. |
| Blink and flash scoring | Flat eye signal, complete synthetic blink valley, flash brightness jump, flat brightness, jump outside the expected flash window. |
| Audio and lip scoring | Silence, low-frequency hum, varied versus steady tones, still/moving mouth signals, combined voice weighting. |
| Risk fusion | Expected SAFE, SUSPICIOUS face-cap, and DEEPFAKE fixture scores. |
| Login and permissions | Health response, wrong-password rejection, successful student login, faculty OTP requirement, student denial on faculty list/detail APIs. |
| Session prerequisites | Enrollment required before starting, successful start, UUID format validation, challenge-word pool, random flash-time bounds. |
| Certificates | SAFE/SUSPICIOUS issuance, identifier prefix, genesis and previous-hash links, certificate page fields, chain integrity. |
| Invalid input and information exposure | Invalid enrollment image/audio rejected; faculty HTML does not embed the fixture scores before authenticated retrieval. |

## Preservation and isolation

- The smoke script switches its database path to a new temporary database before importing/creating the Flask app. Fixture accounts, password updates, enrollments, attempts, and certificates operate there.
- SMTP credentials were disabled only for the test subprocess and the prior environment-variable values restored afterward. No OTP emails were sent during this run.
- The original `authx.db` SHA-256 before and after testing matched exactly.
- Application/configuration files, model binaries, the smoke-test script, and the dependency lockfile remained unchanged. Task 3 adds this report and a README section explaining the existing test command.
- No persistent server was started. The temporary smoke-test database was removed by the script.

## Limits of this result

These checks establish that the existing tested behavior works with the restored environment. They do not establish real-user biometric accuracy or resistance to spoofing. Face matching fixtures use synthetic vectors, and the certificate flow inserts fixture scores rather than performing an end-to-end camera/microphone recording.

The suite checks that faculty login requests OTP, but does not complete OTP verification or exercise every admin/faculty action. Full validation of revocation, overrides, reopening, concurrency, and the planned upgrades remains later work.

OpenCV emitted its existing graph-engine target warnings, as observed in Task 2. The test completed successfully; no dependency changes were made to suppress the warnings.

**Tasks 1, 2, and 3 are complete. Task 4 has not started. Push only when explicitly ordered by the user.**
