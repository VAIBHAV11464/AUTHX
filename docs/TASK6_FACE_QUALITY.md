# Task 6 — face-quality checks

Completed on 2026-09-27, Asia/Calcutta, after Task 5's initial validation passed. Changes are gated by the v2 profile; legacy remains the default.

## Behavior

`detect_all_faces()` exposes every detected YuNet face for the quality gate while the legacy `detect_faces()` interface still selects the largest face. V2 uses the existing lower detector threshold, 0.4, to notice additional faces. The gate checks one enrollment image and each Look/Speak clip before calling the existing scoring algorithms.

| Gate | Initial threshold / retry reason |
| --- | --- |
| Face count | Reject any frame with multiple detected faces: `multiple_faces`. No detected face: `no_face`. |
| Face size | Both box sides at least 80 px and box area at least 2% of image: `face_too_small`. |
| Confidence | At least 0.6: `weak_face`; enrollment retains its existing additional 0.7 gate. |
| Visibility | At least 90% of the face box inside the image: `face_cut_off`. |
| Lighting | Grayscale face mean 40–225: `face_too_dark` / `face_too_bright`. |
| Clipping | At most 60% of face pixels at <=15 or >=245: `uneven_face_lighting`. |
| Blur | Laplacian variance at least 25 on a normalized 128×128 grayscale face crop: `face_blurry`. |
| Clip readiness | At least eight usable frames and at least 80% usable frames in the relevant window. Return the most common quality failure, or `too_few_usable_face_frames` when the window itself is too short. |

For Look, size/lighting/blur readiness is measured on pre-flash frames. Every frame, including flash/post-flash frames, is still checked for multiple faces. The deliberate flash is therefore not treated as bad lighting. Speak checks the full video for quality; this does not check identity against enrollment yet.

Quality failures return HTTP 422 with a specific `reason`; missing models return HTTP 503. Rejections leave the failed step open for retry and do not replace an existing enrollment. The wizard maps these reasons to short instructions in its existing status area. The design, roles, Enroll → Look → Speak → Certificate flow, and recording timing are unchanged.

## Checks

The final combined `tests/uploads_quality.py` run passed 17 tests, including nine quality tests. They cover individual gates, all-face versus largest-face detection, minimum frame counts and the 80% ratio, expected flash illumination, a second face after the flash, preservation of embeddings/results on rejection, a successful retry, successful Speak/standalone response contracts, missing models, and profile pinning in both directions.

All 42 existing smoke checks and all 10 profile regression tests also passed. The profile tests were updated so their old Task 4 placeholder-equivalence check now verifies retained legacy risk fusion; v2 now intentionally has additional quality gates. JavaScript syntax and Python compilation passed. OpenCV's existing graph-engine warnings persisted without failing the smoke checks.

All database writes used temporary databases. The real database checksum was unchanged. Model binaries, dependency files, historical certificate snapshots/hashes, and user accounts were preserved. The final test log and validation record are in `backups/task5-6-20260927-validation/`.

## Limits and deferred work

Quality tests use synthetic image crops and controlled detector results; no live camera/microphone or volunteer accuracy study was performed. Lighting and sharpness thresholds are provisional and may need tuning across skin tones, cameras, compression, and room conditions. The new quality pass adds detector work; laptop scoring latency has not been measured.

The quality gate permits a small minority of unusable frames and does not filter/select matching frames. The existing matcher still uses its legacy confidence ranking; quality-approved frame matching belongs to Task 8. Enrollment remains single-image (Task 7 deferred). Identity checking during Speak, MediaPipe, blink/lip replacements, word recognition, stronger SAFE gates, and evidence summaries remain later tasks. Current v2 is not validated for enabling the final upgraded verifier.

**Tasks 5 and 6 are complete. Task 7 has not started. No GitHub push was performed.**
