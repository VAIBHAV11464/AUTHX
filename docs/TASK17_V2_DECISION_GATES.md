# Task 17 — v2 decision gates

Completed 2026-09-28 before Task 18 implementation. Legacy remains the default; no dependency/model installation, schema change, commit or push.

`decision_evidence.py` centralizes SAFE eligibility from server-persisted evidence, rather than inferring successful checks from scores. Newly measured Look/Speak save separate `lookGateEvidence`/`speakGateEvidence` records with policy version `v2-decision-gates-1`. No frames, landmarks or recordings are saved. Existing measurement/configuration snapshots remain separate and gain named YuNet/SFace model versions and quality settings.

| Required evidence | Initial rule |
| --- | --- |
| Look and Speak capture | Valid 8–90-frame recording, first frame <=500 ms, 2–4-second span and increasing finite timestamps; >=8 quality-approved relevant frames and >=80% quality coverage. Look uses pre-flash readiness; Speak uses its full clip. Speak also records valid finite audio, duration/rate and 0–250 ms software offset. Upload format/dimension bounds remain enforced before scoring. |
| Identity in each step | Independently valid unrounded cosine >=0.363; recorded stricter identity minima and stricter current configuration are respected. A lower configuration never relaxes the 0.363 floor. |
| Blink | Explicit completed bilateral open–closed–open from the existing pre-flash algorithm, >=1 cycle and >=8 measured samples. Persisted coverage must be >=80%, sample/cycle counts consistent, and gaps positive and <=150 ms. Existing geometry checks remain in that algorithm. |
| Flash | Explicit measured response from the existing algorithm, >=4 samples per window, >=150 ms span per window, gaps <=150 ms, finite delta/correlation. Strong, weak, negative and flat measured responses are usable. Score 25 is not a failed gate. |
| Word | Stored server challenge, unrestricted recognition, exactly one matching token/measured word, finite non-boolean confidence >=0.80 and the existing accepted word policy; never client word/flags. |
| Lips | Explicit usable aligned lip evidence, >=12 samples, >=80% coverage, gaps <=150 ms, finite correlation and mouth variance. Measured low correlation or still mouth remains usable; existing scores 25/20 still affect the voice weighting. |

Unknown versions, missing/malformed records, non-boolean flags, invalid counts/configuration, nonfinite measurements and insufficient coverage cannot pass. Displayable gate states are `passed`, `failed`, and `not_recorded`. Historical high scores are not retroactive evidence. No new strong-flash or high-lip-correlation requirement was added.

`fuse()` and the configuration retain their original arithmetic: face .45/blink .30/voice .25, acoustic .75/lip .25, flash adjustments +8/+3/0/-8, SAFE>=75 and SUSPICIOUS>=45. `fuse_v2()` first performs that calculation. If its outcome would be SAFE and any gate is ineligible, it caps trust at `min(74, SAFE_MIN-1)` and classifies that capped value using the existing thresholds. Already lower outcomes stay unchanged, including base and flash adjustment. Eligibility alone does not guarantee the weighted score reaches SAFE.

V2 trust reads the session's pinned profile, server word, stored cosines and detail JSON; client evidence/profile fields cannot substitute for them. Saving trust adds a versioned `machineDecision` snapshot (gates, eligibility, final score/label, base/adjustment and configuration) without erasing Look/Speak records. Current faculty label changes remain separate in meaning: they still modify the existing session label, and do not rerun measurements. Task 19's audit redesign is deferred.

New v2 certificate issuance requires a valid gated machine-decision snapshot as well as the Task 16 word evidence. A pre-gate trust value receives `evidence_required`; recalculate trust using the existing trust route first. The issuance service also enforces this prerequisite, so direct calls cannot bypass it. Certificates may record a SUSPICIOUS/DEEPFAKE outcome as before. Already-issued certificates return unchanged, even if current session evidence is absent. At this isolated checkpoint, certificate serialization and `block_hash()` are unchanged; additive certificate evidence belongs to Task 18.

## Checkpoint

Passed **12 focused gate tests +74 existing regressions**: profile 10, enrollment/matching 17, Speak identity 12, landmark evidence 19, challenge word/retries 16. Python compilation passed. `backups/task17-18/task17-checkpoint-result.json` records the five regression suites and the initial 11-test gate checkpoint; `task17-gates-final.log` records all 12 focused tests after adding corrupted-snapshot checks. `task17-manifest.json`/`task17-source.zip` preserve this isolated implementation checkpoint.

Focused checks cover each absent/failed/malformed gate with high compensating scores; raw identity boundaries; usable weak/flat flash and low/still-mouth lips; malformed capture timing/audio/configs; historical/unknown records; pinned profiles and ignored client evidence; saved machine/config snapshots; issuance prerequisites; unchanged issued certificates/chains; legacy behavior. Existing fixtures now explicitly supply accepted measured gate records when isolating other policies. A historical certificate test inserts an old immutable fixture directly rather than asking current issuance to bypass new prerequisites.

Initial logs are retained. Two initial gate assertions incorrectly classified delta/correlation -1 as malformed; corrected tests use invalid -2. The prior historical test's direct issuance shortcut was replaced with an explicit historical fixture. No enforcement was removed to pass these tests.

Preservation checks retain the real database and all 23 protected model/dependency/database file hashes. Tests use temporary databases, including existing read-only clone/migration checks; the real database is never initialized. Geometric thresholds and confidence remain provisional model evidence, not evaluated human accuracy. No live volunteers, hardware alignment, spoof evaluation or end-to-end latency measurement was performed. Task 18 follows this checkpoint; Tasks 19–24 remain deferred.
