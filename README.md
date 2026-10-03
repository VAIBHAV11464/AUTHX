# AuthX

AuthX is a Flask application for face enrollment, blink/flash checks, voice and lip-motion scoring, and hash-linked verification certificates. It has student, faculty, and admin views.

The GitHub source package includes the application, tests, documentation and selected anonymous QA summaries. Local credentials, databases, recordings, signed consent, preservation archives, internal handoff packets, environments and model binaries are excluded. Historical task reports describe their original checkpoints; their commit/push status applies to those checkpoints. Other `backups/` paths mentioned in those reports refer to local preservation artifacts.

## Run the current application

The Task 2 environment is ready in `.venv`, using project-local CPython 3.11.15. In PowerShell:

```powershell
Set-Location 'D:\AI PROJECT'
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000/login>. Stop the server with Ctrl+C.

For the local demo, sign in directly with password `pass`: `avinash` is a student, `sriram` is faculty, and `vaibhav` is admin. Newly created databases seed these same credentials. This intentionally weak shared password is only for the loopback demo; change it before exposing AuthX to other users. Faculty/admin OTP can be restored by setting `AUTHX_REQUIRE_OTP=true`.

Activation is optional: the command above explicitly selects the correct Python and avoids PowerShell activation-policy problems. Do not use the global `python` command to start this project; it may select MSYS2 Python instead.

In another PowerShell window, a running server can be checked with:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5000/api/health'
```

The expected response has `name: AuthX` and `status: ok`.

## Run the baseline smoke tests

```powershell
Set-Location 'D:\AI PROJECT'
.\.venv\Scripts\python.exe tests\smoke_api.py
```

The script creates and removes a temporary test database. A successful run ends with `smoke ok`. Task 3 passed all 42 checks; see [the test results](docs/TASK3_BASELINE_TESTS.md) for coverage and limitations. The application does not need to be running for this test.

## Verification profiles — Task 4

`VERIFICATION_PROFILE=legacy` is the default; set it in `.env` or the process environment before starting the app. The accepted values are `legacy` and `v2`. V2 now includes upload validation, face-quality gates, five-image enrollment, identity matching in both steps, MediaPipe blink/lip measurements, synchronized capture, flash evidence checks, and offline challenge-word verification. Acoustic scoring and risk weights retain the existing algorithms. Keep the demo on legacy until the later upgrades and evaluation are complete.

Startup adds `sessions.verification_profile` if missing and marks all historical sessions as legacy. New sessions store the server's selected profile at start. Look, Speak, and trust scoring use that stored value, so changing the selector or restarting cannot switch an existing attempt. Reopening retains the session's original profile.

Run the Task 4 checks with:

```powershell
.\.venv\Scripts\python.exe tests\verification_profiles.py
```

These checks use temporary databases, including a read-only backup of `authx.db` when present. See [Task 4 results and limits](docs/TASK4_VERIFICATION_PROFILES.md). The existing design, roles, response fields, and certificate hash format remain unchanged.

## Upload validation and face quality — Tasks 5 and 6

For v2 sessions, malformed or incomplete captures return a specific reason before scoring. Uploads retain the 8 MiB limit. Supported images are single JPEG/PNG frames; recordings must span 2–4 seconds with 8–90 frames and finite, strictly increasing timestamps. Speak requires mono PCM16 WAV audio and video. Enrollment retains the existing embedding representation and single-image request compatibility.

V2 enrollment, Look, and Speak check for multiple faces, insufficient face size, cropped faces, unusable lighting, and blur. The existing wizard shows retry guidance within its current layout. Task 11 updates v2 capture timing; legacy timing remains unchanged. Quality failures do not save the failed step or replace an enrollment. Session requests use the stored profile; enrollment and standalone voice scoring use the current server setting because they have no session.

```powershell
.\.venv\Scripts\python.exe tests\uploads_quality.py
```

See [Task 5 upload bounds and results](docs/TASK5_UPLOAD_VALIDATION.md) and [Task 6 quality thresholds and limits](docs/TASK6_FACE_QUALITY.md). Legacy remains the default. These checks are an intermediate v2 stage and have not been evaluated with live volunteers.

