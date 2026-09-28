# Task 24 — retain legacy; authentic validation evidence unavailable

Decision on 2026-09-28: **retain `VERIFICATION_PROFILE=legacy`**. The v2 default was not enabled. Task 23's human evaluation remains pending. The machine-readable [readiness decision](../backups/task23-24/pending-reviewed/readiness.json) and [readable result](../backups/task23-24/pending-reviewed/readiness.md) record the actual zero sample sizes and unavailable metrics. The original Task 24 conditional enablement has not been satisfied.

The original roadmap targets retain their meaning:

| Target | Authentic observed sample | Current result |
| --- | --- | --- |
| At least 90% genuine completion within two attempts | 0 held-out genuine trials | Unavailable; completion/SAFE completion are both null. |
| No SAFE outcomes on held-out wrong-person/wrong-word cases | 0 wrong-person and 0 wrong-word trials | Unavailable; zero observations is not a zero-SAFE validation pass. |
| 95% of scoring attempts within eight seconds on the reference laptop | 0 declared reference-laptop full-scoring attempts | Unavailable; no hardware benchmark occurred. |

## Concrete decision behavior

`tools/volunteer_study.py` makes a reviewable held-out decision from the registered/frozen authentic dataset and actual paired API report. It requires at least ten consenting unique volunteers, two declared camera identities, complete predeclared normal/dim/genuine/attack coverage for evaluation subjects, separate tuning/source/enrollment identities, confirmed reference runtime and untouched scoring/model/configuration provenance. Missing known truth/recordings/planned conditions or consent is not a pass. Each named attack category must have observed evaluation outcomes. Photo/screen-replay results appear explicitly in the same report.

One attempt is a fresh server session with up to four actual Speak submissions. One genuine trial is a subject/camera/lighting/category condition with up to two authentic sessions; repeated files/runs do not enlarge its denominator. Certificate completion and SAFE certificate completion are reported separately. An unsafe certificate can complete the flow; it is never represented as successful SAFE verification. Incorrect SAFE uses stored machine outcomes independent of effective/faculty labels and can count even without certificate completion.

The proposed timing protocol is declared before collection in [the protocol](VOLUNTEER_STUDY_PROTOCOL.md): **every genuine held-out session attempt** forms the predeclared complete-scoring benchmark, selected before model outcomes. Its time is the sum of actual synchronous Look, all Speak submissions, trust and certificate route processing on the identified reference laptop. Initial loads inside the routes remain included; capture/human pauses, enrollment, input I/O, session creation, external transport and component diagnostics are excluded explicitly. Failed/incomplete genuine pipelines retain a missing benchmark sample, so faster partial rejections cannot establish this target. All attack/early-failure terminal times are reported separately. Nearest-rank p95 and the actual proportion <=8 seconds are both retained. Reference-runtime confirmation is an operator declaration plus a runtime consistency fingerprint; software does not invent or attest laptop hardware.

Task 22's repeated public/synthetic files, partial Look failures, SAPI word probes and fixture clocks cannot enter the authentic completion/incorrect-SAFE/latency denominators. A common enrollment vector provides paired verification comparability and does not itself assess the two enrollment algorithms. Actual v2 five-image enrollment attempts and failures are retained separately; real legacy enrollment/UI usability needs separate observation when assessing that limitation.

If all actual criteria and study-integrity checks pass, the report returns `eligible_for_v2`. The runner writes evidence and the reviewable decision; it does **not** silently change a selector. The authorized Task 24 default change is to be implemented only after verifying that actual frozen evidence, with focused compatibility and rollback checks. Existing profile-pinned sessions and immutable historical records must survive any later change. When a target fails or evidence is unavailable, the report returns `retain_legacy` with observed numerators/denominators and reasons. No threshold was relaxed or tuned in this batch.

## Current checkpoint

Evaluation volunteers: **0**. Tuning volunteers: **0**. Original human submissions: **0**. Confirmed cameras: **0**. Confirmed reference-laptop timing samples: **0**. All three criterion rates are **null**. `defaultChanged` and `task23HumanEvaluationComplete` are **false**. No current/default application configuration was changed; session pinning and history are preserved.

Relevant checks and protected-original/source audits are recorded in [Task 23's report](TASK23_VOLUNTEER_EVALUATION.md) and `backups/task23-24/`. These policy/integration tests verify decision behavior and data integrity, not human performance. No commit, push, deployment, external outreach or production work was performed. To resolve the conditional enablement, actual consented held-out recordings, device identities and the declared reference-laptop benchmark are still required.
