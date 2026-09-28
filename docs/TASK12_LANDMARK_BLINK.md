# Task 12 — landmark blink detection

Completed after Tasks 10–11 and the requested 30-second pause, in the authorized Tasks 12–14 batch.

V2 now measures both eyes from six MediaPipe contour points per eye using the [eye aspect ratio geometry](https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf). Coordinates are converted to image pixels before computing ratios. This implementation uses an explicit temporal state machine, not the paper's trained classifier. [MediaPipe's contour definitions](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py) identify the eye/lip contours.

A blink needs two open observations, bilateral closure, and reopening, wholly before the server-stored flash start. Initial closed eyes, a dip without reopening, a wink, closures lasting over 500 ms, reopening at/after the flash, and landmark/quality dropouts across a blink cannot count. Provisional EAR boundaries are open >= 0.21 and closed <= 0.17; accepted closure duration is 40–500 ms. These are configuration values requiring volunteer validation.

Only quality-approved pre-flash frames are sent to the landmark model. Rejected frames retain missing positions in the temporal sequence. Evidence needs at least eight usable observations, 80% coverage, and gaps no larger than 150 ms. Missing evidence returns `insufficient_blink_evidence`; adequately measured captures without a complete cycle retain `no_blink`. Failed Look does not save or lock the step. Missing/invalid landmark models return HTTP 503 with setup guidance.

Existing `blinkScore`, `blinkCount`, and `dipPercent` response fields remain. One/two blinks score 90, more score 70. `dipPercent` now describes geometric EAR change in v2. Legacy retains its original gradient signal and timing behavior. New measurement/configuration snapshots and sample counts use existing detail JSON; separate Look/Speak snapshots prevent later measurements from overwriting the earlier configuration record.

`tests/landmark_evidence.py` passed all 19 checks across Tasks 12–14. Blink coverage includes completed/multiple cycles, initial closure, missing return, flash boundaries, wink, sustained closure, sparse input, invalid geometry, rejected quality frames, retries, and legacy behavior. All previous regression suites and baseline smoke checks passed. Logs and source snapshots: `backups/task12-14/`.

Limits: thresholds are provisional. Synthetic geometry establishes boundary/sequence behavior, not blink sensitivity with actual volunteers, glasses, varied head pose, or small eyes. No production anti-spoofing claim or live-user accuracy claim is made.

**Task 12 complete. Legacy remains the default.**