## Enrollment and face matching — Tasks 7 and 8

In v2, the same Enroll button captures five images. At least three must be usable, and all usable samples must agree on identity before their normalized average is saved. An unsuccessful attempt preserves the old enrollment. Existing single-image clients and old embeddings continue to work; the legacy wizard still captures one image.

V2 Look matches only quality-approved pre-flash frames and retains the existing median-of-three aggregation. A machine SAFE decision also requires stored, unrounded cosine similarity >= `0.363`. Missing or invalid cosine cannot qualify for SAFE. Legacy scoring is unchanged. Task 9 adds the corresponding Speak check below.

```powershell
.\.venv\Scripts\python.exe tests\enrollment_matching.py
node tests\wizard_enrollment.js
```

The Node command is an optional simulated wizard regression check; running AuthX itself still requires only the Python environment. See [Task 7 results and compatibility](docs/TASK7_MULTI_IMAGE_ENROLLMENT.md) and [Task 8 results and limits](docs/TASK8_FACE_MATCHING.md).

## Identity during Speak — Task 9

V2 Speak compares the enrolled face again using the three highest-confidence quality-approved frames from the full Speak clip. The unrounded median cosine is saved in a new nullable `results.speak_cosine` column. Startup adds the column without rewriting historical data. Machine SAFE now requires raw cosine >= `0.363` in both Look and Speak; strong voice, blink, or flash scores cannot compensate for an identity mismatch. A usable recording with a mismatching face is saved and capped at SUSPICIOUS if its combined score would otherwise be SAFE. Unusable face evidence returns the existing retry/error response without saving Speak.

Legacy remains the default and retains its scoring. The standalone voice endpoint has no session identity gate; its v2 lip scoring now uses Task 13's landmarks. Older v2 results without measured Speak identity cannot qualify for SAFE when trust is recalculated. Existing certificates and their hashes are preserved.

```powershell
.\.venv\Scripts\python.exe tests\speak_identity.py
```

See [Task 9 results and limits](docs/TASK9_SPEAK_IDENTITY.md). The flow, design, roles, recording timing, and response fields are unchanged. Real-camera accuracy and processing latency still require evaluation.

## Landmarks, capture timing, and evidence — Tasks 10–14

The local environment now pins MediaPipe `0.10.35`, OpenCV contrib `5.0.0.93` (the sole `cv2` provider), and NumPy `2.4.6`. The Face Landmarker model is present locally and verified against its SHA-256 before loading. See [Task 10 setup and runtime limits](docs/TASK10_MEDIAPIPE.md), including the upstream package's metrics behavior. Inference works without internet; AuthX never downloads models at runtime.

