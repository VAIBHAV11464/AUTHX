# AUTHX volunteer collection and evaluation protocol

This is executable preparation for Tasks 23–24. It is not completed consent or human validation. All collection is local, initiated by participants/operator actions, and stored under ignored `.runtime/`. No recruitment messages are sent. Use the existing interpreter; no model or package changes are needed.

## Declare the study before collection

The original roadmap requires at least ten consenting volunteers, two cameras, normal/dim lighting, genuine attempts and wrong-person/wrong-word/photo/screen-replay attempts, with tuning and evaluation subjects separated. Recommended allocation is **12 volunteers: two tuning and ten evaluation**. Ten total is the roadmap minimum; report the actual tuning/evaluation counts rather than claiming this recommendation was obtained. Each collected split needs two people for wrong-person sources. If thresholds are not tuned, an evaluation-only study is permitted; declare that no tuning occurred.

One **trial** is one enrolled anonymous subject × camera × lighting × category. One **attempt** is a fresh server session beginning at session start. A genuine trial allows up to two such authentic sessions. Each session retains its real initial Speak submission plus three retries (four total); Speak retries do not become fresh sessions. The wizard's Look retry starts a new server session. A third session is blocked by the collector. Keep every failed or interrupted trial in the collection log. Never repeat a file and call it another human attempt.

The genuine completion target is certificate-flow completion within two fresh sessions. Report **SAFE certificate completion separately**: a SUSPICIOUS/DEEPFAKE certificate completes the flow but does not prove SAFE verification. Incorrect SAFE uses the stored **machine** label, even when certificate issuance fails; faculty labels cannot replace it.

The proposed full-scoring benchmark population is **all predeclared genuine evaluation session attempts**, selected by study conditions before outcomes. Measure the sum of Look, every actually submitted Speak, trust and certificate synchronous route elapsed times, using `perf_counter` on the identified reference laptop. Include initial model-loading costs incurred inside these routes and every genuine session. Exclude enrollment, dataset I/O, recording time, human pauses, session creation, diagnostics, and transport outside the test client. Report those boundaries. An incomplete scoring pipeline remains an unavailable benchmark sample; its faster partial failure time cannot establish the eight-second target. Report all attack/failure terminal processing times separately. This population/boundary is explicitly declared before collection; the original target wording is retained in Task 24's report. If a different hardware/timing target is intended, agree it **before collection** and update the protocol, implementation and tests together; do not relabel old timing afterwards.

Freeze participant splits, camera identities, planned conditions and scoring source/config/models before opening the evaluation collector. If tuning changes scoring/model/configuration after evaluation capture, the loader rejects those captures as untouched evaluation; collect fresh held-out evidence. Do not tune on evaluation results. A different case ID, source identity alias or enrollment name is not a different person. The private identity register assigns one persistent random identity key per human across all roles/splits; do not hash names or generate a second key for the same person.

## Private consent and registry

Copy [the consent/checklist template](VOLUNTEER_CONSENT_TEMPLATE.md) into private storage. Have the operator review actual signed permission before setting `consentReviewed: true`. A filled JSON flag or template is not obtained consent. Maintain real names/contact/signatures separately from anonymous recordings and reports. Confirm recording permission for every enrollment and source person; photo/screen sources also need replay permission. Record withdrawal and exclude withdrawn data before evaluation. The operator must set an agreed retention/delete date and storage access list.

Initialize a fresh private registry:

```powershell
.\.venv\Scripts\python.exe tools\volunteer_study.py init --output .runtime\my-volunteer-study
.\.venv\Scripts\python.exe tools\volunteer_study.py runtime-fingerprint
```

Edit `.runtime/my-volunteer-study/study.json`. `subjects` entries have `id`, immutable `split` (`tuning`/`evaluation`), `identityKeySha256` (SHA256 of the persistent random private key), relative `consentDocument`, `consentSha256`, UTC `consentRecordedAt`, `consentReviewed`, `withdrawn`, `recordingPermitted`, and `replayPermitted`. Use anonymous IDs such as `V001`. Hash the actual private signed file; do not use the example template checksum as consent. An operator must check that each document covers its subject; software checks file integrity and declarations, not signatures or real identity.

