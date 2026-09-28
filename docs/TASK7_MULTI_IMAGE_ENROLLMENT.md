# Task 7 — multi-image enrollment

Completed on 2026-09-27, Asia/Calcutta. Task 7's eight enrollment tests and the simulated wizard checks passed before Task 8 implementation began in the same explicitly authorized request.

## Changes

- The existing Enroll/Enroll again controls capture five JPEG images when the server renders v2 settings, approximately 200 ms apart. Progress appears in the existing prompt. Legacy settings retain the original single capture. Look/Speak recording durations and intervals are unchanged.
- `/api/face/enroll` accepts a v2 `images` array of exactly five items. Task 5's decoder checks every image before model processing; mixed `image`/`images` payloads, bad counts, and malformed images return HTTP 400. The shared 8 MiB request limit remains intact.
- Task 6's quality and enrollment-confidence gates evaluate each sample. A five-image batch needs at least three usable samples. Poor-quality samples may be skipped, but multiple faces or unavailable models abort the batch.
- Every usable SFace vector must have exactly 128 finite components and nonzero finite norm. Samples are normalized individually. All usable pairs must have cosine >= `0.60`, the initial `V2_ENROLL_CONSISTENCY_COSINE` setting. A usable sample that conflicts with the others is not discarded as an outlier.
- Save the normalized arithmetic mean of all usable, mutually consistent vectors in the existing `users.face_embedding` JSON field. There is no schema migration and no raw-image storage. The account is updated only after all checks succeed; failed reenrollment leaves the embedding and enrollment timestamp untouched.
- Existing `{image: ...}` requests remain accepted in both profiles. V2 single-image enrollment retains quality checks and now normalizes its one valid vector. Legacy single-image enrollment retains its original handler and stored representation. Old stored vectors are not rewritten.

Failure reasons include `too_few_enrollment_samples`, `inconsistent_enrollment`, and `invalid_face_embedding`, with guidance in the existing wizard. No new UI step, role, or challenge was introduced.

## Verification

```powershell
.\.venv\Scripts\python.exe tests\enrollment_matching.py
node tests\wizard_enrollment.js
```

The final enrollment/matching suite passed 17 tests: eight enrollment tests and nine Task 8 matching tests. Enrollment cases cover normalized averaging with differently scaled vectors, three usable samples plus two poor samples, fewer than three, mixed identities, multiple faces, missing models, invalid features, API batch validation, single-image and legacy compatibility, preserved accounts on failure, and profile-specific wizard settings.

The simulated wizard check exercises the real JavaScript click handler for legacy capture, five-image capture, failed reenrollment, and duplicate-click suppression. It uses a simulated camera/server, not a live webcam. Python compilation and JavaScript syntax checks also passed. Final regression results and logs are recorded with Task 8 in `backups/task7-8-20260927-validation/`.

## Preservation and limits

The real database was not initialized or modified. Its SHA-256 remained `EF2A8941EEA53701388D1B593B755A2AEE49252CAC6D62B89FB0ACB1D4DD279B`. All test writes used temporary databases. Existing model files, accounts, enrollment data, certificates, dependency files, and default legacy selection were preserved.

The consistency threshold is provisional. Synthetic vectors verify the algorithm and failure behavior; they do not measure real-person enrollment accuracy. Live webcam evaluation, volunteer tuning, and latency measurement remain later tasks. The batch consistency test does not prove that uploaded samples came from separate live camera moments.

**Task 7 is complete. Task 8 was also authorized and is documented separately. No GitHub push was performed.**