The model binary is ignored by Git. On a fresh checkout, after installing `requirements.lock`, obtain the versioned model:

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' -OutFile 'models\face_landmarker.task'
Get-FileHash 'models\face_landmarker.task' -Algorithm SHA256
```

Expected SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.

V2 records both three-second steps at a target 20 fps and aligns audio samples with video timestamps using a local AudioWorklet. Browser stalls retain real timestamps and do not fabricate frames. See [Task 11 timing and limits](docs/TASK11_CAPTURE_TIMING.md).

V2 blink scoring requires both eyes to complete open–closed–open before the flash. V2 lip scoring correlates normalized mouth opening with aligned audio energy. Geometry uses quality-approved frames; missing evidence requests a retry. V2 flash scoring distinguishes an observed weak response from missing/unusable samples; missing evidence receives no neutral contribution. Legacy algorithms remain unchanged. See [Task 12 blink](docs/TASK12_LANDMARK_BLINK.md), [Task 13 lips](docs/TASK13_LANDMARK_LIPS.md), and [Task 14 flash](docs/TASK14_FLASH_EVIDENCE.md).

```powershell
.\.venv\Scripts\python.exe tests\landmark_runtime.py
.\.venv\Scripts\python.exe tests\capture_timing.py
.\.venv\Scripts\python.exe tests\landmark_evidence.py
node tests\capture_timing.js
```

Model/configuration snapshots and evidence sample counts are stored in existing detail JSON, separately for Look and Speak. No raw recordings are stored. Offline word verification and the v2 decision gates are described below. V2 has not been enabled as the default.

## Offline challenge word — Tasks 15–16

Vosk `0.3.45` and the official small English `vosk-model-small-en-us-0.15` model are installed locally. AuthX verifies its file checksums and reuses the model with a fresh unrestricted recognizer per recording. Setup requires internet; inference uses local files and never downloads a model. See [Task 15 setup, checksums and compatibility](docs/TASK15_OFFLINE_SPEECH.md).

For a fresh checkout, install the hash lock with `uv pip sync requirements.lock --python '.venv/Scripts/python.exe' --require-hashes --cache-dir '.runtime/uv-cache'` (srt builds from its pinned source distribution). Download/extract the official model following Task 15, then check it without initializing a database:

```powershell
.\.venv\Scripts\python.exe check_speech.py
```

V2 session Speak now requires exactly one recognized token matching the server-stored word, with measured confidence >= **0.80**. Recognition is not restricted to the expected word. Wrong/empty/unclear/multiple words leave Speak unsaved and show retry guidance. Acoustic/lip/risk scores and Task 9's identity checks are retained.

Three retries mean the initial Speak submission plus three retries, **four total**. Valid submitted capture failures spend an attempt; malformed uploads, authorization/prerequisite/locked requests and setup/model failures do not. Counts persist across restarts and reopen, and concurrent submissions share one reservation. After exhaustion, use Look to start a fresh session. The [Task 16 report](docs/TASK16_CHALLENGE_WORD.md) defines the exact policy, failure responses and crash-recovery semantics.

Small transcript/confidence/model/config evidence is saved without recordings, alongside the separate Look/Speak measurement snapshots. Historical v2 voice scores without word evidence cannot obtain a newly calculated trust result or a new certificate; existing issued certificates and hashes remain intact. Legacy sessions and standalone voice keep their existing behavior.

```powershell
.\.venv\Scripts\python.exe tests\offline_speech.py
.\.venv\Scripts\python.exe tests\challenge_word.py
node tests\wizard_speech.js
```

The tests require documented local models/public and synthetic fixtures. Actual offline fixture inference passed, including accepted `amber`, rejected wrong `bridge`, and rejected multiword `say amber`. These fixtures do not measure live-user accuracy, accent coverage or laptop end-to-end latency. Keep `VERIFICATION_PROFILE=legacy` until later volunteer evaluation.

## Decision gates and evidence summaries — Tasks 17–18

V2 machine SAFE requires usable Look/Speak capture, matching raw identity in both steps, a completed pre-flash blink cycle, measured flash response, the verified server word and usable aligned lip evidence. Missing, invalid or historical evidence cannot be replaced by high scores. The original weights and SAFE>=75/SUSPICIOUS>=45 thresholds remain; an otherwise SAFE outcome with an ineligible gate is capped at 74. A valid measured weak/flat flash and usable low lip score remain eligible and retain their original contributions. See [Task 17 policy and checkpoint](docs/TASK17_V2_DECISION_GATES.md).

Session start/Look/Speak/trust/certificate and authorized faculty detail responses add optional `verificationVersion`, `evidence` and `retryable` fields, retaining every prior field. Compact summaries appear in the existing result, faculty and certificate views. They show recorded checks, word/confidence and the stored machine decision separately from labels faculty can change. Display does not recalculate historical labels. Legacy summaries explain that v2 checks were not required.

New v2 certificates freeze their evidence/model/configuration summary in additive score JSON fields using the existing hash algorithm. Historical and legacy certificate snapshots/hashes are not rewritten; their views explicitly say that evidence was not recorded. A new v2 certificate needs the gated machine snapshot from the existing trust step. See [Task 18 response/snapshot behavior](docs/TASK18_EVIDENCE_SUMMARIES.md).

```powershell
.\.venv\Scripts\python.exe tests\decision_gates.py
.\.venv\Scripts\python.exe tests\evidence_summaries.py
node tests\evidence_summaries.js
```

The Tasks 17–18 checkpoint passed 42 smoke checks, 127 Python regression/runtime tests and four Node simulations. Preservation and exact logs are in `backups/task17-18/result.json`. No live-user accuracy, spoof resistance, accent coverage or end-to-end latency study was performed.

## Session lifetime and faculty audit — Task 19

Unfinished sessions expire at ten minutes from their stored UTC start, including saved Speak awaiting trust. A scored/certified result remains available. Expired work returns `session_expired` and directs the existing wizard to start a fresh Look. The original deadline and v2 four-submission budget survive ordinary uncertified reopen; a late worker cannot save over a reopened attempt.

Faculty/admin reopen of a certified attempt creates a fresh session with the original profile and new server-selected challenge/timing. Concurrent/repeated requests return the same successor. The old session/results/certificate remain intact, including revoked certificates. The faculty view opens the new session. Ordinary uncertified reopen cannot extend the original deadline.

Faculty label actions now have separate authenticated actor/time/previous-label/machine-context audit records. Current views and new v2 certificate snapshots distinguish the selected label from the saved machine decision. Legacy certificate payloads retain their original serialization. Historical labels receive no invented audit or machine history. See [Task 19 semantics and checkpoint](docs/TASK19_SESSION_HANDLING.md).

```powershell
.\.venv\Scripts\python.exe tests\session_lifecycle.py
node tests\session_lifecycle.js
```

## Atomic certificate issuance — Task 20

Certificate lookup, eligibility, frozen snapshot, previous-hash lookup, insertion and certification now share one SQLite `BEGIN IMMEDIATE` transaction. Repeated requests return the same issued certificate, including after revocation or later session/configuration changes. Concurrent sessions append one correctly linked chain; errors roll back both the certificate and certification status. Existing certificate bytes/hashes and legacy serialization remain unchanged. See [Task 20 transaction checks and limits](docs/TASK20_ATOMIC_CERTIFICATES.md).

```powershell
.\.venv\Scripts\python.exe tests\certificate_atomic.py
```

Tasks 19–20 passed **42 smoke checks, 78 Python tests and three Node simulations**, compilation, JavaScript syntax and `pip check`. All 23 protected database/model/dependency hashes and original issued certificate rows match the fresh backup. Exact reviewed results are in `backups/task19-20/result.json`. Tests used isolated databases; no live hardware or volunteer evaluation was performed.

## Regression and failure suite — Task 21

The full reviewed suite passed **42 smoke checks, 172 Python unittest cases, zero skips and five Node simulations**, Python compilation, all eight application JavaScript syntax checks and `pip check`. It covers old enrollment/migration, roles and completed OTP login, retries, expiry, invalid uploads, missing models, concurrent workers, overrides, revocation and certificate chains. New tests fixed OTP reuse races, stale-code issuance, expiry boundaries and malformed authentication inputs; biometric scoring and certificate algorithms retain their prior behavior.

```powershell
.\.venv\Scripts\python.exe backups\task21-22\check.py a-new-run-name --extra regression_failures
```

Choose a fresh run name to preserve logs. The runner disables SMTP, explicitly lists every suite and records actual counts/skips. See [Task 21 coverage, fixes and limitations](docs/TASK21_REGRESSION_FAILURE_TESTS.md) and `backups/task21-22/task21-reviewed-result.json`. All original database rows and 23 protected hashes match the fresh read-only backup. These tests do not establish volunteer accuracy or live hardware latency. Legacy remains the default.

## Offline comparison harness — Task 22

The local harness runs legacy/v2 on identical original recordings and enrollment through the actual APIs, using temporary sessions/databases. It exports completion/SAFE outcomes, known incorrect-SAFE rates, retries, measured words and processing time as JSON, CSV and Markdown. Import existing upload JSON without changing media/timing using `tools/comparison_import.py`; see [the dataset and run guide](docs/COMPARISON_DATASET.md).

```powershell
.\.venv\Scripts\python.exe tools\comparison_demo.py --output .runtime\comparison-fixtures-new
.\.venv\Scripts\python.exe tools\comparison.py .runtime\comparison-fixtures-new\manifest.json --output .runtime\comparison-results\new-run --repetitions 2 --probes
.\.venv\Scripts\python.exe tests\comparison_harness.py
```

The native smoke demo ran four unique public/synthetic cases twice per profile (16 runs). Static images failed Look for no blink; v2 also rejected duplicated timestamps. Independent Vosk/Speak probes accepted amber and rejected bridge/multiple words, and are excluded from full-flow acceptance. Genuine acceptance, incorrect SAFE and completed-flow latency are unavailable because no labeled volunteer dataset was collected. Fourteen focused harness tests passed; the Task 22 API recheck passed 42 smoke checks and 68 Python tests with zero skips. See [Task 22 results and limits](docs/TASK22_COMPARISON_HARNESS.md), the [observed report](backups/task21-22/task22-observed-report/report.md) and `backups/task21-22/result.json`.

All original database rows, issued certificate bytes and 23 protected model/dependency/database hashes are preserved. Tasks 1–22 are complete. Tasks 23–24 are now authorized; their current status follows.

## Volunteer study and v2 readiness — Tasks 23–24

The actual volunteer evaluation is **pending**: no consented recordings, real camera identifiers or confirmed reference-laptop specification were supplied. Legacy remains the default. All genuine-completion, incorrect-SAFE and reference-laptop timing metrics are unavailable with zero authentic samples; preparation is not human validation.

The local study workflow includes a private consent/split registry, precollection source/config/model pin, two-camera/lighting/attack matrix, explicit consent-gated collection through the existing wizard, lossless original-upload export, paired API evaluation and a held-out readiness decision. Collection uses temporary app databases with SMTP disabled; media, private permission records and embeddings stay under ignored `.runtime/`. See [the executable protocol](docs/VOLUNTEER_STUDY_PROTOCOL.md), [unsigned consent template](docs/VOLUNTEER_CONSENT_TEMPLATE.md), [Task 23 status](docs/TASK23_VOLUNTEER_EVALUATION.md) and [Task 24 retain-legacy decision](docs/TASK24_V2_READINESS.md).

The prepared empty private registry is `.runtime/volunteer-study-task23-24/study.json`. To inspect its actual pending status without starting devices or the app:

```powershell
.\.venv\Scripts\python.exe tools\volunteer_study.py validate .runtime\volunteer-study-task23-24\study.json
```

Exit 2 means evidence/readiness is unavailable. Real collection requires reviewed signed permission, anonymous identity/source separation, actual camera/laptop details and the declared precollection protocol. The readiness runner excludes tuning/diagnostic/repeated recordings from held-out completion claims, preserves the four-Speak policy, and reports certificate completion separately from machine SAFE. V2 can become the default only after the original Task 24 targets are supported by authentic held-out evidence. The current [machine-readable decision](backups/task23-24/pending-reviewed/readiness.json) is `retain_legacy`.

## Environment and configuration

- `requirements.txt` declares application dependencies plus pinned MediaPipe, OpenCV contrib and Vosk.
- `requirements.lock` pins the resolved application dependencies with SHA-256 distribution hashes for the Python 3.11 environment.
- `.runtime/` holds the local interpreter, package cache, and preserved previous environment; it is ignored by Git.
- Existing YuNet/SFace ONNX files, the Face Landmarker task model, and the local Vosk English model reside in `models/`.
- The app reads optional settings from `.env`; see `.env.example`. SMTP is only used when optional faculty/admin OTP is enabled; without SMTP credentials, that mode prints codes to the server console.
- Starting the app initializes the database schema. An empty database seeds the three demo accounts with password `pass`; an existing database keeps its accounts and passwords until deliberately changed.

See [Task 2 environment notes](docs/TASK2_ENVIRONMENT.md) for exact setup, verification, and recovery details. The [Task 1 baseline](docs/TASK1_BASELINE.md) records the original behavior and preservation snapshot.
