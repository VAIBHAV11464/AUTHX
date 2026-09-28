# Task 5 — validate uploaded recordings

Completed on 2026-09-27, Asia/Calcutta. Task 5 was implemented and its initial seven tests passed before starting Task 6 in the same authorized request.

## Behavior

`app/services/uploads.py` adds bounded decoding for v2 enrollment, Look, Speak, and standalone voice scoring. Session routes use their stored starting profile. Enrollment and standalone scoring use the current server profile. Legacy capture parsing/scoring remains intact; legacy remains the default.

Invalid v2 uploads return HTTP 400 with `ok: false` and a specific `reason`. A failed enrollment preserves the existing embedding; failed Look/Speak validation does not save results or lock the step. No raw recordings or additional tables are introduced.

| Input | Accepted bounds |
| --- | --- |
| Request body | Existing 8 MiB maximum, shared by both profiles. HTTP 413 now returns JSON `upload_too_large` for readable wizard feedback. |
| Image | Single JPEG/PNG; strict base64 or base64 data URL; each side 64–1280 px, area at most 921,600 pixels. Dimensions checked before image conversion/decompression. |
| Clip memory budget | At most 30,000,000 decoded image pixels across the clip. |
| Frame count | 8–90 frames, including Speak; invalid frames reject the upload rather than being silently skipped. |
| Timestamps | Actual numeric values, excluding booleans; finite, nonnegative, strictly increasing, at most 4000 ms. First frame at most 500 ms. |
| Video span | Last timestamp minus first timestamp: 2000–4000 ms. |
| Audio | RIFF/WAVE mono PCM16, uncompressed; sample rates 8000, 16000, 22050, 32000, 44100, or 48000 Hz; duration 2000–4000 ms. Existing resampling to 16 kHz is retained. |
| WAV container | Complete declared RIFF/chunk lengths, consistent PCM format/byte rate/block alignment, whole samples, exactly one format/data chunk. Well-formed ancillary chunks are accepted. Truncation is rejected before scoring. |

These bounds accommodate the existing three-second, approximately 30-frame Look and 15-frame Speak captures. Capture intervals and audio/video synchronization have not been changed; Task 11 remains deferred. Audio/video cross-alignment and actual capture provenance are not established by timestamp validation.

## Checks and preservation

Final commands:

```powershell
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\verification_profiles.py
.\.venv\Scripts\python.exe tests\uploads_quality.py
```

Results: 42 baseline smoke checks, 10 profile regression tests, and 17 combined upload/quality tests passed. The combined suite contains eight upload tests with subcases for valid boundaries, oversized dimensions, malformed images/base64, frame counts, invalid/duplicate/backward/nonfinite timestamps, durations, WAV format/header/truncation issues, request limits, and preservation on rejected API requests.

All test writes use temporary databases. SMTP was disabled for the smoke-test subprocess. No persistent server was started and the real `authx.db` was not initialized. Its SHA-256 remained `EF2A8941EEA53701388D1B593B755A2AEE49252CAC6D62B89FB0ACB1D4DD279B`.

The final combined test log and validation record are in `backups/task5-6-20260927-validation/`. Thresholds and format bounds are initial demo choices, not a claim of measured biometric accuracy. Dependencies, models, accounts, enrollments, and certificates were preserved.

**Task 5 is complete. Task 6 was also explicitly authorized and is documented separately. No GitHub push was performed.**
