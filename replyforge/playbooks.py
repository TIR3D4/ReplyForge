"""Validated, versioned playbooks stored in PostgreSQL, with a file default."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import parse_playbook_yaml
from .models import PlaybookVersion


def active_version(session: Session) -> PlaybookVersion | None:
    return session.scalar(select(PlaybookVersion).where(
        PlaybookVersion.active.is_(True),
    ).order_by(PlaybookVersion.id.desc()).limit(1))


def effective_playbook(session: Session, fallback: dict) -> tuple[dict, int]:
    active = active_version(session)
    return (parse_playbook_yaml(active.source), active.id) if active else (fallback, 0)


def save_playbook(session: Session, source: str) -> PlaybookVersion:
    if len(source) > 50_000:
        raise ValueError("Playbook must be under 50KB")
    parse_playbook_yaml(source)  # validate all transitions before saving
    for current in session.scalars(select(PlaybookVersion).where(PlaybookVersion.active.is_(True))).all():
        current.active = False
    version = PlaybookVersion(source=source, active=True)
    session.add(version)
    session.flush()
    return version


def activate_version(session: Session, version_id: int) -> bool:
    target = session.get(PlaybookVersion, version_id)
    if target is None:
        return False
    parse_playbook_yaml(target.source)
    for current in session.scalars(select(PlaybookVersion).where(PlaybookVersion.active.is_(True))).all():
        current.active = False
    target.active = True
    return True
