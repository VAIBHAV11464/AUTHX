import json
import secrets
import sqlite3
import uuid
import time
from datetime import datetime, timezone

import bcrypt

from config import Config
from app.services.verification_profiles import get_profile
from app.services.session_lifecycle import LifecycleError, deadline_passed, expired, require_live

SEED_USERS = (
    ("vaibhav", "admin"),
    ("sriram", "faculty"),
    ("avinash", "student"),
)


def connect(db_path=None):
    path = db_path or Config.DATABASE_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    path = db_path or Config.DATABASE_PATH
    conn = connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'faculty', 'student')),
                face_embedding TEXT,
                face_enrolled_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                challenge_word TEXT NOT NULL,
                flash_start_ms INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                trust_score INTEGER,
                risk_label TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                face_score REAL,
                cosine REAL,
                blink_score REAL,
                blink_count INTEGER,
                flash_score REAL,
                reflection_delta REAL,
                reflection_r REAL,
                acoustic_score REAL,
                lip_score REAL,
                lip_r REAL,
                voice_score REAL,
                detail_json TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS certificates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                cert_id TEXT NOT NULL UNIQUE,
                block_hash TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                score_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                otp_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS faculty_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                attempt_generation INTEGER NOT NULL,
                actor_id INTEGER NOT NULL REFERENCES users(id),
                actor_role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                selected_label TEXT NOT NULL CHECK (selected_label IN ('SAFE', 'SUSPICIOUS', 'DEEPFAKE')),
                previous_label TEXT,
                machine_trust_score INTEGER,
                machine_risk_label TEXT
            );
            CREATE INDEX IF NOT EXISTS overrides_session ON faculty_overrides(session_id, id);
            CREATE TABLE IF NOT EXISTS session_rotations (
                original_session_id TEXT PRIMARY KEY REFERENCES sessions(id),
                new_session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id)
            );
        ''')
        # Additive migration: historical attempts always belong to legacy,
        # regardless of the configured profile for newly started attempts.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "verification_profile" not in columns:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN verification_profile TEXT "
                "NOT NULL DEFAULT 'legacy' "
                "CHECK (verification_profile IN ('legacy', 'v2'))"
            )
        # Retry state belongs to the session, so deleting results/reopening cannot reset it.
        for name, definition in (
            ('speak_attempts', 'INTEGER NOT NULL DEFAULT 0 CHECK (speak_attempts >= 0)'),
            ('speak_token', 'TEXT'), ('speak_reserved_at', 'REAL'), ('speak_last_evidence', 'TEXT'),
            ('attempt_generation', 'INTEGER NOT NULL DEFAULT 0'),
            ('machine_trust_score', 'INTEGER'), ('machine_risk_label', 'TEXT'),
        ):
            if name not in columns:
                conn.execute(f'ALTER TABLE sessions ADD COLUMN {name} {definition}')
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(results)")}
        if "speak_cosine" not in columns:
            # NULL means no measured Speak identity. Preserve historical rows.
            conn.execute("ALTER TABLE results ADD COLUMN speak_cosine REAL")
        seeded = _seed_users(conn)
        conn.commit()
        return seeded
    finally:
        conn.close()


def _seed_users(conn):
    count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if count:
        return []
    now = _utc_now()
    created = []
    for username, role in SEED_USERS:
        password = "pass"
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, role, now),
        )
        created.append((username, role, password))
    if created:
        print("AuthX seed accounts (shown once):")
        for username, role, password in created:
            print(f"  {username} ({role}): {password}")
    return created


def get_user_by_username(username, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def create_otp(user_id, otp_hash, expires_at, db_path=None):
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE otps SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO otps (user_id, otp_hash, expires_at, used, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (user_id, otp_hash, expires_at, _utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def latest_unused_otp(user_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            """
            SELECT * FROM otps
            WHERE user_id = ? AND used = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def save_face_embedding(user_id, embedding, db_path=None):
    conn = connect(db_path)
    try:
        conn.execute(
            """
            UPDATE users
            SET face_embedding = ?, face_enrolled_at = ?
            WHERE id = ?
            """,
            (embedding, _utc_now(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def create_session(user_id, word, flash_start_ms, db_path=None, *, verification_profile="legacy", connection=None):
    profile = get_profile(verification_profile)
    session_id = str(uuid.uuid4())
    conn = connection or connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                id, user_id, challenge_word, flash_start_ms, status, started_at,
                verification_profile
            ) VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (session_id, user_id, word, int(flash_start_ms), _utc_now(), profile.name),
        )
        if connection is None:
            conn.commit()
        return session_id
    finally:
        if connection is None:
            conn.close()


def get_session(session_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()


def get_result(session_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM results WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()


def _mutable_session(conn, session_id, generation=None):
    session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    require_live(session)
    if conn.execute('SELECT 1 FROM certificates WHERE session_id = ?', (session_id,)).fetchone():
        raise LifecycleError('session_certified')
    if generation is not None and session['attempt_generation'] != generation:
        raise LifecycleError('session_attempt_superseded')
    return session


def save_look(session_id, scores, db_path=None, *, generation=None):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = _mutable_session(conn, session_id, generation)
        if session['status'] != 'open':
            raise LifecycleError('session_scored')
        conn.execute(
            """
            INSERT INTO results (
                session_id, face_score, cosine, blink_score, blink_count,
                flash_score, reflection_delta, reflection_r, detail_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                scores["faceScore"],
                scores["cosine"],
                scores["blinkScore"],
                scores["blinkCount"],
                scores["flashScore"],
                scores["reflectionDelta"],
                scores["reflectionR"],
                scores["detailJson"],
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_voice(session_id, scores, db_path=None, *, connection=None, generation=None, result_id=None):
    conn = connection or connect(db_path)
    try:
        if connection is None:
            conn.execute('BEGIN IMMEDIATE')
        session = _mutable_session(conn, session_id, generation)
        if session['status'] != 'open':
            raise LifecycleError('session_scored')
        row = conn.execute(
            "SELECT * FROM results WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None or (result_id is not None and row['id'] != result_id):
            raise LifecycleError('session_attempt_superseded')
        if row['voice_score'] is not None:
            raise LifecycleError('speak_locked')
        detail = json.loads(row["detail_json"] or "{}") if row and row["detail_json"] else {}
        detail.update(scores["detail"])
        conn.execute(
            """
            UPDATE results
            SET acoustic_score = ?, lip_score = ?, lip_r = ?, voice_score = ?, speak_cosine = ?,
                detail_json = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                scores["acousticScore"],
                scores["lipScore"],
                scores["lipR"],
                scores["voiceScore"],
                scores.get("speakCosine"),
                json.dumps(detail),
                _utc_now(),
                session_id,
            ),
        )
        if connection is None:
            conn.commit()
    finally:
        if connection is None:
            conn.close()


SPEAK_MAX_ATTEMPTS = 4  # Initial submission plus three retries, fixed for Task 16.
SPEAK_LEASE_SECONDS = 120


def _speak_budget(session, **extra):
    used = session['speak_attempts']
    return {'attemptsUsed': used, 'attemptsRemaining': max(0, SPEAK_MAX_ATTEMPTS - used), **extra}


def reserve_speak(session_id, user_id, db_path=None):
    """Reserve one valid submission atomically across processes, before expensive scoring."""
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        row = conn.execute('SELECT * FROM results WHERE session_id = ?', (session_id,)).fetchone()
        if session is None or session['user_id'] != user_id:
            return {'ok': False, 'reason': 'forbidden'}
        if expired(session):
            return _speak_budget(session, ok=False, reason='session_expired', freshSessionRequired=True, retryable=False)
        if conn.execute('SELECT 1 FROM certificates WHERE session_id = ?', (session_id,)).fetchone():
            return {'ok': False, 'reason': 'session_certified', 'retryable': False}
        if row is None:
            return {'ok': False, 'reason': 'look_required'}
        if row['voice_score'] is not None:
            return {'ok': False, 'reason': 'speak_locked'}
        now = time.time()
        if session['speak_token'] and now - session['speak_reserved_at'] < SPEAK_LEASE_SECONDS:
            return _speak_budget(session, ok=False, reason='speak_in_progress', retryable=True)
        if session['speak_attempts'] >= SPEAK_MAX_ATTEMPTS:
            return _speak_budget(session, ok=False, reason='speak_attempts_exhausted',
                                 freshSessionRequired=True, retryable=False)
        token = secrets.token_hex(16)
        conn.execute('UPDATE sessions SET speak_attempts = speak_attempts + 1, speak_token = ?, '
                     'speak_reserved_at = ? WHERE id = ?', (token, now, session_id))
        conn.commit()
        return {'ok': True, 'token': token, 'resultId': row['id']}
    finally:
        conn.close()


def finish_speak(session_id, reservation, scored, *, setup_failure=False, db_path=None):
    """Complete only our reservation, persisting success and releasing the slot in one txn."""
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        row = conn.execute('SELECT * FROM results WHERE session_id = ?', (session_id,)).fetchone()
        if (session is None or session['speak_token'] != reservation['token'] or row is None
                or row['id'] != reservation['resultId'] or row['voice_score'] is not None):
            return {'ok': False, 'reason': 'speak_attempt_superseded', 'retryable': True}
        if expired(session):
            conn.execute('UPDATE sessions SET speak_token = NULL, speak_reserved_at = NULL WHERE id = ?', (session_id,))
            conn.commit()
            return _speak_budget(session, ok=False, reason='session_expired', freshSessionRequired=True, retryable=False)
        if scored['ok']:
            save_voice(session_id, scored, connection=conn)
        detail = scored.get('detail')
        evidence = {'reason': scored.get('reason'), 'speech': scored.get('speech')
                    or (detail.get('speech') if isinstance(detail, dict) else None)}
        conn.execute('UPDATE sessions SET speak_token = NULL, speak_reserved_at = NULL, '
                     'speak_attempts = speak_attempts - ?, speak_last_evidence = ? WHERE id = ?',
                     (int(setup_failure), json.dumps(evidence, allow_nan=False), session_id))
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        conn.commit()
        exhausted = not scored['ok'] and not setup_failure and session['speak_attempts'] >= SPEAK_MAX_ATTEMPTS
        return _speak_budget(session, ok=scored['ok'],
                             reason='speak_attempts_exhausted' if exhausted else scored.get('reason'),
                             attemptReason=scored.get('reason'), freshSessionRequired=exhausted,
                             retryable=not scored['ok'] and not exhausted)
    finally:
        conn.close()


def save_trust(session_id, trust_score, risk_label, db_path=None, *, machine_decision=None,
               legacy_decision=None, generation=None, result_id=None):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = _mutable_session(conn, session_id, generation)
        row = conn.execute('SELECT * FROM results WHERE session_id = ?', (session_id,)).fetchone()
        if row is None or (result_id is not None and row['id'] != result_id):
            raise LifecycleError('session_attempt_superseded')
        if any(row[name] is None for name in ('face_score', 'blink_score', 'flash_score', 'voice_score')):
            raise LifecycleError('incomplete')
        from app.services.decision_evidence import stored_decision
        if session['status'] == 'scored' and (
                (session['verification_profile'] == 'legacy' and session['machine_trust_score'] is not None)
                or (session['verification_profile'] == 'v2' and stored_decision(row['detail_json']))):
            return session
        if machine_decision is not None or legacy_decision is not None:
            from app.services.decision_evidence import object_json
            row = conn.execute('SELECT detail_json FROM results WHERE session_id = ?', (session_id,)).fetchone()
            detail = object_json(row['detail_json'] if row else None)
            if machine_decision is not None:
                detail['machineDecision'] = machine_decision
            if legacy_decision is not None:
                detail['legacyMachineDecision'] = legacy_decision
            conn.execute('UPDATE results SET detail_json = ? WHERE session_id = ?',
                         (json.dumps(detail, allow_nan=False), session_id))
        conn.execute(
            """
            UPDATE sessions
            SET trust_score = ?, risk_label = ?, status = 'scored', completed_at = ?,
                machine_trust_score = ?, machine_risk_label = ?
            WHERE id = ?
            """,
            (int(trust_score), session['risk_label'] if _active_override(conn, session) else risk_label,
             _utc_now(), int(trust_score), risk_label, session_id),
        )
        saved = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        conn.commit()
        return saved
    finally:
        conn.close()


def _active_override(conn, session):
    return conn.execute('SELECT * FROM faculty_overrides WHERE session_id = ? AND attempt_generation = ? '
                        'ORDER BY id DESC LIMIT 1', (session['id'], session['attempt_generation'])).fetchone()


def override_summary(row):
    if row is None:
        return None
    return {'id': row['id'], 'actorId': row['actor_id'], 'actorRole': row['actor_role'],
            'createdAt': row['created_at'], 'selectedLabel': row['selected_label'],
            'previousLabel': row['previous_label'], 'machineTrustScore': row['machine_trust_score'],
            'machineRiskLabel': row['machine_risk_label'], 'attemptGeneration': row['attempt_generation']}


def get_active_override(session, db_path=None, *, connection=None):
    conn = connection or connect(db_path)
    try:
        return override_summary(_active_override(conn, session))
    finally:
        if connection is None:
            conn.close()


def set_risk_label(session_id, label, db_path=None, *, actor_id):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        actor = conn.execute('SELECT * FROM users WHERE id = ?', (actor_id,)).fetchone()
        if actor is None or actor['role'] not in ('faculty', 'admin'):
            raise LifecycleError('forbidden')
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        if session is None:
            return False
        from app.services.decision_evidence import stored_decision
        result = conn.execute('SELECT detail_json FROM results WHERE session_id = ?', (session_id,)).fetchone()
        machine = stored_decision(result['detail_json']) if result else None
        conn.execute('INSERT INTO faculty_overrides (session_id, attempt_generation, actor_id, actor_role, '
                     'created_at, selected_label, previous_label, machine_trust_score, machine_risk_label) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (session_id, session['attempt_generation'], actor_id, actor['role'], _utc_now(), label,
                      session['risk_label'], machine['trustScore'] if machine else session['machine_trust_score'],
                      machine['riskLabel'] if machine else session['machine_risk_label']))
        updated = conn.execute(
            "UPDATE sessions SET risk_label = ? WHERE id = ?",
            (label, session_id),
        ).rowcount
        conn.commit()
        return updated > 0
    finally:
        conn.close()


def list_sessions(db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            """
            SELECT s.id, s.challenge_word, s.flash_start_ms, s.status,
                   s.trust_score, s.risk_label, s.started_at, u.username
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            ORDER BY s.started_at DESC
            """
        ).fetchall()
    finally:
        conn.close()


def session_detail(session_id, db_path=None):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN')
        row = conn.execute(
            """
            SELECT s.id, s.challenge_word, s.flash_start_ms, s.status,
                   s.trust_score, s.risk_label, s.started_at, u.username,
                   r.face_score, r.cosine, r.blink_score, r.blink_count,
                   r.flash_score, r.reflection_delta, r.reflection_r,
                   r.acoustic_score, r.lip_score, r.lip_r, r.voice_score, r.detail_json,
                   c.cert_id
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            LEFT JOIN results AS r ON r.session_id = s.id
            LEFT JOIN certificates AS c ON c.session_id = s.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        overrides = [override_summary(item) for item in conn.execute(
            'SELECT * FROM faculty_overrides WHERE session_id = ? ORDER BY id', (session_id,))]
    finally:
        conn.close()
    if row is None:
        return None
    extra = {}
    if row["detail_json"]:
        try:
            parsed = json.loads(row["detail_json"])
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            extra = parsed
    return {
        "sessionId": row["id"],
        "username": row["username"],
        "word": row["challenge_word"],
        "flashStartMs": row["flash_start_ms"],
        "status": 'certified' if row['cert_id'] else 'expired' if expired(session) else row["status"],
        "overrides": overrides,
        "startedAt": row["started_at"],
        "trustScore": row["trust_score"],
        "riskLabel": row["risk_label"],
        "faceScore": row["face_score"],
        "cosine": row["cosine"],
        "blinkScore": row["blink_score"],
        "blinkCount": row["blink_count"],
        "dipPercent": extra.get("dipPercent"),
        "flashScore": row["flash_score"],
        "reflectionDelta": row["reflection_delta"],
        "reflectionR": row["reflection_r"],
        "acousticScore": row["acoustic_score"],
        "lipScore": row["lip_score"],
        "lipR": row["lip_r"],
        "voiceScore": row["voice_score"],
        "rms": extra.get("rms"),
        "speechRatio": extra.get("speechRatio"),
        "mfccVariation": extra.get("mfccVariation"),
        "certId": row["cert_id"],
    }


def label_counts(db_path=None):
    counts = {"SAFE": 0, "SUSPICIOUS": 0, "DEEPFAKE": 0}
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT risk_label, COUNT(*) AS n
            FROM sessions
            WHERE risk_label IS NOT NULL
            GROUP BY risk_label
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        if row["risk_label"] in counts:
            counts[row["risk_label"]] = row["n"]
    return counts


def list_admin_certificates(db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            """
            SELECT c.cert_id, c.revoked, c.block_hash, c.prev_hash,
                   s.challenge_word, s.risk_label, u.username
            FROM certificates AS c
            JOIN sessions AS s ON s.id = c.session_id
            JOIN users AS u ON u.id = s.user_id
            ORDER BY c.id DESC
            """
        ).fetchall()
    finally:
        conn.close()


def clear_attempt(session_id, db_path=None):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        if session is None:
            return 'not_found'
        if conn.execute('SELECT 1 FROM certificates WHERE session_id = ?', (session_id,)).fetchone():
            rotation = conn.execute('SELECT new_session_id FROM session_rotations WHERE original_session_id = ?', (session_id,)).fetchone()
            if rotation:
                new_id = rotation['new_session_id']
            else:
                from flask import current_app
                cfg = current_app.config
                word = secrets.choice(cfg['CHALLENGE_WORDS'])
                flash = cfg['FLASH_START_MIN_MS'] + secrets.randbelow(cfg['FLASH_START_MAX_MS'] - cfg['FLASH_START_MIN_MS'] + 1)
                new_id = create_session(session['user_id'], word, flash,
                                        verification_profile=session['verification_profile'], connection=conn)
                conn.execute('INSERT INTO session_rotations VALUES (?, ?)', (session_id, new_id))
            conn.commit()
            return {'sessionId': new_id, 'previousSessionId': session_id, 'newSession': True}
        if deadline_passed(session):
            return 'session_expired'
        if session and session['verification_profile'] == 'v2':
            if session['speak_token'] and time.time() - session['speak_reserved_at'] < SPEAK_LEASE_SECONDS:
                return 'speak_in_progress'
            if session['speak_attempts'] >= SPEAK_MAX_ATTEMPTS:
                return 'speak_attempts_exhausted'
        conn.execute("DELETE FROM results WHERE session_id = ?", (session_id,))
        conn.execute(
            """
            UPDATE sessions
            SET status = 'open', trust_score = NULL, risk_label = NULL, completed_at = NULL,
                speak_token = NULL, speak_reserved_at = NULL, attempt_generation = attempt_generation + 1,
                machine_trust_score = NULL, machine_risk_label = NULL
            WHERE id = ?
            """,
            (session_id,),
        )
        conn.commit()
        return None
    finally:
        conn.close()


def latest_certificate(db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM certificates ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def list_certificates(db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute("SELECT * FROM certificates ORDER BY id").fetchall()
    finally:
        conn.close()


def get_certificate(cert_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM certificates WHERE cert_id = ?",
            (cert_id,),
        ).fetchone()
    finally:
        conn.close()


def get_certificate_for_session(session_id, db_path=None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM certificates WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()


def insert_certificate(session_id, cert_id, block_hash, prev_hash, score_json, created_at, db_path=None, *,
                       generation=None, connection=None):
    conn = connection or connect(db_path)
    try:
        if connection is None:
            conn.execute('BEGIN IMMEDIATE')
        _mutable_session(conn, session_id, generation)
        conn.execute(
            """
            INSERT INTO certificates (
                session_id, cert_id, block_hash, prev_hash, score_json, created_at, revoked
            ) VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (session_id, cert_id, block_hash, prev_hash, score_json, created_at),
        )
        conn.execute(
            """
            UPDATE sessions
            SET status = 'certified', completed_at = ?
            WHERE id = ?
            """,
            (created_at, session_id),
        )
        if connection is None:
            conn.commit()
    finally:
        if connection is None:
            conn.close()


def revoke_certificate(cert_id, db_path=None):
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT block_hash, prev_hash FROM certificates WHERE cert_id = ?",
            (cert_id,),
        ).fetchone()
        if row is None:
            return None
        before = (row["block_hash"], row["prev_hash"])
        conn.execute(
            "UPDATE certificates SET revoked = 1 WHERE cert_id = ?",
            (cert_id,),
        )
        conn.commit()
        return before
    finally:
        conn.close()


def mark_otp_used(otp_id, db_path=None):
    conn = connect(db_path)
    try:
        conn.execute("UPDATE otps SET used = 1 WHERE id = ?", (otp_id,))
        conn.commit()
    finally:
        conn.close()


def consume_otp(otp_id, db_path=None, *, now=None):
    """Claim a verified OTP once, including expiry and newer-login invalidation."""
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM otps WHERE id = ?', (otp_id,)).fetchone()
        if row is None or row['used']:
            return 'invalid_otp'
        try:
            expires = datetime.fromisoformat(row['expires_at'])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            error = 'otp_expired' if expires <= (now() if now else datetime.now(timezone.utc)) else None
        except (ValueError, TypeError, OverflowError):
            error = 'invalid_otp'
        conn.execute('UPDATE otps SET used = 1 WHERE id = ?', (otp_id,))
        conn.commit()
        return error
    finally:
        conn.close()


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
