# Task 15 — offline speech infrastructure

Implemented 2026-09-28 in the authorized Tasks 15–16 batch. This checkpoint adds an independent service; verification scoring and decision routes are unchanged at this stage.

The project pins Vosk 0.3.45 and uses the official `vosk-model-small-en-us-0.15` English model. The [official model listing](https://alphacephei.com/vosk/models) lists Apache 2.0 licensing. The [installation guide](https://alphacephei.com/vosk/install) supports Windows x86/64 but its Python version range is old; compatibility with this exact Windows x64 CPython 3.11.15 environment is established by local native initialization and inference checks, not by claiming the guide certifies Python 3.11.

Dependency resolution retained every existing package pin, including MediaPipe 0.10.35, NumPy 2.4.6 and the sole OpenCV contrib 5.0.0.93 provider. `requirements.lock` adds hash-pinned Vosk and its dependencies. Srt 3.5.3 is built from its hash-verified PyPI source distribution by uv; other additions use wheels. The install log is in `backups/task15-16/install.log`. Reproduce with `uv pip sync requirements.lock --python '.venv/Scripts/python.exe' --require-hashes --cache-dir '.runtime/uv-cache'` (do not use the previous all-binary restriction for srt).

## Local model setup

Download only at setup time:

```powershell
Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' -OutFile 'models\vosk-model-small-en-us-0.15.zip'
Get-FileHash 'models\vosk-model-small-en-us-0.15.zip' -Algorithm SHA256
Expand-Archive -LiteralPath 'models\vosk-model-small-en-us-0.15.zip' -DestinationPath 'models'
.\.venv\Scripts\python.exe check_speech.py
```

Archive: 41,205,931 bytes, SHA-256 `30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498`. The source provenance manifest `models/vosk-model-small-en-us-0.15.json` records the source/license/version and all 14 extracted file hashes. Its pinned SHA-256 is `54e9e66b9592bbf3489d59a8b2d3460327671d25ee5f263f1e3280e1ea9cad29`. These are locally measured integrity records of the official HTTPS download, not an independently published signature. The binaries/archive are ignored by Git; the manifest is preserved. Do not regenerate the manifest to accept a changed model.

`check_speech.py` checks setup without creating the Flask application or initializing any database. It can optionally transcribe a local WAV pathname. Missing models/manifests return `speech_model_missing`; bad checksums/manifests return `speech_model_invalid`; incompatible packages or native initialization/decoder failures return `speech_runtime_unavailable`. No placeholder transcript or confidence is fabricated.

## Runtime

`app/services/speech.py` verifies local integrity before loading, caches the model by path/config/file metadata, and checks changed files again. A shared lock serializes model initialization/recognition; every call creates a fresh recognizer with no cross-attempt decoder state. The constructor always receives a local model path. It never uses `Model(lang=...)`, downloads, `SetGrammar`, or an expected-word vocabulary. `SetWords(True)`, intermediate `Result()` segments, and `FinalResult()` provide the measured words/confidences, following the [official example](https://github.com/alphacep/vosk-api/blob/master/python/example/test_simple.py).

The upload reader already resamples supported mono PCM16 input rates to 16 kHz. The independent speech service also handles every allowed rate (8/16/22.05/32/44.1/48 kHz), using time-based interpolation and PCM16 quantization without relabeling samples at the wrong rate. This does not improve lost bandwidth in an 8 kHz capture. Lip alignment/scoring audio and existing weights are unchanged. Result evidence is bounded, JSON-safe text and confidences; no recordings are persisted.

## Validation and limits

All 42 smoke checks, 90 regression/runtime tests, both Node simulations, compilation and pip checks passed. Task 15 validation results are recorded in `backups/task15-16/task15-result.json`; stage-specific logs prove the scoring/routes/database/wizard sources match the pre-change snapshot. The standalone speech suite covers real local loading and the public upstream Vosk sample, silence/state isolation, unrestricted per-attempt decoder construction, all supported rates/duration/PCM values, intermediate/final segment aggregation, missing/corrupt setup, native failures, bad audio and nonfinite confidence. The upstream fixture source is `https://raw.githubusercontent.com/alphacep/vosk-api/master/python/example/test.wav`; it is kept in ignored `.runtime/fixtures/vosk-test.wav`, with SHA-256 `dcfea5712c43a43ba7ae8083afb39d36993e5a69c46e88b68aaa72b65cb615bb`. Python socket connection calls are blocked during the actual inference test. This establishes local fixture inference, not volunteer recognition accuracy or measured end-to-end laptop latency.

The real database was never initialized. Its checksum and those of all three existing face models match the batch-start preservation inventory. Source copies and a read-only SQLite backup are local in `backups/task15-16`. Legacy remains the default. No push was performed.
