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
    Audit, BusinessConnection, Conversation, Control, Event, Message, Outbox, Ticket, utcnow
)
from .security import redact
from .playbooks import effective_playbook
from .privacy import prune_history
from .telegram import TelegramClient, TelegramError
from .workflow import (
    Proposal, accept_input, apply_action, build_markup, callback_action, root_menu
)

log = logging.getLogger(__name__)

MAX_TEXT_BATCH = 8
MAX_BATCH_CHARACTERS = 2400

REPLY_WINDOW = timedelta(hours=23, minutes=50)


def auto_reply_enabled(session: Session, settings: Settings) -> bool:
    flag = session.get(Control, "auto_reply_enabled")
    return flag.value == "true" if flag else settings.auto_reply_enabled



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


def worker_is_alive(session: Session, *, max_age_seconds: int = 65) -> bool:
    flag = session.get(Control, "worker_heartbeat")
    if not flag:
        return False
    try:
        stamp = datetime.fromisoformat(flag.value)
        return (utcnow() - _aware(stamp)).total_seconds() <= max_age_seconds
    except (ValueError, TypeError):
        return False


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
        kind=("menu" if proposal.menu else
              "handoff" if conv.owner == "human_pending" else "text"),
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
    voice = message.get("voice") or message.get("audio") or {}
    if not file_id and isinstance(voice, dict):
        file_id = voice.get("file_id")
    kind = "voice" if voice else ("photo" if file_id else "text")
    text = message.get("text") or message.get("caption") or ""
    session.add(Message(
        conversation_id=conv.id, telegram_message_id=msg_id,
        direction="in", content=redact(text), kind=kind,
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

    def _process_payload(self, session: Session, payload: dict,
                         *, batch_messages: list[dict] | None = None) -> None:
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
        playbook, version = effective_playbook(session, self.playbook)
        prior = (conv.state or {}).get("_playbook_version")
        if conv.workflow and prior is not None and prior != version:
            conv.workflow, conv.step, conv.state = None, None, {}
            conv.revision += 1
            if conv.owner == "ai" and conn.can_reply:
                conv.state = {"_playbook_version": version}
                save_proposal(session, conv, root_menu(playbook))
            return

        if callback:
            if not auto_reply_enabled(session, self.settings):
                return
            if (callback.get("from") or {}).get("id") != conv.chat_id:
                return
            if conv.owner != "ai" or conv.menu_message_id != message.get("message_id"):
                return
            action = callback_action(conv, str(callback.get("data") or ""))
            if action:
                proposal = apply_action(session, conv, playbook, self._agent(session, conv), self.settings, action)
                if conn.can_reply:
                    conv.state = {**(conv.state or {}), "_playbook_version": version}
                    save_proposal(session, conv, proposal)
                    self._queue_operator_alert(session, conv)
            return

        # Telegram echoes messages created by the connected bot: never recurse.
        if message.get("sender_business_bot") is not None:
            return
        sender_id = (message.get("from") or {}).get("id")
        if conn.owner_user_id is not None and sender_id == conn.owner_user_id:
            # Capture human operator teaching examples without treating them as
            # customer inbound messages or reopening the reply window.
            msg_id = message.get("message_id")
            if msg_id is not None and session.scalar(select(Message.id).where(
                Message.conversation_id == conv.id,
                Message.telegram_message_id == msg_id,
                Message.direction == "out",
            )) is not None:
                return
            if msg_id is not None:
                session.add(Message(
                    conversation_id=conv.id, telegram_message_id=msg_id,
                    direction="out", kind="human",
                    content=redact(message.get("text") or message.get("caption") or ""),
                ))
            conv.owner = "human"
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="owner", action="takeover"))
            return
        if not record_inbound(session, conv, message):
            return
        # Persist each constituent message independently. Only the prompt/context
        # is combined; Telegram message IDs and attachments remain traceable.
        accepted_messages = [message]
        for item in batch_messages or []:
            if record_inbound(session, conv, item):
                accepted_messages.append(item)
        if conv.owner != "ai" or not conn.can_reply or not auto_reply_enabled(session, self.settings):
            if conv.owner in ("human", "human_pending"):
                self._queue_human_followup(session, conv, message)
            return
        photo = message.get("photo") or []
        document = message.get("document") or {}
        file_id = photo[-1].get("file_id") if photo else (
            document.get("file_id") if str(document.get("mime_type", "")).startswith("image/") else None
        )
        text = "\n".join(
            str(item.get("text") or item.get("caption") or "")
            for item in accepted_messages
        )[:MAX_BATCH_CHARACTERS]
        ai = self._agent(session, conv)
        voice = message.get("voice") or message.get("audio") or {}
        if isinstance(voice, dict) and voice.get("file_id"):
            try:
                data = self.telegram.download(str(voice["file_id"]), self.settings.media_max_bytes)
                transcript = ai.transcribe_voice(data)
            except (TelegramError, ValueError, TypeError, AttributeError):
                transcript = None
            if transcript:
                text = transcript
            else:
                proposal = Proposal(
                    "🎙 ویست دریافت شد. لطفاً مشکل رو متنی بنویس یا اپراتور رو انتخاب کن."
                    if playbook.get("locale") == "fa" else
                    "🎙 Voice received. Please type your question or choose human support.",
                    [("👨‍💻 اپراتور", "human"),
                     ("🏠 منو", "home")],
                )
                conv.state = {**(conv.state or {}), "_playbook_version": version}
                save_proposal(session, conv, proposal)
                return
        photo_expected = bool(
            conv.workflow and conv.step and
            playbook["workflows"].get(conv.workflow, {}).get("states", {})
                .get(conv.step, {}).get("input") == "photo"
        )
        # Financial/payment evidence is NEVER sent to third-party vision APIs.
        if (file_id and not photo_expected and conv.workflow == "connection"
                and self.settings.vision_enabled):
            try:
                content = self.telegram.download(str(file_id), self.settings.media_max_bytes)
                observation = ai.describe_screenshot(content)
            except (TelegramError, ValueError, TypeError, AttributeError):
                observation = None
            if observation:
                info = dict(conv.state or {})
                info["screenshot_clues"] = observation
                conv.state = info
                text = (text + "\n" if text else "") + "مشاهده از اسکرین‌شات: " + observation
        if file_id and not text and not photo_expected:
            proposal = Proposal(
                "📷 تصویر رو دریافت کردم. لطفاً بگو مربوط به کدوم مشکل هست یا موضوع رو از منو انتخاب کن."
                if playbook.get("locale") == "fa" else
                "📷 Image received. Tell me what went wrong or select a menu option.",
                [("🏠 منوی اصلی", "home"), ("👨‍💻 اپراتور", "human")],
            )
        else:
            proposal = accept_input(session, conv, playbook, ai, self.settings, text, file_id)
        conv.state = {**(conv.state or {}), "_playbook_version": version}
        save_proposal(session, conv, proposal)
        self._queue_operator_alert(session, conv)

    def _queue_human_followup(self, session: Session, conv: Conversation, message: dict) -> None:
        """Notify an already-assigned human if new evidence arrived."""
        ticket = session.scalar(select(Ticket).where(
            Ticket.conversation_id == conv.id,
            Ticket.status.in_(("open", "in_progress")),
        ).order_by(Ticket.id.desc()).limit(1))
        if ticket is not None:
            ticket.last_customer_at = utcnow()
            ticket.updated_at = utcnow()
        if not self.settings.support_alert_chat_id:
            return
        photo = message.get("photo") or []
        doc = message.get("document") or {}
        file_id = (photo[-1].get("file_id") if photo else
                   (doc.get("file_id") if str(doc.get("mime_type", "")).startswith("image/")
                    else None))
        if file_id:
            session.add(Outbox(
                conversation_id=conv.id, revision=conv.revision,
                kind="alert_photo", text="📎 New evidence in support chat " + str(conv.chat_id),
                buttons=[{"file_id": file_id}],
            ))
        info = dict(conv.state or {})
        previous = info.get("human_update_alert_at")
        try:
            last_time = datetime.fromisoformat(previous) if previous else None
        except (ValueError, TypeError):
            last_time = None
        if last_time is not None and last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        if last_time is None or (utcnow() - last_time) >= timedelta(seconds=90):
            session.add(Outbox(
                conversation_id=conv.id, revision=conv.revision,
                kind="alert", text="💬 Customer " + str(conv.chat_id) +
                " added a message to a human-owned support conversation.",
                buttons=[],
            ))
            info["human_update_alert_at"] = utcnow().isoformat()
            conv.state = info

    def _queue_operator_alert(self, session: Session, conv: Conversation) -> None:
        if not self.settings.support_alert_chat_id or conv.owner != "human_pending":
            return
        ticket = session.scalar(select(Ticket).where(
            Ticket.conversation_id == conv.id,
            Ticket.status.in_(("open", "in_progress")),
        ))
        if ticket:
            session.add(Outbox(
                conversation_id=conv.id, revision=conv.revision,
                kind="alert", text=f"🎧 ReplyForge ticket #{ticket.id}\n"
                f"Customer chat: {conv.chat_id}\n"
                f"Reason: {ticket.reason} | Priority: {ticket.priority}\n"
                f"Review in /admin/conversations/{conv.id}",
                buttons=[],
            ))
            from_date = (conv.state or {}).get("flow_started_at")
            try:
                boundary = datetime.fromisoformat(from_date) if from_date else utcnow() - timedelta(minutes=10)
            except (ValueError, TypeError):
                boundary = utcnow() - timedelta(minutes=10)
            if boundary.tzinfo is None:
                boundary = boundary.replace(tzinfo=timezone.utc)
            # Limit evidence to images shared during this workflow, not historical files.
            evidence = session.scalars(select(Message).where(
                Message.conversation_id == conv.id, Message.direction == "in",
                Message.kind == "photo", Message.created_at >= boundary,
            ).order_by(Message.id.desc()).limit(3)).all()
            for index, message in enumerate(reversed(evidence), 1):
                file_id = (message.data or {}).get("file_id")
                if file_id:
                    session.add(Outbox(
                        conversation_id=conv.id, revision=conv.revision,
                        kind="alert_photo", text=f"📎 Evidence {index} for ticket #{ticket.id}",
                        buttons=[{"file_id": file_id}],
                    ))

    @staticmethod
    def _batchable(msg: dict) -> bool:
        return (isinstance(msg, dict) and isinstance(msg.get("text"), str)
                and bool(msg["text"].strip()) and isinstance(msg.get("from"), dict)
                and isinstance(msg["from"].get("id"), int)
                and not any(msg.get(k) for k in (
                    "voice", "audio", "photo", "document", "video",
                    "sender_business_bot",
                )))

    def process_event(self, update_id: int) -> None:
        with session_scope(self.factory) as session:
            event = session.get(Event, update_id)
            if not event or event.status != "processing":
                return
            source = event.payload.get("business_message")
            merged: list[Event] = []
            combined: list[dict] = []
            if self.settings.message_debounce_ms and self._batchable(source):
                key = (source.get("business_connection_id"),
                       (source.get("chat") or {}).get("id"),
                       source["from"]["id"])
                conn = session.get(BusinessConnection, key[0])
                # Owner-authored replies must each be processed as takeover,
                # never coalesced with a customer message or discarded.
                if key[2] != (conn.owner_user_id if conn else None):
                    next_events = session.scalars(select(Event).where(
                        Event.status == "pending",
                        Event.update_id > update_id,
                    ).order_by(Event.update_id).limit(MAX_TEXT_BATCH).with_for_update(
                        skip_locked=True,
                    )).all()
                    total = len(source["text"])
                    for next_event in next_events:
                        incoming = (next_event.payload or {}).get("business_message")
                        if not self._batchable(incoming):
                            break
                        actual = (incoming.get("business_connection_id"),
                                  (incoming.get("chat") or {}).get("id"),
                                  incoming["from"]["id"])
                        count = len(incoming["text"])
                        if actual != key or total + count > MAX_BATCH_CHARACTERS:
                            break  # Preserve event ordering across customers/media.
                        merged.append(next_event)
                        combined.append(incoming)
                        total += count
                        if len(merged) >= MAX_TEXT_BATCH - 1:
                            break
            self._process_payload(session, event.payload, batch_messages=combined)
            for completed in [event, *merged]:
                completed.status = "done"
                completed.payload = {}  # never retain raw subscription links in a completed event
                completed.claimed_until = None

    def delivery(self, outbox_id: int):
        with session_scope(self.factory) as session:
            job = session.get(Outbox, outbox_id)
            if not job or job.status != "sending":
                return
            conv = session.get(Conversation, job.conversation_id)
            conn = session.get(BusinessConnection, conv.business_connection_id)
            is_alert = job.kind in ("alert", "alert_photo")
            recent_inbound = bool(conv.last_inbound_at and
                                  utcnow() - _aware(conv.last_inbound_at) < REPLY_WINDOW)
            if job.kind == "human":
                correct_owner = conv.owner == "human"
            elif job.kind == "handoff":
                correct_owner = conv.owner == "human_pending"
            else:
                correct_owner = conv.owner == "ai" and auto_reply_enabled(session, self.settings)
            permitted = is_alert or (
                conn.enabled and conn.can_reply and recent_inbound and correct_owner
            )
            # AI drafts are revision-fenced; intentionally queued human messages
            # are independent commands and must NOT erase each other when the
            # operator types twice before the worker flushes the outbox.
            revision_stale = job.kind != "human" and conv.revision != job.revision
            if revision_stale or not permitted:
                job.status = "cancelled"
                job.error_code = "obsolete_or_not_permitted"
                return
            if job.kind == "human":
                older = session.scalar(select(Outbox.id).where(
                    Outbox.conversation_id == conv.id,
                    Outbox.kind == "human",
                    Outbox.id < job.id,
                    Outbox.status.in_(("pending", "sending", "uncertain")),
                ).order_by(Outbox.id).limit(1))
                if older is not None:
                    # Preserve per-chat operator message ordering even after a
                    # Telegram rate limit or unknown delivery outcome.
                    job.status = "pending"
                    job.available_at = utcnow() + timedelta(seconds=5)
                    job.claimed_until = None
                    job.error_code = "waiting_for_previous_operator_reply"
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
            elif kind == "alert_photo":
                if self.settings.support_alert_chat_id is None:
                    raise TelegramError("operator_alert_not_configured", status=400)
                file_id = (job.buttons or [{}])[0].get("file_id")
                if not file_id:
                    raise TelegramError("missing_photo_id", status=400)
                result = self.telegram.send_photo_admin(self.settings.support_alert_chat_id, file_id, text)
                message_id = result["message_id"]
            elif kind in ("menu", "handoff") and menu_id:
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
            if kind in ("menu", "handoff") and conv.revision == job.revision:
                conv.menu_message_id = message_id
            if kind not in ("alert", "alert_photo"):
                session.add(Message(conversation_id=conv.id, telegram_message_id=None,
                                    direction="out", kind=kind, content=redact(text)))

    def check_sla(self) -> bool:
        """Escalate overdue, unanswered tickets at most once."""
        with session_scope(self.factory) as session:
            now = utcnow()
            ticket = session.scalar(select(Ticket).where(
                Ticket.status.in_(("open", "in_progress")),
                Ticket.first_response_at.is_(None),
                Ticket.escalated_at.is_(None),
                Ticket.sla_due_at.is_not(None),
                Ticket.sla_due_at <= now,
            ).order_by(Ticket.sla_due_at, Ticket.id).limit(1).with_for_update(
                skip_locked=True,
            ))
            if ticket is None:
                return False
            ticket.escalated_at = now
            ticket.priority = "urgent"
            ticket.updated_at = now
            session.add(Audit(
                conversation_id=ticket.conversation_id, actor="system",
                action="ticket_sla_escalation", detail=str(ticket.id),
            ))
            if self.settings.support_alert_chat_id:
                conv = session.get(Conversation, ticket.conversation_id)
                session.add(Outbox(
                    conversation_id=ticket.conversation_id,
                    revision=conv.revision,
                    kind="alert",
                    text=f"🚨 Support SLA breached: ticket #{ticket.id} "
                         f"(chat {conv.chat_id}, reason {ticket.reason}). "
                         f"Review /admin/conversations/{conv.id}",
                    buttons=[],
                ))
            return True

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
        return self.check_sla()

    def heartbeat(self) -> None:
        with session_scope(self.factory) as session:
            row = session.get(Control, "worker_heartbeat")
            if row is None:
                session.add(Control(key="worker_heartbeat", value=utcnow().isoformat()))
            else:
                row.value = utcnow().isoformat()
                row.updated_at = utcnow()

    def run(self):
        log.info("ReplyForge worker started")
        next_heartbeat = 0.0
        next_privacy_sweep = 0.0
        while True:
            now = time.monotonic()
            if now >= next_heartbeat:
                self.heartbeat()
                next_heartbeat = now + 15
            if now >= next_privacy_sweep:
                try:
                    with session_scope(self.factory) as db:
                        counts = prune_history(db, self.settings.retention_days)
                    if any(counts.values()):
                        log.info("Privacy retention scrub complete: %s", counts)
                except Exception:
                    log.exception("Privacy retention scrub failed")
                next_privacy_sweep = now + 6 * 3600
            if not self.tick():
                time.sleep(self.settings.poll_seconds)


def _aware(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
