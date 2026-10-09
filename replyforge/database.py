"""SQLAlchemy session and durable queue lease helpers."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta, timezone

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Event, Outbox, utcnow


def new_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def create_schema(engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker):
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def claim(session: Session, model, lease_seconds: int):
    """One worker claims one record; other workers skip locked PostgreSQL rows."""
    now = utcnow()
    if model is Event:
        # Global FIFO deliberately trades throughput for deterministic ordering.
        # A backoff or unexpired lease must not let later inputs advance a flow.
        item = session.scalar(select(Event).where(
            Event.status.in_(("pending", "processing")),
        ).order_by(Event.update_id).limit(1).with_for_update())
        if item is None:
            return None
        deadline = item.available_at if item.status == "pending" else item.claimed_until
        if deadline is not None:
            deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline
            if deadline > now:
                return None
    else:
        clause = or_(
            (model.status == "pending") & (model.available_at <= now),
            (model.status == "sending") & (model.claimed_until < now),
        )
        item = session.scalar(select(model).where(clause).order_by(model.id)
                              .limit(1).with_for_update(skip_locked=True))
        if item is None:
            return None
    # Never automatically resend a message after an unknown delivery outcome.
    if model is Outbox and item.status == "sending":
        item.status = "uncertain"
        item.error_code = "worker_crashed_mid_send"
        return None
    item.status = "processing" if model is Event else "sending"
    item.claimed_until = now + timedelta(seconds=lease_seconds)
    if model is Event:
        item.attempts += 1
    session.flush()
    return item


def session_factory(url: str):
    engine = new_engine(url)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def exclusive_worker(engine):
    """Enforce the supported single-worker topology on PostgreSQL.

    Keep the same session-level advisory lock connection alive throughout run().
    Losing this connection must stop the worker, not silently reconnect it.
    """
    from sqlalchemy import text
    if engine.dialect.name != 'postgresql':
        yield None  # SQLite is a single-process development/test mode only.
        return
    with engine.connect() as connection:
        locked = connection.scalar(text('SELECT pg_try_advisory_lock(1380339761)'))
        connection.commit()
        if not locked:
            raise RuntimeError('Another ReplyForge worker is already active')
        try:
            yield connection
        finally:
            if not connection.invalidated:
                connection.execute(text('SELECT pg_advisory_unlock(1380339761)'))
                connection.commit()
