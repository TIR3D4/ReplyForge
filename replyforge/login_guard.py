"""Shared database login throttling; remote addresses are stored only as HMACs."""
from datetime import timedelta, timezone
from .database import session_scope
from .models import LoginBucket, utcnow
from .security import fingerprint


def attempt(factory, address: str, pepper: str) -> str | None:
    key = fingerprint('login:' + address, pepper)
    with session_scope(factory) as db:
        if db.bind.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        now = utcnow()
        db.execute(insert(LoginBucket).values(key=key, attempts=0, started_at=now).on_conflict_do_nothing())
        row = db.get(LoginBucket, key, with_for_update=True)
        start = row.started_at.replace(tzinfo=timezone.utc) if row.started_at.tzinfo is None else row.started_at
        if now - start >= timedelta(minutes=5):
            row.attempts, row.started_at = 0, now
        if row.attempts >= 30:
            return None
        row.attempts += 1
    return key


def success(factory, key):
    with session_scope(factory) as db:
        row = db.get(LoginBucket, key, with_for_update=True)
        if row:
            row.attempts = 0
