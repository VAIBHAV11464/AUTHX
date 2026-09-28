# Task 11 — capture rate and audio/video timing

Completed in the authorized Task 10–11 batch on 2026-09-27.

- V2 session start returns additive `captureFrameMs: 50`, selected from the session's starting profile. The wizard uses this response for both Look and Speak, so a configuration change after page load cannot select the wrong recorder. Legacy keeps the existing 100 ms Look and 200 ms Speak intervals and recorder.
- Both v2 steps target 20 frames per second for three seconds. Frame timestamps use actual capture times from `performance.now()`, without rounding, duplicates, or invented catch-up frames after stalls. The existing flash remains 400 ms within the server-selected window.
- V2 Speak uses a local AudioWorklet to record samples by their actual audio frame index. Video and the planned audio sample window share a three-second epoch. The worklet trims boundary blocks precisely, reports the actual first sample offset, and sends no microphone sound to playback.
- The browser rejects absent/interrupted/noncontiguous audio instead of constructing silence. Resource cleanup closes the audio context and microphone tracks on success/failure; early audio failure cancels video capture. Unsupported AudioWorklet receives retry guidance.
- Added optional `audioStartMs` to v2 uploads, checked as finite numeric 0–250 ms. Existing clients default to zero. Session Speak aligns the current lip-energy sampling to that offset and stores the offset in existing detail JSON. Invalid timing returns 400 without saving Speak. Recording bodies retain the 8 MiB limit and current image sizing/encoding.

Four Python timing tests passed, alongside all previous regression suites. Node simulations passed for ideal 60-frame/three-second video, real timestamps under encoding stalls, flash-window ticks, and exact contiguous three-second AudioWorklet sample boundaries. Existing wizard enrollment simulation and syntax checks passed.

Run `tests/capture_timing.py` with `.venv/Scripts/python.exe` and `node tests/capture_timing.js`. Logs and original source copies are in `backups/task10-11/`.

Limits: timing tests simulate browser clocks and processing. Actual Windows camera/microphone latency, timer throttling, audio-device latency, and 20 fps achievement need live evaluation. A slow/hidden browser may capture fewer frames; later measurement checks request retry for inadequate evidence. The audio offset represents software sample-clock alignment, not a calibrated hardware latency measurement. The design, roles, flow, three-second prompts, and legacy default remain intact.

**Task 11 complete. Tasks 12–14 begin only after the requested 30-second pause. No push performed.**
