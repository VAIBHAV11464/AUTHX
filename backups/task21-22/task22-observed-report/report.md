# Comparison: public-sapi-static-smoke

4 unique cases; 2 repetitions. Repeats are not independent recordings.

| Profile | Completed | SAFE accepted | Incorrect SAFE | Retry cases | Full-flow word verified | Mean processing |
| --- | --- | --- | --- | --- | --- | --- |
| legacy | 0/8 | 0/8 | Unavailable: No cases with known negative SAFE ground truth | 8/8 | Unavailable: No word verification measured in the full flow | 2.5900 s |
| v2 | 0/8 | 0/8 | Unavailable: No cases with known negative SAFE ground truth | 8/8 | Unavailable: No word verification measured in the full flow | 2.5784 s |

Synchronous test-client routes from session start through certificate or failure; excludes dataset IO, common enrollment, live capture/device/browser delays, and diagnostics.

| Independent word diagnostics (excluded from acceptance) | Verified | Known token agreement |
| --- | --- | --- |
| legacy | 4/8 | 8/8 |
| v2 | 4/8 | 8/8 |

Separate diagnostics never count as completed or SAFE verification. Legacy does not measure the challenge word. Unknown SAFE ground truth is excluded from incorrect-SAFE rates. Missing evidence has null metrics, never invented success.

Model/configuration versions, per-stage timings, denominators and component diagnostics are in results.json. No raw media, embeddings, credentials, OTPs or local dataset paths appear in these reports.
