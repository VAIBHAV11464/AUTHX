# Task 10 — offline MediaPipe infrastructure

Completed in the authorized Task 10–11 batch on 2026-09-27. No landmark scoring change was enabled in this batch.

- Added the official `float16/1` Face Landmarker model, local checksum verification, provenance in `models/face_landmarker.json`, and a pinned MediaPipe runtime. Model SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` (3,758,596 bytes). The binary is ignored by Git and must be supplied separately on a fresh checkout.
- Pinned MediaPipe **0.10.35**, with a hashed dependency lockfile. The initial 0.10.30 trial installed but failed native Windows loading (`free` symbol missing) and was replaced. MediaPipe requires OpenCV contrib, so `opencv-python` was replaced with `opencv-contrib-python` at the same **5.0.0.93** version. Exactly one package provides `cv2`; NumPy remains **2.4.6** and original application package pins remain unchanged.
- Added lazy CPU landmark loading, immutable per-frame measurements, shared-instance locking, and explicit close handling. IMAGE mode prevents tracking state or timestamp counters from passing between users. Each frame is measured once per supplied clip; later blink/lip consumers use those returned points.
- Added locks around shared YuNet/SFace operations, reusable YuNet and SFace models keyed by local model path, and a scoring-local v2 detection cache. Face quality, identity, and current legacy measurement helpers can reuse detections within the v2 call. Legacy detector selection/scoring remains unchanged.
- Six runtime tests passed: actual offline model initialization/blank inference, a public Google portrait fixture producing 478 landmarks, model reuse, missing/tampered model errors, concurrent landmark/SFace serialization, YuNet reuse, and detection-cache isolation. Existing 42 smoke checks and all 56 previous regression tests passed after the dependency change. `pip check` and Python compilation passed.

Source copies, installation logs, test logs, and preservation checks are in `backups/task10-11/`. The real database and original ONNX model hashes are unchanged. All API tests write temporary databases.

References: [Google's Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python), [model bundle](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker), and [MediaPipe 0.10.35](https://pypi.org/project/mediapipe/0.10.35/).

Limits: blank and portrait fixtures verify inference, not live-user accuracy. Inference succeeded with network access restricted. The selected upstream binary attempted a Clearcut metrics upload, which failed without affecting inference. MediaPipe's [privacy notice](https://github.com/google-ai-edge/mediapipe#privacy-notice) describes on-device input processing and runtime metrics; this package should not be described as making zero network attempts. AuthX does not download models at runtime or send recordings itself. Real-camera latency remains unmeasured.

**Task 10 complete; legacy remains the default.**
