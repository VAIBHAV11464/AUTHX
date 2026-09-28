# Task 2 — reproducible local Python environment

Task 2 covers the environment and run instructions only. Full regression testing remains Task 3; verification/model upgrades remain later tasks.

## Correction to the earlier diagnosis

The existing Python 3.12.3 installation and virtual environment successfully launch outside the sandbox. The launch failures seen during the overview were caused by sandbox access restrictions, not a missing Python installation. The app was moved to the planned Python 3.11 environment for reproducibility and the later upgrade work, rather than because the old interpreter was broken.

## Environment layout

| Item | Location/version |
| --- | --- |
| Current interpreter | `.runtime/python/cpython-3.11.15-windows-x86_64-none/python.exe` |
| Current virtual environment | `.venv/` — CPython 3.11.15, Windows x86-64 |
| Pinned application dependencies | `requirements.lock` |
| Package download cache | `.runtime/uv-cache/` |
| Preserved old environment | `.runtime/previous-venv-20260927-015251/` |
| Previous environment records | `backups/task2-20260927-015251/` |

Python was downloaded with the existing `uv` tool without registering it in Windows or changing PATH. The old environment was moved intact into `.runtime/` before the new `.venv` was created. Its original configuration and package versions were recorded separately.

All previously installed application package versions were retained except NumPy: the previous `2.5.3` has no usable Python 3.11 wheel in this setup, so resolution selected `2.4.6`. The original requirements were not edited. Flask remains 3.1.3 and OpenCV remains 5.0.0.93. MediaPipe and Vosk were not added in Task 2.

## Reproduce on a fresh checkout

Prerequisites: Windows x86-64, `uv` available in PowerShell, and internet access during installation. Run from the project root. These instructions are for a checkout without an existing `.venv`; preserve an existing environment before rebuilding it.

```powershell
uv python install 3.11.15 --install-dir '.runtime/python' --cache-dir '.runtime/uv-cache' --no-bin --no-registry
.\.runtime\python\cpython-3.11.15-windows-x86_64-none\python.exe -m venv .venv
uv pip sync requirements.lock --python '.venv/Scripts/python.exe' --require-hashes --only-binary :all: --cache-dir '.runtime/uv-cache'
```

The application dependencies are installed from the lockfile, rather than resolving the unbounded minimum versions in `requirements.txt` again. The lockfile is for the current Windows/Python 3.11 setup; it does not claim validated compatibility with other platforms.

The YuNet/SFace model binaries and the database are ignored by Git and are not created by these environment commands. Preserve the existing files when working in this checkout; a fresh checkout needs those two model files supplied separately. Launching the app without an existing database creates demo accounts as described in the README.

## Start and stop

```powershell
Set-Location 'D:\AI PROJECT'
.\.venv\Scripts\python.exe app.py
```

Browse to `http://127.0.0.1:5000/login`; press Ctrl+C in the server terminal to stop. The server retains its existing loopback binding and disabled debug mode.

## Verification record

Results are recorded in `backups/task2-20260927-015251/validation.json` and `environment-record.json` after verification completes. Checks cover interpreter/dependency readiness, model construction, isolated startup, and preservation of the original source/model/database files. They are not the full Task 3 regression suite or camera/microphone accuracy evaluation.

Completed checks:

- CPython 3.11.15 runs from `.venv` and all seven direct dependency imports succeed.
- `python -m pip check` reports no broken requirements.
- YuNet inference on a blank image completes with no detected face; SFace produces a finite 128-component feature vector.
- Isolated Flask initialization succeeds; its test client returns health 200, root redirect 302 to `/login`, and login page 200.
- The original database SHA-256 is unchanged, along with all 36 original application/configuration files other than the intentional `.gitignore` addition, and both model files.
- OpenCV 5 emits a graph-engine target warning during model initialization. Both inference checks succeed; no OpenCV changes were made to suppress it.

These checks did not start a persistent server, authenticate users, record camera/microphone input, or run `tests/smoke_api.py`.

Startup verification uses a SQLite backup in a temporary directory and redirects the app's database setting in memory before creating the Flask app. It must not initialize or modify the real `authx.db`, send OTPs, reset passwords, or create sessions.

## Recovery

The old environment's package files remain preserved. Because its activation scripts refer to the original `.venv` location, do not activate the relocated copy as though it were a newly created environment. If rollback is requested later, stop all application processes, preserve the then-current environment, and move the preserved old directory back to `.venv`. Alternatively, recreate a Python 3.12 environment using `previous-packages.txt`. No rollback was performed in Task 2.

**Task 2 is complete. Task 3 has not started.**
