# Task 16 — challenge word and three Speak retries

Implemented 2026-09-28 after the isolated Task 15 checkpoint passed. Tasks 15–16 only; Task 17 has not started. Legacy remains the default. No commit or push was performed.

## Acceptance rule

V2 session Speak verifies `sessions.challenge_word`, supplied by the server to the profile. Client word/transcript/confidence/profile fields cannot select or override it. Vosk uses the complete small English model without a grammar restricted to the expected word. Standalone voice and enrollment retain their existing behavior.

Case-fold the transcript and tokenize with Python Unicode `\w+`, treating punctuation/whitespace as separators. Require exactly one token equal to the normalized stored challenge, plus exactly one measured word record with the same token. Its unrounded confidence must be numeric, finite, non-boolean, in [0,1], and **>= 0.80**. Quotes/case/terminal punctuation normalize; extra or repeated words and possessives yield multiple tokens and fail. `amber123` remains a different token. Invalid configuration or a minimum below 0.80 produces a setup failure, never a silent threshold reduction. Vosk confidence is model evidence, not a calibrated probability of identity or spoof resistance.

Failures are explicit: `word_not_heard`, `wrong_word`, `ambiguous_word`, `word_confidence_low`, `word_confidence_missing`. Missing/disagreeing word records, missing/nonnumeric/nonfinite/boolean/impossible confidence and multiword ambiguity cannot pass. No closest-word guessing is used.

Word verification follows existing face-quality, Speak identity and lip checks. A usable identity mismatch can save measured voice/identity when the word passes, retaining Task 9's SUSPICIOUS cap. Wrong/unclear words leave successful Speak unset and Look intact. Acoustic/lip/risk weights and thresholds are unchanged.

## Retry semantics

“Three Speak retries” means **one initial submission plus three retries: four total valid submitted attempts**. The fourth may succeed; failure requires a fresh session and another Look. Start chooses a new server challenge randomly, which may happen to repeat the same word.

| Outcome | Budget behavior |
| --- | --- |
| Authorization/ownership/not-found, missing Look, already-saved Speak | No charge. |
| Malformed/oversized upload, invalid timing, capture interruption detected before submission | No charge. |
| Valid submitted capture with unusable face/lip evidence, silence, empty/wrong/ambiguous/low-confidence word | One attempt consumed; successful Speak stays unset. |
| Successful Speak | One attempt consumed; ordinary Speak lock applies. |
| Speech/face/landmark setup or native failure, invalid speech configuration, unexpected scoring exception | No net charge; release/refund any reservation. |
| Missing/invalid enrollment or invalid model embedding | No net charge; existing 422 guidance. |
| Duplicate while scoring | 409 `speak_in_progress`, no extra charge. |
| Worker dies after reservation | Submitted attempt stays spent; recover its lease after 120 seconds. |

Additive session columns are `speak_attempts` (historical default zero), nullable `speak_token`, `speak_reserved_at`, and `speak_last_evidence`. No recognition is invented for historical sessions. Tests preserve all original fields/rows/certificate hashes and repeat migration.

SQLite `BEGIN IMMEDIATE` reserves one attempt before scoring. A persistent token serializes competing submissions across processes. Finishing checks the token and original Look result ID, then saves successful voice/evidence and releases the slot in one transaction. A stale/superseded worker cannot save or refund a newer reservation. The 120-second lease recovers a dead worker while retaining its spent attempt; it is not Task 19's session expiry.

Reopen cannot reset the budget or erase last evidence. It returns 409 during an active reservation or after exhaustion; before exhaustion it retains the count. These are the lifecycle changes required for Task 16. Certified-session rotation, broader lifecycle fixes and override auditing remain Task 19.

Failed scoring responses add `attemptsUsed`, `attemptsRemaining`, `retryable`, `freshSessionRequired` and `attemptReason` when available. Fourth failure sets `reason=speak_attempts_exhausted`; `attemptReason` retains the actual failure. Later submissions return 409. Successful response fields remain the original set.

## Evidence, history and wizard

Successful `detail_json.speech` stores bounded transcript/word confidences, expected server word, acceptance/matched confidence/minimum, word policy version, Vosk/model/integrity version, recognizer rate and unrestricted-grammar flag. The session stores only the latest submitted outcome at `speak_last_evidence`, including failed word evidence. Failed steps do not change Look or save voice scores. No recordings are persisted. Separate `lookMeasurement`/`speakMeasurement` snapshots remain intact; speech has its own snapshot.

New v2 trust calculations and new certificate issuance require valid stored word evidence. Historical v2 voice scores without recognition cannot silently proceed. Already-issued certificates remain retrievable/reissuable with identical snapshots/hashes; the certificate serialization/hash code is unchanged. Legacy retains prior behavior. Comprehensive SAFE gates and evidence summary views remain Tasks 17–18.

The existing wizard shows word-specific guidance and remaining attempts in its status area. Failed words do not request trust/certificates. Setup failures leave Speak available. Exhaustion hides the stale word/Speak control and directs the user to the existing Look control for a fresh session. Historical saved Speak with no word evidence also receives fresh-session guidance.

## Checks and limits

All 42 smoke checks and 106 regression/runtime tests passed, together with three Node simulations, Python compilation, JavaScript syntax and `pip check`. Final results are in `backups/task15-16/result.json`; individual initial and repaired check logs are preserved. All database tests use temporary databases, including a read-only clone of the real database for migration. SMTP is disabled only in test subprocesses.

`tests/challenge_word.py` has 16 tests covering confidence boundaries, normalization/ambiguity, missing/invalid confidence, server authority, snapshot preservation, initial plus three retries/fourth success, restart/reopen/fresh session, non-consuming failures, concurrent API/SQLite reservation, crash/stale worker recovery, historical evidence/certificates, legacy/standalone, migration and minimum enforcement.

Actual offline Vosk recognition also runs through the word policy/API with three synthetic fixtures (face/lip scoring isolated): `amber` accepts at confidence 1.0; `bridge` against amber rejects; `say amber` rejects as ambiguous. Audio comes from installed Microsoft David Desktop English (United States) SAPI, generated locally in ignored `.runtime/fixtures/`. The generation script is `backups/task15-16/synthetic_fixtures.ps1`. Short fixtures are silence-padded to three seconds for upload validation. `synthetic-api-inference.json` contains measured evidence. Task 15 also recognizes public upstream audio with Python network connections blocked during inference.

The Node wizard simulation verifies guidance, setup failures, no premature trust/certificate calls, success, exhaustion and fresh Look. Earlier suites receive explicit successful-word fixtures when isolating identity/lip/profile behavior; actual recognition remains tested separately. Migration expectations include additive defaults without removing preservation checks. Regression found and fixed a retry-evidence collector assuming every failed scorer's `detail` was an object; existing lip failures supply a string, which now remains valid retry behavior.

The real database and original face model hashes remain unchanged; speech integrity and prior dependency pins are preserved. No volunteer/live-camera accuracy, accent coverage, all-ten-word evaluation, hardware alignment or end-to-end latency study was performed. Public/synthetic fixtures do not establish those outcomes. V2 stays opt-in pending later evaluation.

**Tasks 15–16 complete; stop here. Task 17 not implemented. No push.**
