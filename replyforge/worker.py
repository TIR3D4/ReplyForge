"""Durable event handling and once-at-most outbound delivery attempts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent import AIEngine
from .config import Settings, load_playbook
from .database import claim, session_scope
from .models import (
    Audit, BusinessConnection, Conversation, Event, Message, Outbox, Ticket, utcnow
)
from .security import redact
from .telegram import TelegramClient, TelegramError
from .workflow import (
    accept_input, apply_action, build_markup, callback_action
)

log = logging.getLogger(__name__)

REPLY_WINDOW = timedelta(hours=23, minutes=50)


def update_connection(session: Session, data: dict) -> BusinessConnection:
    connection_id = str(data["id"])
    conn = session.get(BusinessConnection, connection_id)
    if conn is None:
        conn = BusinessConnection(id=connection_id)
        session.add(conn)
    rights = data.get("rights") or {}
    conn.owner_user_id = (data.get("user") or {}).get("id")
    conn.enabled = bool(data.get("is_enabled", False))
    conn.can_reply = bool(rights.get("can_reply", data.get("can_reply", False)))
    conn.updated_at = utcnow()
    session.flush()
    return conn


def get_connection(session: Session, telegram: TelegramClient, connection_id: str) -> BusinessConnection:
    conn = session.get(BusinessConnection, connection_id)
    if conn is None:
        conn = update_connection(session, telegram.get_connection(connection_id))
    return conn


def get_conversation(session: Session, connection: BusinessConnection, chat_id: int) -> Conversation:
    conv = session.scalar(select(Conversation).where(
        Conversation.business_connection_id == connection.id, Conversation.chat_id == chat_id
    ).with_for_update())
    if conv is None:
        conv = Conversation(business_connection_id=connection.id, chat_id=chat_id, state={})
        session.add(conv)
        session.flush()
    return conv


def save_proposal(session: Session, conv: Conversation, proposal) -> None:
    if not proposal.text:
        return
    conv.revision += 1
    markup = build_markup(conv, proposal.actions) if proposal.menu and proposal.actions else None
    session.add(Outbox(
        conversation_id=conv.id,
        revision=conv.revision,
        kind="menu" if proposal.menu else "text",
        text=proposal.text[:4000],
        buttons=(markup or {}).get("inline_keyboard", []),
    ))


def record_inbound(session: Session, conv: Conversation, message: dict) -> bool:
    msg_id = message.get("message_id")
    if msg_id is None:
        return False
    if session.scalar(select(Message.id).where(
        Message.conversation_id == conv.id,
        Message.telegram_message_id == msg_id, Message.direction == "in",
    )) is not None:
        return False
    photo = (message.get("photo") or [])
    document = message.get("document") or {}
    file_id = photo[-1].get("file_id") if photo else (
        document.get("file_id") if str(document.get("mime_type", "")).startswith("image/") else None
    )
    text = message.get("text") or message.get("caption") or ""
    session.add(Message(
        conversation_id=conv.id, telegram_message_id=msg_id,
        direction="in", content=redact(text), kind="photo" if file_id else "text",
        data={"file_id": file_id} if file_id else {},
    ))
    conv.last_inbound_at = utcnow()
    return True


class Processor:
    def __init__(self, settings: Settings, factory, telegram: TelegramClient):
        self.settings = settings
        self.factory = factory
        self.telegram = telegram
        self.playbook = load_playbook(settings.business_config)

    def _agent(self, session: Session, conv: Conversation) -> AIEngine:
        """Create a chat-scoped model budget and audit every attempted model call."""
        def permit_call() -> bool:
            if not self.settings.ai_api_key:
                return False
            since = utcnow() - timedelta(days=1)
            used = session.scalar(select(func.count(Audit.id)).where(
                Audit.conversation_id == conv.id,
                Audit.action == "ai_call",
                Audit.created_at >= since,
            )) or 0
            if used >= self.settings.max_llm_calls_per_chat_per_day:
                return False
            session.add(Audit(conversation_id=conv.id, actor="system", action="ai_call"))
            session.flush()
            return True

        return AIEngine(self.settings, allow_call=permit_call)

    def _process_payload(self, session: Session, payload: dict) -> None:
        if "business_connection" in payload:
            update_connection(session, payload["business_connection"])
            return
        if "deleted_business_messages" in payload:
            deleted = payload["deleted_business_messages"]
            conn = session.get(BusinessConnection, deleted.get("business_connection_id", ""))
            if conn:
                conv = session.scalar(select(Conversation).where(
                    Conversation.business_connection_id == conn.id,
                    Conversation.chat_id == deleted.get("chat", {}).get("id"),
                ))
                if conv:
                    for mid in deleted.get("message_ids", []):
                        msg = session.scalar(select(Message).where(
                            Message.conversation_id == conv.id,
                            Message.telegram_message_id == mid,
                            Message.direction == "in",
                        ))
                        if msg:
                            msg.content = "[deleted]"
                            msg.data = {}
            return
        if "edited_business_message" in payload:
            edited = payload["edited_business_message"]
            conn_id = edited.get("business_connection_id")
            conv = session.scalar(select(Conversation).where(
                Conversation.business_connection_id == conn_id,
                Conversation.chat_id == edited.get("chat", {}).get("id"),
            ))
            if conv:
                msg = session.scalar(select(Message).where(
                    Message.conversation_id == conv.id,
                    Message.telegram_message_id == edited.get("message_id"),
                    Message.direction == "in",
                ))
                if msg:
                    msg.content = redact(edited.get("text") or edited.get("caption") or "")
            return

        callback = payload.get("callback_query")
        message = payload.get("business_message")
        if callback:
            message = callback.get("message") or {}
        if not message:
            return
        conn_id = message.get("business_connection_id")
        chat_id = (message.get("chat") or {}).get("id")
        if not conn_id or chat_id is None:
            return
        conn = get_connection(session, self.telegram, str(conn_id))
        if not conn.enabled:
            return
        conv = get_conversation(session, conn, int(chat_id))

        if callback:
            if (callback.get("from") or {}).get("id") != conv.chat_id:
                return
            if conv.owner != "ai" or conv.menu_message_id != message.get("message_id"):
                return
            action = callback_action(conv, str(callback.get("data") or ""))
            if action:
                proposal = apply_action(session, conv, self.playbook, self._agent(session, conv), self.settings, action)
                if conn.can_reply:
                    save_proposal(session, conv, proposal)
                    self._queue_operator_alert(session, conv)
            return

        # Telegram echoes messages created by the connected bot: never recurse.
        if message.get("sender_business_bot") is not None:
            return
        sender_id = (message.get("from") or {}).get("id")
        if conn.owner_user_id is not None and sender_id == conn.owner_user_id:
            conv.owner = "human"
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="owner", action="takeover"))
            return
        if not record_inbound(session, conv, message):
            return
        if conv.owner != "ai" or not conn.can_reply:
            return
        photo = message.get("photo") or []
        document = message.get("document") or {}
        file_id = photo[-1].get("file_id") if photo else (
            document.get("file_id") if str(document.get("mime_type", "")).startswith("image/") else None
        )
        text = message.get("text") or message.get("caption") or ""
        proposal = accept_input(session, conv, self.playbook, self._agent(session, conv), self.settings, text, file_id)
        save_proposal(session, conv, proposal)
        self._queue_operator_alert(session, conv)

    def _queue_operator_alert(self, session: Session, conv: Conversation) -> None:
        if not self.settings.support_alert_chat_id or conv.owner != "human_pending":
            return
        ticket = session.scalar(select(Ticket).where(
            Ticket.conversation_id == conv.id, Ticket.status == "open",
        ))
        if ticket:
            session.add(Outbox(
                conversation_id=conv.id, revision=conv.revision,
                kind="alert", text=f"🎧 ReplyForge ticket #{ticket.id}\n"
                f"Customer chat: {conv.chat_id}\n"
                f"Reason: {ticket.reason}\n"
                f"Review in /admin/conversations/{conv.id}",
                buttons=[],
            ))

    def process_event(self, update_id: int) -> None:
        with session_scope(self.factory) as session:
            event = session.get(Event, update_id)
            if not event or event.status != "processing":
                return
            self._process_payload(session, event.payload)
            event.status = "done"
            event.payload = {}  # short-lived inbound secrets never remain in event queue
            event.claimed_until = None

    def delivery(self, outbox_id: int):
        with session_scope(self.factory) as session:
            job = session.get(Outbox, outbox_id)
            if not job or job.status != "sending":
                return
            conv = session.get(Conversation, job.conversation_id)
            conn = session.get(BusinessConnection, conv.business_connection_id)
            is_alert = job.kind == "alert"
            if (conv.revision != job.revision or
                    (not is_alert and (not conn.enabled or not conn.can_reply
                    or not conv.last_inbound_at or (utcnow() - _aware(conv.last_inbound_at)) >= REPLY_WINDOW
                    or (conv.owner != "ai" and job.kind != "text")))):
                job.status = "cancelled"
                job.error_code = "obsolete_or_not_permitted"
                return
            connection_id = conn.id
            chat_id = conv.chat_id
            menu_id = conv.menu_message_id
            kind = job.kind
            markup = {"inline_keyboard": job.buttons} if job.buttons else None
            text = job.text

        try:
            message_id = None
            if kind == "alert":
                if self.settings.support_alert_chat_id is None:
                    raise TelegramError("operator_alert_not_configured", status=400)
                result = self.telegram.send_admin(self.settings.support_alert_chat_id, text)
                message_id = result["message_id"]
            elif kind == "menu" and menu_id:
                try:
                    self.telegram.edit(connection_id, chat_id, menu_id, text, markup=markup)
                    message_id = menu_id
                except TelegramError as exc:
                    if exc.status == 400 and "message is not modified" in exc.message.lower():
                        message_id = menu_id
                    elif exc.status == 400 and not exc.uncertain:
                        # Deleted/stale message: a fresh menu is safer than giving up.
                        result = self.telegram.send(connection_id, chat_id, text, markup)
                        message_id = result["message_id"]
                    else:
                        raise
            else:
                result = self.telegram.send(connection_id, chat_id, text, markup)
                message_id = result["message_id"]
        except TelegramError as exc:
            with session_scope(self.factory) as session:
                job = session.get(Outbox, outbox_id)
                if exc.retry_after and not exc.uncertain:
                    job.status = "pending"
                    job.available_at = utcnow() + timedelta(seconds=min(int(exc.retry_after) + 1, 300))
                else:
                    job.status = "uncertain" if exc.uncertain else "failed"
                job.error_code = "telegram_" + str(exc.status or "transport")
                job.claimed_until = None
            return
        except (KeyError, TypeError, ValueError):
            with session_scope(self.factory) as session:
                job = session.get(Outbox, outbox_id)
                job.status = "uncertain"
                job.error_code = "missing_message_confirmation"
            return

        with session_scope(self.factory) as session:
            job = session.get(Outbox, outbox_id)
            conv = session.get(Conversation, job.conversation_id)
            job.status = "sent"
            job.telegram_message_id = message_id
            job.claimed_until = None
            if kind == "menu" and conv.revision == job.revision:
                conv.menu_message_id = message_id
            if kind != "alert":
                session.add(Message(conversation_id=conv.id, telegram_message_id=None,
                                    direction="out", kind=kind, content=redact(text)))

    def tick(self) -> bool:
        with session_scope(self.factory) as session:
            ev = claim(session, Event, self.settings.lease_seconds)
            event_id = ev.update_id if ev else None
        if event_id is not None:
            try:
                self.process_event(event_id)
            except Exception:
                log.exception("Event processing failed (update_id=%s)", event_id)
                with session_scope(self.factory) as session:
                    ev = session.get(Event, event_id)
                    if ev and ev.status == "processing":
                        ev.claimed_until = None
                        if ev.attempts >= 5:
                            ev.status = "dead"
                            ev.payload = {}
                        else:
                            ev.status = "pending"
                            ev.available_at = utcnow() + timedelta(seconds=min(60, 2 ** ev.attempts))
            return True
        with session_scope(self.factory) as session:
            job = claim(session, Outbox, self.settings.lease_seconds)
            outbox_id = job.id if job else None
        if outbox_id is not None:
            self.delivery(outbox_id)
            return True
        return False

    def run(self):
        log.info("ReplyForge worker started")
        while True:
            if not self.tick():
                time.sleep(self.settings.poll_seconds)


def _aware(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
