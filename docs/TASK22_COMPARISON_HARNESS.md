# Task 22 — offline paired-profile comparison harness

Implemented after the reviewed Task 21 checkpoint, 2026-09-28. Scope ends before Task 23. Legacy remains the application default. No commit, push, deployment, model/dependency changes, volunteer recruitment or default enablement.

## Delivered and executable

`tools/comparison.py` runs original paired recordings through actual enrollment/session/Look/Speak/trust/certificate APIs in a fresh temporary SQLite database. It reports completion, machine SAFE acceptance/eligibility, incorrect SAFE with known truth, retry rates, measured word evidence and per-stage/total wall-clock time. JSON, CSV and readable Markdown outputs are exclusive, reproducible artifacts. No real AuthX app/database is initialized.

`tools/comparison_import.py` imports already recorded Look/Speak JSON into local assets without changing media bytes, timestamps or audio offset. `tools/comparison_demo.py` prepares four fully executable public/SAPI smoke cases. [Dataset/run/report documentation](COMPARISON_DATASET.md) specifies the contract, truth/provenance, retry sequence and later real-data workflow. Raw datasets remain in ignored `.runtime/`; no recordings or embeddings enter output summaries or the real database.

Run the prepared demo (use a fresh output directory):

```powershell
Set-Location 'D:\AI PROJECT'
.\.venv\Scripts\python.exe tools\comparison_demo.py --output .runtime\comparison-fixtures-new
.\.venv\Scripts\python.exe tools\comparison.py `
  .runtime\comparison-fixtures-new\manifest.json `
  --output .runtime\comparison-results\new-run --repetitions 2 --probes
```

The final observed run used `.runtime/comparison-fixtures-jpeg/manifest.json` and produced:

- `backups/task21-22/task22-demo-final/results.json`: versions, hashes, config, per-case/stage/diagnostic evidence, exact denominators and actual times.
- `backups/task21-22/task22-demo-final/results.csv`: flattened whitelisted full-flow outcomes.
- `backups/task21-22/task22-demo-final/report.md`: readable aggregate.
- `backups/task21-22/task22-demo-final.log`: actual unmocked native inference log.

The final readable/exported report is `backups/task21-22/task22-observed-report/`: `results.json`, `results.csv`, `diagnostics.csv`, `aggregate.csv` and `report.md`. It formats the retained native measurement without changing any outcome or timing. Its formatting provenance pins the original result hash, measured source archive (`task22-native-source.zip`) and final formatter hash. The original native artifacts remain unchanged.

## Pairing and actual processing

Both profiles receive identical original image/WAV bytes, frame timestamps, audio offset, common enrollment and server challenge/flash timing. A fingerprint covers these inputs; the driver verifies they were not mutated. The isolated server's existing word pool is constrained to the recorded challenge for repeatability. Vosk still uses its unrestricted local model, with no expected-word grammar, threshold changes or invented recognition.

The common enrollment can be a legacy single-image API enrollment or an already compatible private local embedding. The native demo actually enrolled the same public portrait once through YuNet/SFace; both profiles use that exact vector. This deliberately holds enrollment constant and does not compare enrollment algorithms. The vector is used only in the temporary database, never exported.

Every run gets a new profile-pinned session. Look/Speak use the current real upload parser, quality/identity/liveness/lip/word policies. A failed Look can retry with a later original capture; a saved Look is reused for Speak retries. The real four-submission Speak budget, generation/lifecycle behavior, trust gates and atomic certificate issuance remain authoritative. Machine labels are read separately from effective labels; the harness applies no faculty overrides. Any route exception is an operational failure with its exception class, never an exported secret-bearing exception message or capture retry.

`--probes` runs independent actual Speak/word component diagnostics when the full flow is blocked. It never inserts a fabricated Look, gate, trust or certificate, and every diagnostic is explicitly excluded from acceptance/full-flow metrics. Legacy has no challenge-word policy; its optional word diagnostic is a separate Vosk measurement. Known/unknown truth, outcome categories and splits remain explicit per case.

## Observed public/synthetic smoke results

**Four unique cases, two repetitions per profile: eight case runs per profile, sixteen total.** The inputs are a repeated static public portrait on a declared synthetic 50 ms schedule, with local Microsoft David Desktop SAPI audio (`amber`, `bridge`, `say amber`), plus a duplicated Look timestamp failure case. These are not live camera recordings or measured hardware timestamps. The source portrait and SAPI WAV files were read only; the demo preparation scales/compresses the portrait once using browser JPEG settings and silence-pads short WAVs once to three seconds. No original fixture was replaced.

| Case | Full legacy flow | Full v2 flow | Independent v2 Speak / word measurement |
| --- | --- | --- | --- |
| Static amber | `no_blink` | `no_blink` | Accepts `amber`, measured confidence 1.0. |
| Static bridge against amber | `no_blink` | `no_blink` | Rejects `wrong_word`; transcript `bridge`, measured confidence 1.0. |
| Static phrase against amber | `no_blink` | `no_blink` | Rejects `ambiguous_word`; transcript `say amber`, no single matched confidence. |
| Duplicate Look timestamp | `no_blink` | `bad_timestamps` | Its independently valid amber Speak recording accepts; this cannot complete rejected Look. |