Declare the reference laptop with stable anonymous `id`, `specification` (CPU/RAM/OS/power mode/browser description), `confirmedThisMachine: true`, and the command's `runtimeFingerprintSha256`. This fingerprint is an OS/Python/processor consistency check, not hardware attestation. Keep a private device inventory; no serial number or username is exported. Record power mode, background workload and model-cache/order conditions in the operator condition log.

Inventory cameras on the same browser, loopback origin and port to be used for collection:

```powershell
.\.venv\Scripts\python.exe tools\study_capture.py cameras --port 5017
```

Open the printed loopback URL and click **Allow camera labels**. This action briefly opens a video device solely to expose labels, then stops its tracks. No images or audio are saved. Copy the two relevant camera records (`id`, `description`, `deviceKeySha256`) into `cameras`. The key hashes the browser's device ID; it depends on origin/browser permissions. Confirm the cameras are physically distinct, not two virtual labels for the same source. Device reset/origin change requires a new explicit inventory and protocol pin. Stop this inventory server before collection. Do not start devices around bystanders.

The planned matrix is generated from the consenting subject registry. Every subject has two cameras × two lighting conditions × five categories = 20 trials. Wrong-person sources rotate to another subject **in the same split**; an enrollment subject and any Look/Speak/replay source must stay in that split. Review sources before declaring:

```powershell
.\.venv\Scripts\python.exe tools\volunteer_study.py plan .runtime\my-volunteer-study\study.json --output .runtime\my-volunteer-study\study-planned.json --declare-protocol
.\.venv\Scripts\python.exe tools\volunteer_study.py pin-protocol .runtime\my-volunteer-study\study-planned.json --output .runtime\my-volunteer-study\protocol-freeze.json
```

The declaration flag records the reviewed protocol before collection. Planning/pinning require actual reviewed private subject records; the empty prepared template cannot pass. Planning output and pin are exclusive. No volunteers, consent, camera identities or laptop specifications have been filled in the delivered template.

## Collection matrix and independent truth

| Category | Known condition and instruction |
| --- | --- |
| genuine | Enrolled person performs Look and says exactly the displayed server word. |
| wrong_person | Enroll primary person, then the separately consenting same-split source performs Look and Speak; also log any person switch between the two steps. Say the correct displayed word. |
| wrong_word | Enrolled person performs Look; say a known different single word on **every** Speak submission. Record the actual intended/spoken word independently. Do not change to the correct word within this case. |
| photo | Enroll primary person, then present the consented photo source. Record print/display method, geometry and any live voice source in the private condition log. Do not add unregistered people. |
| screen_replay | Enroll primary person, then present a consented source recording on a screen. Log screen/playback method, audio source and source identities. Preserve the challenge mismatch or matching conditions as observed. |

Use `normal`/`dim` lighting established by the operator before scoring. Log room setup and measured lux when a real meter exists; otherwise declare it qualitative. Do not fabricate lux or select only quality-passing captures. Keep camera position/distance, audio background and operational errors in the private condition log. Photo/screen-replay `wordMatch` defaults to **null**; independently declare true/false only when the source's spoken-word relationship is known before scoring. Unknown word truth stays outside agreement-accuracy denominators while measured recognition/verification remains reported. Incorrect instructions, bystanders or unknown spoken-word compliance must be recorded and resolved by independent observation/listening before claiming known truth; model outcomes never determine truth. If a submitted condition differs, retain its original media as an operational/deviation record, keep its failure visible in the planned-trial accounting and recollect the planned trial as allowed by the declared attempt limit. Do not silently relabel it or omit it to pass.

For each predeclared trial, use a fresh output directory:

```powershell
.\.venv\Scripts\python.exe tools\study_capture.py collect .runtime\my-volunteer-study\study-planned.json --protocol-freeze .runtime\my-volunteer-study\protocol-freeze.json --trial T0001 --output .runtime\my-volunteer-study\captures\T0001 --port 5017
```

The launcher checks the precollection pin before creating an app. It sets the database to a fresh temporary file **before** the Flask factory, disables SMTP and uses a fresh private signing key. It does not read accounts/enrollments from the real DB. The printed URL contains a temporary local access key; open it privately and do not publish it.

