# Task 18 — evidence summaries

Completed 2026-09-28 after the isolated Task 17 checkpoint. Scope is Tasks 17–18 only. Legacy remains the default; no dependencies, models, schema, capture timing, roles or layout design were changed. No commit or push.

## Additive API contract

Authenticated session start, Look, Speak, trust and certificate responses, plus authorized faculty session detail, gain optional fields. Every existing response field remains. Enrollment, standalone voice, session lists, admin actions and faculty override/reopen contracts remain unchanged.

| Optional field | Meaning |
| --- | --- |
| `verificationVersion` | The pinned session profile (`legacy`/`v2`). Issued certificate responses use only the issued snapshot; old snapshots without a profile say `not_recorded`. No profile is inferred from a mutable current session for a historical certificate. |
| `evidence` | Policy version; passed/failed/not-recorded checks; bounded transcript/word confidences and speech provenance; separate Look/Speak model/measurement/quality configurations; gate/decision configurations; saved machine result; short readable `summary` and `lines`. |
| `retryable` | For general session summaries, an unsaved capture step exists and the v2 budget remains (legacy has its existing behavior). Look success means Speak remains available. Speak/trust/certificate success has no further capture retry. Existing explicit Task 16 failure flags retain their more specific retry/wait meaning and are never overwritten. |

The blueprint's response hook adds these fields only after authentication and ownership/role checks. Unauthorized/forbidden/not-found responses do not reveal evidence. Nothing submitted by a client becomes the authoritative evidence or profile. The hook reads existing records without saving scores, labels or new rows.

The word summary selects accepted saved Speak evidence, otherwise the last attempted speech record, clearly labeled `Last word attempt`. It retains only bounded text (transcript <=1000 characters, word <=64, <=16 word records), finite confidences and named version/hash/configuration fields. No recordings, embeddings, password/OTP data or arbitrary detail JSON are returned. Existing failed scorer detail strings remain supported.

## Views and machine versus faculty meaning

Existing student results and faculty details gain one compact paragraph, within their existing panels and styling. `evidence.js` writes only `textContent`; summaries/transcripts never become HTML. Fresh Look and faculty send-back clear the previous visible summary. Missing optional fields are handled gracefully by older/legacy responses. The certificate uses normal Jinja autoescaping.

Checks reflect saved evidence; a saved `machineDecision` is shown independently of the session's current `riskLabel`. Faculty actions still change that existing label, and do not change the machine snapshot or imply its failed gates passed. The summary explicitly explains this. No override audit table or new override policy was implemented; that is Task 19.

Historical v2 records without the new measurement records show `not recorded`. Their existing stored label is retained on display. Legacy records explain that v2 checks were not required; the app does not invent a separate historical machine-decision snapshot.

## Immutable certificate approach

For newly issued **v2** certificates only, `_score_json()` adds `verificationVersion` and the bounded `evidence` snapshot. It uses the saved machine decision plus the step/speech/model/configuration records available at issuance. The resulting score JSON is frozen and hashed once. The existing `block_hash(prev_hash, session_id, trust_score, created_at, score_json)` concatenation/SHA-256 algorithm is unchanged. No separate mutable lookup is used to present a certificate's evidence.

Legacy new issuance retains its original score JSON fields. Every historical stored score JSON, hash and previous-hash link remains unchanged. Older certificate views say `Evidence snapshot not recorded for this historical or legacy certificate.` Repeated issuance returns the same certificate, evidence and hash even after current-session measurements, word, faculty label or global configuration change. Revocation/chain handling remains existing behavior. Atomic previous-hash read/insert overhaul remains Task 20.

A valid gated machine snapshot remains required for new v2 issuance. Historical pre-gate trust with valid word evidence receives `evidence_required` until the existing trust route calculates/stores a gated result. Certificates can still record SUSPICIOUS/DEEPFAKE outcomes. A faculty-changed stored label may differ from the machine outcome; both are disclosed in the new issued snapshot.

## Checks and preservation

Passed **42 smoke checks +127 Python regression/runtime tests**: profile10, uploads/quality17, enrollment/matching17, Speak identity12, landmark runtime6, timing4, landmark evidence19, offline speech5, challenge word16, decision gates12, summaries9. Four Node simulations passed (enrollment, timing, speech retries, evidence display), along with Python compilation, three changed-JS syntax checks and `pip check`.

Nine summary tests verify exact additive start/Look/Speak/trust/certificate field sets, real synthetic geometry/flash flow with speech isolated, unchanged historical labels on display, machine/faculty distinction, frozen issued evidence/configuration across mutable session changes, legacy bytes/hash format, historical certificate chains, transcript escaping/bounds/nonfinite confidence, retry budget/setup failures, authorization/no private data, and read-only display across global profile/config changes. The Node summary test runs the actual wizard/faculty renderer with a text-only DOM sink, optional-field fallback and fresh/reopen reset. Existing Speak contract assertions were intentionally extended to include precisely the three optional fields.

The initial summary run exposed a test-only module/function naming collision, fixed before the passing checks. Final review also tightened persisted blink coverage/gap consistency and machine snapshot numeric/label consistency, with focused malformed-record cases. Affected gate/profile/identity/landmark/word suites were rechecked; exact commands, exits and logs are recorded in `backups/task17-18/result.json`.

Static fixture versions of all three existing views were rendered using a temporary database, served on loopback, and inspected in the in-app browser. Their summaries wrap within the existing panels without covering metric tiles. The fixture script is `backups/task17-18/preview.py`; it removes active scripts and remote font loads for layout inspection and does not start the real application database. Automated Node tests independently exercise active renderer behavior. This is layout QA, not a live camera/microphone test.

`before-source.zip`, the read-only SQLite backup, `before-manifest.json`, isolated Task17 snapshot, `after-source.zip`/`after-manifest.json` and final results are in `backups/task17-18/`. The real `authx.db` SHA-256 remains `ef2a8941eea53701388d1b593b755a2aee49252cac6d62b89fb0acb1d4dd279b`; all model/dependency preservation hashes match. Tests only initialize temporary databases. No accounts, enrollments, historical sessions or issued certificates were rewritten.

Limits remain the same: fixtures/heuristics do not establish human accuracy, spoof resistance, all-word/accent performance, hardware synchronization or laptop end-to-end latency. No volunteer study or default enablement was performed. MediaPipe's documented upstream metrics attempts remain disclosed in Task 10; local inference never downloads a model.

**Tasks 17–18 complete. Stop before Task 19. No commit or push.**
