"""Persistence schema. Existing deployments must apply reviewed migrations on upgrades."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class BusinessConnection(Base):
    __tablename__ = "business_connections"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("business_connection_id", "chat_id", name="uq_business_chat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), ForeignKey("business_connections.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner: Mapped[str] = mapped_column(String(24), default="ai", nullable=False)
    workflow: Mapped[str | None] = mapped_column(String(100))
    step: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    menu_message_id: Mapped[int | None] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Event(Base):
    __tablename__ = "incoming_events"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "telegram_message_id", "direction", name="uq_conversation_message"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"), nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="menu")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    buttons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(100))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    reason: Mapped[str] = mapped_column(String(100), default="manual")
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    priority: Mapped[str] = mapped_column(String(12), default="normal", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(100))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_customer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class TicketNote(Base):
    """Internal notes are strictly private; no Telegram send is generated."""
    __tablename__ = "ticket_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id"), nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Knowledge(Base):
    __tablename__ = "knowledge"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Binding(Base):
    __tablename__ = "subscription_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_hmac: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    user_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="")
    customer_chat_id: Mapped[int | None] = mapped_column(BigInteger)

class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("conversations.id"))
    actor: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

Index("idx_event_queue", Event.status, Event.available_at)
Index("idx_outbox_queue", Outbox.status, Outbox.available_at)
Index("idx_tickets_status", Ticket.status, Ticket.created_at)
Index("idx_tickets_sla", Ticket.status, Ticket.first_response_at, Ticket.sla_due_at)
Index("idx_ticket_notes", TicketNote.ticket_id, TicketNote.created_at)


class PlaybookVersion(Base):
    __tablename__ = "playbook_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Control(Base):
    """Runtime automation flags; never store credentials here."""
    __tablename__ = "controls"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