Review the trial banner, actual signed consent and enrolled/source people. The participant clicks **I agree to recording for this trial**, then **Allow camera**. Choose the declared camera in the existing selector. Browser camera hashes are checked before uploads. Capture **Enroll** with the primary enrollment subject (five real images), then present the assigned genuine/attack source. Re-enrollment is blocked once a session has started so all exported sessions retain their original enrollment vector. Follow the existing **Look → Speak → Certificate** controls and budget. For a genuine failure, use a second Look session if needed; do not omit the first failed session. Stop after two sessions. Every original submission body, failure and server challenge/flash timing is preserved without interpolation or resampling by the exporter.

Click **End collection and stop devices** once capture/scoring finishes, then close the tab and stop the server with Ctrl+C. The end action saves an immutable private ledger and stops camera/microphone tracks. The active-capture guard asks the operator to wait for the existing recording to finish. Interrupted collection retains original upload files but lacks a verified terminal ledger and cannot become a completed trial by invention. Log the interruption and recollect with a fresh directory. No device has been opened for this delivered batch.

The wizard produces authentic performance/sample-clock timestamps through its existing v2 capture modules. These are software timing measurements, not proof of physical A/V synchronization. The server stores its own selected word/flash/session times; the exporter cannot replace them.

## Lossless export and paired run

Export every terminal trial:

```powershell
.\.venv\Scripts\python.exe tools\study_capture.py export .runtime\my-volunteer-study\captures\T0001 --output .runtime\my-volunteer-study\exports\T0001
```

Original JSON/upload/media bytes, timestamps, audio offset, protocol pin and ledger remain private. The dataset uses exact ordered `submissions` so a Look-only failure has no invented Speak. A completed session contains its actual Speak retries. The paired harness holds one common **actually captured v2 enrollment vector** fixed; this compares verification profiles on identical inputs, not their enrollment algorithms. The actual five-image enrollment upload and enrollment failures are retained and reported separately. Legacy UI/enrollment usability and physical synchronization remain additional limitations unless separately assessed with real data.

Assemble all private exports into one dataset, preserving the registry's signed consent references beside the ready registry:

```powershell
$trialExports = Get-ChildItem .runtime\my-volunteer-study\exports -Directory | ForEach-Object FullName
.\.venv\Scripts\python.exe tools\study_capture.py assemble .runtime\my-volunteer-study\study-planned.json --exports $trialExports --output .runtime\my-volunteer-study\dataset --ready-study .runtime\my-volunteer-study\study-ready.json
.\.venv\Scripts\python.exe tools\volunteer_study.py validate .runtime\my-volunteer-study\study-ready.json
.\.venv\Scripts\python.exe tools\volunteer_study.py freeze .runtime\my-volunteer-study\study-ready.json --output .runtime\my-volunteer-study\evaluation-freeze.json
.\.venv\Scripts\python.exe tools\volunteer_study.py run .runtime\my-volunteer-study\study-ready.json --freeze .runtime\my-volunteer-study\evaluation-freeze.json --output .runtime\my-volunteer-study\evaluation-run-01
```

`validate` exits 2 for unavailable readiness, with anonymous reasons. Freeze pins scoring source/config/model/dependency hashes, signed consent digests, subject splits, independently recorded truth, original media/challenge inputs and the current runtime before the paired evaluation. It is checked again after the run. The runner uses one repetition, temporary sessions/databases and no component probes; original route failures and four-Speak limits remain authoritative. Missing planned trials cannot disappear from readiness merely because the recorded subset performs well. Every normal output contains only bounded anonymous outcomes/metrics/configuration/provenance; embeddings, original media, private consent and absolute dataset paths stay in private datasets.

Read `results.json`/CSV/Markdown for all paired cases and `decision/readiness.json`/Markdown for held-out criteria, subject/camera/lighting/category/matrix results, separate SAFE/flow completion, retries, measured word agreement, actual enrollment collection and timing sample counts. Tuning/demo/diagnostic rows and repetitions cannot inflate held-out denominators. Unique volunteers, session attempts and unique submissions are different counts. A failed/insufficient study returns **retain_legacy**; missing evidence is null, never an inferred pass. The study runner writes the reviewable decision and does not change the app selector. Any eligible result must be verified against the actual frozen evidence before conditionally changing the default in the authorized Task 24 work, with compatibility/rollback checks and no deployment.
