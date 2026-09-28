# AuthX baseline before upgrades — Task 1

Recorded on 2026-09-27, Asia/Calcutta. Only Task 1 was performed: preservation and documentation. Application code, settings, dependencies, model files, and the original database were not modified.

## Preservation record

Backup directory: `D:\AI PROJECT\backups\task1-20260927-014653`.

| Artifact | Purpose |
| --- | --- |
| `authx.db` | Consistent database snapshot created with SQLite's online backup command from a read-only source connection. |
| `source-snapshot.zip` | Snapshot of 37 application, template, static asset, test, configuration, and example configuration files, including `.gitignore`. |
| `schema.sql` | Export of the database schema at backup time. |
| `manifest.json` | Timestamp, SHA-256 checksums, source/model inventory, database counts, verification results, and initial Git status. |

The source archive excludes the virtual environment, Python caches, Git history, the database, any real `.env`, and model binaries. The existing two ONNX model files are inventoried and hashed separately in the manifest; they remain in `models/`. The database snapshot contains the application's existing account and biometric data and should remain local.

Initial Git status listed the application files as untracked; this task does not create commits or stage files. The source snapshot therefore preserves content that cannot currently be recovered through a Git checkout.

### Database verification

- Backup `PRAGMA integrity_check`: `ok`.
- Backup `PRAGMA foreign_key_check`: no violations.
- Original and backup table counts match.
- Original database SHA-256 before and after backup matches exactly.

| Table | Rows |
| --- | ---: |
| users | 3 |
| sessions | 18 |
| results | 2 |
| certificates | 2 |
| otps | 5 |

These are preservation checks, not authentication or accuracy tests. No account values, password hashes, OTP hashes, or face embeddings were printed to document this baseline.

## Current behavior established by source inspection

### Application and login

- Python/Flask server entrypoint: `app.py`; binds to `127.0.0.1:5000` with debug disabled when run directly.
- SQLite stores users, sessions, results, certificates, and OTP records. Creating the Flask app initializes the schema and seeds accounts only when the users table is empty.
- `/` redirects to `/login`; `/api/health` is implemented to return AuthX's health response.
- Passwords use bcrypt. Student login issues an HS256 JWT immediately; faculty/admin login requires a six-digit OTP first.
- JWT expiry is eight hours; OTP expiry is ten minutes. Browser sign-in state uses localStorage.
- Configured SMTP sends OTP mail to the configured SMTP account, with the username identified in the message. With no credentials or on delivery failure, the current implementation prints the OTP to the server console.
- Student, faculty, and admin home pages use the existing role checks. API authorization looks up the current user's role in the database.

### Student verification flow

1. Allow/select camera; enroll from a single captured image. YuNet detects a face and SFace creates the stored embedding.
2. Start Look: the server creates a UUID session, chooses one of ten words, and selects a random flash start between 1900 and 2400 ms.
3. The browser records approximately three seconds of Look frames at a target interval of 100 ms, with a 400 ms screen flash. JPEG long side is capped at 640 pixels, quality 0.7.
4. Face comparison requires at least eight eligible pre-flash frames and compares the three highest detector-confidence candidates, using their median cosine similarity.
5. Blink detection uses local image gradients as an eye-opening proxy. Despite the pre-flash prompt, the current implementation includes post-flash frames and excludes only frames during the flash. A signal dip can count without a completed return to open eyes.
6. Flash scoring uses the change in face brightness before/during the flash. Insufficient samples produce score 50 with missing reflection measurements.
7. Start Speak: record approximately three seconds of audio/video; video frame interval is 200 ms. Audio is resampled to 16 kHz, mono, 16-bit PCM WAV.
8. Acoustic scoring uses RMS, energy in a speech-frequency band, and MFCC variation. Lip scoring uses a mouth-region image-gradient proxy correlated with audio energy. Insufficient lip samples produce score 50.
9. The requested word is displayed but not checked by speech recognition. The Speak step does not compare face identity against enrollment.
10. Save voice results, calculate trust, then request a certificate. Successfully saved Look/Speak results lock those steps against repeat submissions.

### Scoring contract

| Setting | Current behavior |
| --- | --- |
| Base trust | `0.45 * face + 0.30 * blink + 0.25 * voice` |
| Voice score | `0.75 * acoustic + 0.25 * lip` |
| Flash adjustment | Score 90: +8; 60: +3; 50: 0; 25: -8 |
| Final rounding | Clamp to 0–100; round half up to an integer |
| Face cap | Face score below 50 caps trust at 74 |
| SAFE | Trust >= 75 |
| SUSPICIOUS | Trust >= 45 and < 75 |
| DEEPFAKE | Trust < 45 |
| Cosine reference | `0.363` affects face-score mapping; it is not an independent SAFE eligibility gate |
| Upload limit | 8 MiB |

The current labels are heuristic risk categories, not measured probabilities. Accuracy, false-acceptance rate, and false-rejection rate have not been measured in Task 1.

### Faculty, admin, sessions, and certificates

- Faculty/admin APIs list sessions, return detailed measurements, override risk labels, and reopen attempts. Admin APIs provide counts and certificate revocation.
- Unfinished sessions currently have no age-based expiry or verification profile/version.
- An override replaces the session label without a separate audit record; the existing certificate snapshot is not rewritten.
- Reopening deletes results and resets scoring fields on the same session, without rotating its challenge or removing an existing certificate.
- Completed scoring can issue a certificate for any of the three risk labels. A certificate records the outcome; issuance itself does not mean SAFE.
- Certificates use `AX-` identifiers and SHA-256 hashes linking to the previous certificate, starting at `GENESIS`. Hashes include the stored score snapshot.
- Certificate pages are public by certificate identifier and show measurements, chain status, and revocation status.
- Repeat issuance returns an existing certificate. Selecting the preceding certificate and inserting the next certificate are not currently one transaction.
- Revocation changes the revoked flag while retaining hashes. Historical certificate chain integrity was not recomputed in Task 1; SQLite integrity checks do not verify application-level hashes.

## Runtime evidence and deferred work

- A read-only request to `http://127.0.0.1:5000/api/health` was refused: no running app was reachable there. The app was not started because startup can initialize the database.
- The existing virtual environment references a Python 3.12 installation and an older workspace location. Its interpreter failed to launch during the earlier overview; restoring the environment belongs to Task 2.
- Source behavior above was inspected, not demonstrated with a live camera/microphone session.
- Existing `tests/smoke_api.py` covers scoring fixtures, model loading, login/permissions, session prerequisites, certificate linkage, and invalid image/audio input. It uses a temporary database. It was not run in Task 1; execution belongs to Task 3.
- No dependencies were installed, no accounts or attempts were created, and no OTPs were sent.

## Recovery reference

Do not restore as part of Task 1. If restoration is later requested, stop application processes first and preserve the then-current database before replacing it with this snapshot. Verify the snapshot against its manifest checksum and run SQLite integrity checks. Extract source files into a separate directory first, then compare them before replacing working files. The source archive does not recreate the Python environment or model binaries.

**Task 1 is complete. Task 2 has not started.**
