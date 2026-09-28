# Task 13 — normalized lip measurement

Completed in the authorized Tasks 12–14 batch, after the Task 10–11 checkpoint and 30-second pause.

V2 replaces mouth-region image gradients with inner-lip separation (landmarks 13/14), divided by mouth width (78/308). Uniform image scaling and translation leave this ratio unchanged. The existing 0.45/0.25 correlation thresholds and 90/60/25 lip scores remain; measured still mouth scores 20. The provisional normalized mouth variance floor is 0.0001.

Quality-approved Speak frames are measured once, and the resulting landmarks supply lip geometry. Energy is RMS over an 80 ms audio window centered at `video tMs - audioStartMs`. Samples outside recorded audio coverage are excluded. At least 12 aligned samples, 80% coverage, and gaps <= 150 ms are required. Invalid geometry/audio, absent coverage, silence, or effectively unvarying energy return `insufficient_lip_evidence` with no lip score. The old neutral 50 fallback is retained only by legacy.

Session Speak still compares identity against enrollment before measuring lips. A failed lip step leaves Look intact and Speak available for retry. V2 standalone voice uses the same quality/landmark/audio checks without session identity requirements and retains its response structure. Its optional audio offset is validated identically. Acoustic analysis and 75% acoustic / 25% lip voice weighting remain unchanged.

Successful Speak stores normalized mouth variance, lip method/configuration/model snapshots, evidence sample count, and audio offset in existing detail JSON. No raw images, landmarks, or audio are stored. The existing response fields, UI layout, roles, and certificate hashing are unchanged.

The 19 Task 12–14 checks passed, including scale/translation invariance, correctly aligned synthetic mouth/audio correlation, degraded correlation with the wrong offset, still mouth, silence, constant/invalid energy, sparse/missing landmarks, audio coverage, API retries, and complete scoring/certificate flow. Existing Task 9 identity tests still pass with landmark fixtures isolating their identity cases. Logs: `backups/task12-14/`.

Limits: mouth opening and acoustic energy do not prove the requested word, speaker identity, or spoof resistance. Natural articulation, device latency, and head pose may reduce correlation and require tuning. Live accuracy and latency remain unmeasured; word recognition begins in Tasks 15–16, stronger SAFE gates in Task 17.

**Task 13 complete. Legacy remains the default.**
