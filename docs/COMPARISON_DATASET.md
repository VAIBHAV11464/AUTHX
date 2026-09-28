# Local comparison dataset and run format

The executable driver is `tools/comparison.py`; `tools/comparison_import.py` imports already recorded upload JSON. Neither starts devices nor recruits/records people. Dataset media and any embedding files belong in ignored `.runtime/` or another private local directory. Use anonymous case/enrollment identifiers. Do not add recordings, consent documents or embeddings to Git or the real AuthX database.

## Import existing captures

Retain the original Look `{frames: [{tMs, image}, ...]}` and Speak `{frames: [...], wav, audioStartMs}` upload bodies. Save the original enrolled image separately. `image`/`wav` may be strict base64 or base64 data URLs. The importer decodes those original bytes to local files and preserves every `tMs` and the software audio offset. It performs no image resizing, time interpolation, WAV resampling or silence padding. Malformed media/timing is evaluated by the real route policy when running the comparison.

Supply metadata from the original server session and actual dataset record:

```json
{
  "datasetId": "local-evaluation",
  "id": "case-001",
  "fixtureCategory": "consented",
  "consentRecorded": true,
  "split": "evaluation",
  "timingProvenance": "captured_sample_clock",
  "source": "Anonymous local recording; consent documented separately",
  "expectedWord": "amber",
  "flashStartMs": 2000,
  "groundTruth": {"category": "genuine", "safeExpected": true, "wordMatch": true}
}
```

This illustrates the format for later authorized data, not a claim that this batch collected such a recording. Set unknown truth to `category: "unknown"`, `safeExpected: null`, `wordMatch: null`; do not infer truth from either profile's result. Use the server-stored word and flash timing, never a requested client word or guessed flash window. Existing challenge words and configured timing bounds remain authoritative.

```powershell
.\.venv\Scripts\python.exe tools\comparison_import.py `
  --look .runtime\recordings\look-upload.json `
  --speak .runtime\recordings\speak-upload.json `
  --enrollment .runtime\recordings\enrolled.jpg `
  --metadata .runtime\recordings\case-metadata.json `
  --output .runtime\datasets\case-001

.\.venv\Scripts\python.exe tools\comparison.py `
  .runtime\datasets\case-001\manifest.json `
  --output .runtime\comparison-results\case-001-run-1
