# V2 readiness decision

retain_legacy

Default remains legacy. Actual human evaluation: pending_actual_consented_recordings.

Consenting volunteers: 0; held out: 0; recordings: 0; cameras: 0.

| Criterion | Status | Observed numerator / denominator |
| --- | --- | --- |
| genuineCompletionWithinTwo | unavailable | 0 / 0 |
| zeroHeldOutWrongPersonWrongWordSafe | unavailable | 0 / 0 |
| referenceLaptop95PercentWithinEightSeconds | unavailable | 0 / 0 |

- Fewer than ten consenting unique volunteers
- Exactly two distinct declared cameras are required by this study protocol
- Protocol, attempt unit and latency boundary have not been declared before collection
- No held-out evaluation volunteers
- Held-out subject/camera/lighting/attack matrix is incomplete
- Predeclared evaluation trials have missing recordings or outcomes
- Reference laptop has not been identified and confirmed on this runtime
- genuineCompletionWithinTwo: unavailable
- zeroHeldOutWrongPersonWrongWordSafe: unavailable
- referenceLaptop95PercentWithinEightSeconds: unavailable
- No held-out genuine outcomes
- No held-out wrong_person outcomes
- No held-out wrong_word outcomes
- No held-out photo outcomes
- No held-out screen_replay outcomes
- No verified pre-run source/config/ground-truth/split freeze

The paired harness holds one common enrollment vector fixed. It does not compare legacy single-image against v2 five-image enrollment; original v2 enrollment collection is reported separately.

Predeclared full-scoring benchmark uses every genuine held-out session attempt, including failures as unavailable samples. Partial and attack rejection times are separate diagnostics; neither can prove the complete eight-second scoring target.
