"""SQLAlchemy session and durable queue lease helpers."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

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
    clause = or_(
        (model.status == "pending") & (model.available_at <= now),
        (model.status == "processing") & (model.claimed_until < now),
    ) if model is Event else or_(
        (model.status == "pending") & (model.available_at <= now),
        (model.status == "sending") & (model.claimed_until < now),
    )
    item = session.scalar(
        select(model).where(clause).order_by(model.id if model is Outbox else model.update_id)
        .limit(1).with_for_update(skip_locked=True)
    )
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
