"""Persistent start time is authoritative; read-only expiry needs no cleanup job."""
import time
from datetime import datetime, timezone

SESSION_SECONDS = 600


class LifecycleError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def deadline_passed(session, *, now=None):
    try:
        started = datetime.fromisoformat(session['started_at'])
        if started.tzinfo is None or started.utcoffset() != timezone.utc.utcoffset(started):
            return True
        return (time.time() if now is None else now) >= started.timestamp() + SESSION_SECONDS
    except (ValueError, TypeError, OverflowError):
        return True


def expired(session, *, now=None):
    return session['status'] not in ('scored', 'certified') and deadline_passed(session, now=now)


def require_live(session):
    if session is None:
        raise LifecycleError('not_found')
    if expired(session):
        raise LifecycleError('session_expired')


def failure_fields(reason):
    return {'ok': False, 'reason': reason, 'retryable': False,
            'freshSessionRequired': reason == 'session_expired'}