The legacy Speak component succeeds on these valid audio/video clips without measuring a challenge word. The separate optional Vosk word diagnostic produces the same token/word-policy outcomes on both sides. Policy outcomes repeated identically for all four cases/profile pairs.

| Aggregate (case runs, including repetitions) | Legacy | V2 |
| --- | ---: | ---: |
| Complete verification / SAFE acceptance | 0/8 / 0/8 | 0/8 / 0/8 |
| Retry-requested cases / capture submissions | 8/8 / 8/8 | 8/8 / 8/8 |
| Full-flow measured words | 0 | 0 |
| Independent word probes verified | 4/8 | 4/8 |
| Independent token agreement against known word truth | 8/8 | 8/8 |
| Known genuine cases / known negative SAFE truth | 0 / 0 | 0 / 0 |
| Mean processing through failure (n=8) | 2.5900 s | 2.5784 s |
| Median processing through failure (n=8) | 2.5690 s | 2.8778 s |
| Nearest-rank p95 through failure (n=8) | 2.7043 s | 5.9672 s |

Genuine acceptance, genuine completion within two captures, incorrect SAFE and completed-flow latency are **unavailable**, with null values and exact reasons. The static smoke cases have unknown biometric SAFE truth; they are not counted as genuine/negative volunteer examples. The word truth is known from synthesis, so independent agreement can be reported separately. Eight repeats do not become eight independent recordings or human subjects. Model confidence 1.0 is not calibrated identity probability or held-out recognition accuracy.

Timers cover synchronous test-client routes from start to failure/certificate, including request decoding, native processing and persistence where reached. Dataset loading, common enrollment, diagnostics and actual capture/device/browser delays are excluded. Common enrollment separately took 0.3970 s. Per-stage/diagnostic timings, sample counts and versions are in JSON. Profile order alternates and model caches are shared; cold/warm timing is not isolated. The v2 pooled mean includes fast timestamp rejection, and neither pooled mean establishes relative complete-flow speed. No certificate was issued in this native smoke run.

The initial lossless PNG demo exceeded the existing 8 MiB body limit and revealed a probe boundary-handling gap. It was retained as initial evidence; the driver now handles the real 413 bound for its Speak diagnostics. A new JPEG dataset used the browser's normal encoding, without relaxing any application limit. Initial harness tests also identified a test-only saved-Look fixture missing API fields; the fixture was corrected. Application enforcement was not changed for Task 22.

## Verification and preservation

`tests/comparison_harness.py` covers paired original bytes/timestamps/enrollment, pinned server inputs after global changes, real route rejection without capture repair, retry counts and saved-Look reuse, known/unknown/zero-denominator metrics, incorrect machine SAFE even if later certification fails, genuine real timers/percentile method, repeatable policy outcomes, temporary DB/config restoration, exclusive outputs, safe CSV/allowlisted output, missing assets/schema/consent, setup failures without invented timing, operational error secrecy, and lossless upload import. Controlled scorers isolate these integration rules; they are distinct from the actual unmocked native demo above.

The focused recheck `backups/task21-22/task22-reviewed-result.json` passed **42 smoke checks, 68 Python tests, zero skips and compilation**: profiles10, challenge16, atomic14, failures14 and harness14. The final fourteen-case harness suite then passed again after strengthening exhaustion/attempt-reason reporting and adding diagnostic/aggregate CSVs; `task22-final-harness.log` is authoritative for those final reporting changes. It verifies the importer preserves exact media/timing/offset and that six supplied Speak captures stop at the actual four-submission limit. The full Task 21 checkpoint remains 42 smoke checks, 172 Python tests, zero skips, five Node simulations, compilation/eight JS syntax checks/pip check. Across all distinct Python suites there are **186 unique cases**; repeated runs are not added to that count. `backups/task21-22/result.json` is the final reviewed batch summary.

`backups/task21-22/after-source.zip`, `after-manifest.json`, final audit/result manifests and the read-only original SQLite backup preserve the final source and exact protected inventories. Every original table row, issued score JSON byte string/hash/link/time and all 23 protected database/model/dependency hashes match. Original fusion, legacy Look/Speak and certificate hash algorithms retain their syntax trees; legacy serializer example bytes match. The real DB hash is `ef2a8941eea53701388d1b593b755a2aee49252cac6d62b89fb0acb1d4dd279b`.

No Task 23 dataset exists in this batch: no live volunteers, tuning/evaluation split, two-camera/dim-lighting study, wrong-person/photo/screen-replay validation, accent coverage or complete-flow reference-laptop latency study. The harness can process later authorized recordings with known labels; it does not certify the Task 24 targets. MediaPipe's upstream metrics attempt still appears in the native log and fails without preventing local inference; AuthX downloads no models during inference. **Stop before Task 23; keep legacy default. No commit or push.**
