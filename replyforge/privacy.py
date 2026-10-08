"""Bounded PII/media retention. Keeps operational timestamps and audit structure."""
from __future__ import annotations

from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    InsightCandidate, KnowledgeSuggestion, Message, OperatorDraft, Outbox, Ticket, TicketNote, utcnow,
)

EXPIRED = "[expired]"


def prune_history(session: Session, retention_days: int, *, batch_size: int = 250) -> dict[str, int]:
    """Scrub old content without deleting ticket lifecycle or dependency relationships."""
    counts = {"messages": 0, "outbox": 0, "notes": 0, "drafts": 0, "suggestions": 0, "ticket_summaries": 0, "insight_candidates": 0}
    if retention_days == 0:
        return counts
    if not 7 <= retention_days <= 3650 or not 1 <= batch_size <= 1000:
        raise ValueError("Invalid retention settings")
    cutoff = utcnow() - timedelta(days=retention_days)

    msgs = session.scalars(select(Message).where(
        Message.created_at < cutoff, Message.content != EXPIRED,
    ).order_by(Message.id).limit(batch_size)).all()
    for item in msgs:
        item.content = EXPIRED
        item.data = {}  # forget Telegram photo and voice file_id references
    counts["messages"] = len(msgs)

    deliveries = session.scalars(select(Outbox).where(
        Outbox.created_at < cutoff, Outbox.text != EXPIRED,
        Outbox.status.in_(("sent", "failed", "cancelled")),
    ).order_by(Outbox.id).limit(batch_size)).all()
    for item in deliveries:
        item.text = EXPIRED
        item.buttons = []
    counts["outbox"] = len(deliveries)

    notes = session.scalars(select(TicketNote).where(
        TicketNote.created_at < cutoff, TicketNote.content != EXPIRED,
    ).order_by(TicketNote.id).limit(batch_size)).all()
    for item in notes:
        item.content = EXPIRED
    counts["notes"] = len(notes)

    drafts = session.scalars(select(OperatorDraft).where(
        OperatorDraft.created_at < cutoff, OperatorDraft.text != EXPIRED,
    ).order_by(OperatorDraft.id).limit(batch_size)).all()
    for item in drafts:
        item.text = EXPIRED
        if item.status == "suggested":
            item.status = "expired"
    counts["drafts"] = len(drafts)

    candidates = session.scalars(select(KnowledgeSuggestion).where(
        KnowledgeSuggestion.created_at < cutoff,
        KnowledgeSuggestion.question != EXPIRED,
    ).order_by(KnowledgeSuggestion.id).limit(batch_size)).all()
    for item in candidates:
        item.question = EXPIRED
        item.answer = EXPIRED
        if item.status == "pending":
            item.status = "expired"
    counts["suggestions"] = len(candidates)

    summaries = session.scalars(select(Ticket).where(
        Ticket.resolved_at < cutoff,
        Ticket.resolution_summary.is_not(None),
        Ticket.resolution_summary != EXPIRED,
    ).order_by(Ticket.id).limit(batch_size)).all()
    for ticket in summaries:
        ticket.resolution_summary = EXPIRED
    counts["ticket_summaries"] = len(summaries)
    candidates = session.scalars(select(InsightCandidate).where(
        InsightCandidate.created_at < cutoff, InsightCandidate.question != EXPIRED,
    ).order_by(InsightCandidate.id).limit(batch_size)).all()
    for item in candidates:
        item.question, item.answer = EXPIRED, EXPIRED
        item.digest = "expired"
        item.status = "expired"
    counts["insight_candidates"] = len(candidates)
    return counts