```

Both outputs require fresh directories. Original input files are read-only. A consent declaration refers to separately documented consent; it does not obtain consent. Volunteer capture/evaluation requires separate Task 23 authorization.

## Manifest contract

The importer emits an executable `authx-comparison-dataset-1` manifest. `tools/comparison_demo.py` generates the four complete public/SAPI demo cases. These generated manifests are working examples; no media is embedded in the documentation.

| Field | Required meaning |
| --- | --- |
| `schemaVersion`, `datasetId` | Supported version and stable identifier (1–64 letters/digits/underscores/hyphens, starting with a letter/digit). |
| `provenance` | Local dataset record describing origin/transforms; original asset hashes are recommended. It is not copied into public outcome summaries. |
| `enrollments` | Map of stable reference IDs to `{method, path}`. Method `legacy_single_image` derives one common enrollment through the real legacy enrollment API. `existing_embedding` reads a private local JSON vector, verifies compatibility and uses it unchanged for both profiles. No comparison of different enrollment methods is implied. |
| `cases` | Nonempty list of unique case IDs, each referencing one common enrollment. |
| `fixtureCategory` | `public`, `synthetic` or `consented`. Consented cases require explicit `consentRecorded: true`. Mixed public portrait/synthetic audio demo cases are labeled synthetic. |
| `split` | `demo`, `tuning` or `evaluation`; never merge tuning data into claims about held-out evaluation. |
| `timingProvenance` | `captured_sample_clock` for original measured timestamps; `synthetic_schedule` for explicitly synthetic tests. This is declared provenance, not proof that an upload was captured live. |
| `expectedWord`, `flashStartMs` | Original server challenge and integer flash start within the current bounds. The driver constrains only the isolated server's challenge selection; Vosk recognition remains unrestricted. |
| `groundTruth` | `category`: unknown/genuine/wrong_person/wrong_word/photo/screen_replay/other_negative; `safeExpected`: boolean/null; `wordMatch`: boolean/null. Labels come from known recording conditions, not scores. |
| `attempts` | Ordered original capture submissions. Each has `lookFrames`, `speakFrames` (`[{path, tMs}, ...]`), `wav` path and optional `audioStartMs` (default zero, retained client compatibility). Paths are relative to the manifest directory and must stay inside it. |

To assemble multiple imported cases, retain all asset files under one dataset directory, prefix their relative paths with their case subdirectory, combine the case records and enrollment references into one manifest, and retain unique stable IDs. An ordered `attempts` list may hold distinct recordings for a real retry sequence. Repeating one file is only a repeated measurement, not another independent recording or evidence of improved human completion.

Both profiles receive the identical original base64 bytes, timestamps, WAV, software offset and enrollment. The loader does not repair an invalid capture. The API may reject it differently under the two existing policies. Pair fingerprints cover media, enrollment reference bytes, challenge and flash; the driver also verifies the prepared originals were not mutated.

## Processing and reporting semantics

Each case/profile/repetition starts a new isolated session. The actual API pins its profile/word/flash; client fields do not decide these. If Look fails, a later attempt can submit another Look. Once Look saves, subsequent attempts reuse it and submit Speak; the real persistent four-submission budget remains authoritative. Success runs actual trust and certificate issuance. Results are machine outcomes with no faculty overrides. The temporary database is removed after the run.

`--repetitions N` repeats the same cases in alternating profile order. Caches are shared within the process. `orderInRun` and per-stage wall-clock durations are recorded; no cold/warm distinction is claimed. True cold measurements require fresh processes and separately labeled runs. A long case can reach the real ten-minute expiry, which is reported rather than extended.

`--probes` additionally calls the actual Speak scorer and unrestricted word service on the first original Speak capture, independently of full-flow prerequisites. Diagnostic media validation remains enforced; the word-only service does not require video. These probes save no fabricated Look, result, trust or certificate and are always marked `includedInAcceptance: false`. Legacy's optional diagnostic word is the same Vosk component for comparison; it does not become a legacy word policy or a full-flow legacy success.

`results.json`, `results.csv`, `diagnostics.csv`, `aggregate.csv` and `report.md` contain whitelisted outcomes, bounded measured transcripts/confidence, model/configuration versions, exact denominator counts and real timings. Diagnostic CSV rows explicitly exclude their evidence from acceptance. Stage records retain both a terminal reason (such as exhausted retries) and the underlying capture attempt reason. Dataset paths, raw media, embeddings, account credentials and OTPs are excluded. CSV cells beginning with formula characters are escaped. Output directories are exclusive to preserve prior evidence.

| Metric | Denominator and interpretation |
| --- | --- |
| Completion | All case runs; success means actual certificate issuance, which can record any risk label. |
| SAFE acceptance | All case runs; completion with a stored machine SAFE label. Also reported separately for known genuine cases. |
| Incorrect SAFE | All case runs explicitly labeled `safeExpected: false`; any stored machine SAFE outcome counts, including a later certificate failure. Unknown truth is excluded. Negative completed count is separate. |
| Genuine within two captures | Known genuine cases with `safeExpected: true`; SAFE completion by capture index <=2. Reports distinguish genuine completion from SAFE acceptance. |
| Retry case rate | All case runs; at least one unsuccessful capture response requests retry, excluding operational/setup failure. |
| Retry submission rate | Actual Look/Speak requests; failed retryable captures, including invalid uploads, over all capture submissions. It differs from the v2 spent Speak count. |
| Word exact match / verified | Only measured full-flow Speak word records. Legacy has no such measurement. Exact token agreement is distinct from confidence-qualified policy acceptance. Known agreement accuracy compares the measured token decision to explicit `wordMatch` truth. |
| Diagnostic words | Only independently measured word probes; separate verification and known token-agreement metrics. These cannot affect acceptance, completion or full-flow word metrics. |
| Processing time | Actual synchronous route wall-clock time from start to certificate/failure; stage times and completed-flow timing are separate. Excludes dataset loading, common enrollment, diagnostics and live device/browser/capture delay. Setup and common enrollment are measured separately. |

Every zero denominator yields a null rate and an explicit unavailable reason. Timing uses arithmetic mean, median and nearest-rank p95 with sample size. Repetitions are reported as case runs alongside unique-case counts; they never increase independent human sample size. Partial/failure timings cannot establish a complete-flow latency target. Confidence is model evidence, not calibrated identity probability. Use the per-case `split` and fixture category when interpreting results; this harness does not certify Task 24 readiness.
