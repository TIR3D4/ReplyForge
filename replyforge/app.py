"""FastAPI webhook ingestion, internal provisioning API and operator dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import hmac
from datetime import timedelta
from copy import deepcopy
import yaml
from pathlib import Path

from fastapi import (
    Body, Depends, FastAPI, Form, Header, HTTPException, Request
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, desc, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from .http_security import RequestBoundary
from .config import ConfigError, Settings, load_playbook
from .database import session_factory, session_scope
from .agent import AIEngine
from .models import (
    Audit, Binding, BusinessConnection, Control, Conversation, Event, Knowledge, KnowledgeSuggestion, Message, Outbox, Ticket, TicketNote, OperatorDraft, utcnow
)
from .security import constant_time_equal, fingerprint, redact, subscription_token_fingerprint
from .playbooks import active_version, activate_version, effective_playbook, save_playbook
from .models import PlaybookVersion
from .telegram import TelegramClient, TelegramError
from .worker import REPLY_WINDOW, _aware, auto_reply_enabled, worker_is_alive

basic = HTTPBasic()
templates = Jinja2Templates(directory="templates")


class LinkRequest(BaseModel):
    link: str = Field(min_length=4, max_length=2048)
    provider: str
    user_ref: str = Field(min_length=1, max_length=255)
    label: str = Field(default="", max_length=255)
    customer_chat_id: int | None = None


def build_app(config: Settings | None = None, *, factory=None, telegram=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(instance: FastAPI):
        s = config or Settings.from_env()
        playbook = load_playbook(s.business_config)
        engine = None
        sf = factory
        if sf is None:
            engine, sf = session_factory(s.database_url)
        instance.state.settings = s
        instance.state.factory = sf
        instance.state.playbook = playbook
        instance.state.telegram = telegram or TelegramClient(s.bot_token)
        try:
            yield
        finally:
            if telegram is None:
                instance.state.telegram.close()
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="ReplyForge", version="1.1.0rc1", docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestBoundary)

    def secret_token(request: Request):
        return request.app.state.settings.binding_pepper

    def authenticate(request: Request, credentials: HTTPBasicCredentials = Depends(basic)):
        s = request.app.state.settings
        good_user = constant_time_equal(s.admin_username, credentials.username)
        good_password = constant_time_equal(s.admin_password, credentials.password)
        if not (good_user and good_password):
            raise HTTPException(status_code=401, detail="Invalid credentials",
                                headers={"WWW-Authenticate": "Basic"})
        return credentials.username

    def csrf(request: Request, submitted: str):
        expected = hmac.new(secret_token(request).encode(), b"replyforge-admin-csrf", hashlib.sha256).hexdigest()
        if not constant_time_equal(expected, submitted):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

    def csrf_value(request: Request) -> str:
        return hmac.new(secret_token(request).encode(), b"replyforge-admin-csrf", hashlib.sha256).hexdigest()

    def require_internal(request: Request, provided: str | None):
        expected = request.app.state.settings.internal_api_key
        if not provided or not constant_time_equal(expected, provided):
            raise HTTPException(status_code=403, detail="Forbidden")

    @app.get("/healthz")
    def healthz(request: Request):
        with session_scope(request.app.state.factory) as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok", "service": "replyforge"}

    @app.get("/readyz")
    def readyz(request: Request):
        with session_scope(request.app.state.factory) as session:
            session.execute(text("SELECT 1"))
            ready = worker_is_alive(session)
            pending = session.scalar(select(func.count(Event.update_id)).where(
                Event.status.in_(("pending", "processing")))) or 0
            dead = session.scalar(select(func.count(Event.update_id)).where(
                Event.status == "dead")) or 0
        return JSONResponse({"status": "ready" if ready else "degraded",
                             "worker": "alive" if ready else "stale_or_missing",
                             "pending_updates": pending, "dead_updates": dead},
                            status_code=200 if ready else 503)

    @app.post("/telegram/webhook")
    def telegram_webhook(request: Request, payload: dict = Body(...),
                         telegram_secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token")):
        s = request.app.state.settings
        if s.webhook_path != "/telegram/webhook":
            raise HTTPException(status_code=500, detail="Configured webhook path mismatch")
        if telegram_secret is None or not constant_time_equal(s.webhook_secret, telegram_secret):
            raise HTTPException(status_code=403, detail="Forbidden")
        update_id = payload.get("update_id")
        if type(update_id) is not int or update_id < 0:
            raise HTTPException(status_code=400, detail="Invalid update_id")
        try:
            with session_scope(request.app.state.factory) as session:
                if session.get(Event, update_id) is None:
                    # Hold a short burst before intent classification. All inbound
                    # Business updates share the delay to preserve event order.
                    delay_ms = s.message_debounce_ms if "business_message" in payload else 0
                    session.add(Event(
                        update_id=update_id, payload=payload,
                        available_at=utcnow() + timedelta(milliseconds=delay_ms),
                    ))
        except IntegrityError:
            pass  # Concurrent duplicate delivery, unique update_id already committed.
        callback = payload.get("callback_query") or {}
        if callback.get("id"):
            try:
                request.app.state.telegram.answer_callback(str(callback["id"]))
            except Exception:
                pass  # Never prevent durable ingestion because Telegram ack failed.
        return {"ok": True}

    @app.post("/api/bindings")
    def create_binding(request: Request, data: LinkRequest,
                       internal_key: str | None = Header(default=None, alias="X-Internal-Api-Key")):
        require_internal(request, internal_key)
        if data.provider not in ("marzban", "pasarguard"):
            raise HTTPException(status_code=422, detail="Provider must be marzban or pasarguard")
        if data.provider == "pasarguard" and not data.user_ref.isdecimal():
            raise HTTPException(status_code=422, detail="Pasarguard requires numeric user ID")
        digest = fingerprint(data.link, request.app.state.settings.binding_pepper)
        token_hmac = subscription_token_fingerprint(
            data.link, request.app.state.settings.binding_pepper)
        with session_scope(request.app.state.factory) as session:
            existing = session.scalar(select(Binding).where(Binding.link_hmac == digest))
            if existing is None:
                existing = Binding(link_hmac=digest, token_hmac=token_hmac, provider=data.provider,
                                   user_ref=data.user_ref, label=data.label,
                                   customer_chat_id=data.customer_chat_id)
                session.add(existing)
            else:
                existing.provider, existing.user_ref = data.provider, data.user_ref
                existing.token_hmac = token_hmac
                existing.label, existing.customer_chat_id = data.label, data.customer_chat_id
            session.flush()
            return {"id": existing.id, "provider": existing.provider, "saved": True}

    @app.get("/admin", response_class=HTMLResponse)
    def dashboard(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            data = {
                "conversations": session.scalars(select(Conversation).order_by(desc(Conversation.id)).limit(40)).all(),
                "tickets": session.scalars(select(Ticket).order_by(desc(Ticket.id)).limit(40)).all(),
                "knowledge": session.scalars(select(Knowledge).order_by(desc(Knowledge.id)).limit(40)).all(),
                "bindings": session.scalars(select(Binding).order_by(desc(Binding.id)).limit(40)).all(),
                "uncertain": session.scalars(select(Outbox).where(Outbox.status == "uncertain").order_by(desc(Outbox.id)).limit(20)).all(),
                "total_conversations": session.scalar(select(func.count(Conversation.id))),
                "open_tickets": session.scalar(select(func.count(Ticket.id)).where(
                    Ticket.status.in_(("open", "in_progress")))),
                "overdue_tickets": session.scalar(select(func.count(Ticket.id)).where(
                    Ticket.status.in_(("open", "in_progress")),
                    Ticket.first_response_at.is_(None),
                    Ticket.sla_due_at < utcnow(),
                )) or 0,
                "urgent_tickets": session.scalar(select(func.count(Ticket.id)).where(
                    Ticket.status.in_(("open", "in_progress")),
                    Ticket.priority == "urgent",
                )) or 0,
                "sent_messages": session.scalar(select(func.count(Outbox.id)).where(Outbox.status == "sent")),
                "pending_messages": session.scalar(select(func.count(Outbox.id)).where(Outbox.status.in_(("pending", "sending")))),
                "auto_reply_enabled": auto_reply_enabled(session, request.app.state.settings),
                "worker_alive": worker_is_alive(session),
                "dead_updates": session.scalar(select(func.count(Event.update_id)).where(
                    Event.status == "dead")) or 0,
                "pending_learning": session.scalar(select(func.count(KnowledgeSuggestion.id)).where(
                    KnowledgeSuggestion.status == "pending")) or 0,
                "positive_feedback": session.scalar(select(func.count(Audit.id)).where(
                    Audit.action == "feedback_positive")) or 0,
                "negative_feedback": session.scalar(select(func.count(Audit.id)).where(
                    Audit.action == "feedback_negative")) or 0,
            }
            current, revision = effective_playbook(session, request.app.state.playbook)
            return templates.TemplateResponse(request, "dashboard.html", {
                **data, "brand": current["brand"],
                "locale": current.get("locale", "en"),
                "playbook_version": revision,
                "csrf": csrf_value(request),
                "_": lambda en, fa: fa if current.get("locale") == "fa" else en,
            })


    @app.get("/admin/tickets", response_class=HTMLResponse)
    def ticket_queue(
        request: Request, ticket_status: str = "open", priority: str = "all",
        search: str = "", page: int = 1, _=Depends(authenticate),
    ):
        if ticket_status not in ("open", "in_progress", "closed", "all"):
            raise HTTPException(422, detail="Invalid ticket status")
        if priority not in ("all", "low", "normal", "high", "urgent"):
            raise HTTPException(422, detail="Invalid priority")
        if not 1 <= page <= 1000 or len(search) > 64:
            raise HTTPException(422, detail="Invalid page or search")
        with session_scope(request.app.state.factory) as session:
            conditions = []
            if ticket_status == "open":
                conditions.append(Ticket.status.in_(("open", "in_progress")))
            elif ticket_status != "all":
                conditions.append(Ticket.status == ticket_status)
            if priority != "all":
                conditions.append(Ticket.priority == priority)
            if search.strip():
                phrase = search.strip()
                if phrase.isdecimal():
                    conditions.append(or_(Ticket.id == int(phrase),
                        Ticket.conversation_id.in_(select(Conversation.id).where(
                            Conversation.chat_id == int(phrase)))))
                else:
                    conditions.append(Ticket.reason.ilike("%" + phrase + "%"))
            count = session.scalar(select(func.count(Ticket.id)).where(*conditions)) or 0
            priority_order = case(
                (Ticket.priority == "urgent", 0),
                (Ticket.priority == "high", 1),
                (Ticket.priority == "normal", 2),
                else_=3,
            )
            tickets = session.scalars(select(Ticket).where(*conditions).order_by(
                priority_order, Ticket.sla_due_at, desc(Ticket.created_at),
            ).offset((page - 1) * 30).limit(30)).all()
            conv_map = {c.id: c for c in session.scalars(
                select(Conversation).where(
                    Conversation.id.in_([t.conversation_id for t in tickets])
                )).all()} if tickets else {}
            current, _version = effective_playbook(session, request.app.state.playbook)
            return templates.TemplateResponse(request, "tickets.html", {
                "tickets": tickets, "count": count, "page": page,
                "pages": max(1, (count + 29) // 30),
                "ticket_status": ticket_status, "priority": priority,
                "search": search, "conv_map": conv_map,
                "csrf": csrf_value(request), "locale": current.get("locale", "en"),
                "now": utcnow(),
            })

    @app.post("/admin/tickets/{ticket_id}/triage")
    def update_ticket_triage(
        request: Request, ticket_id: int, csrf_token: str = Form(...),
        priority: str = Form(...), category: str = Form("general"),
        assignee: str = Form(""), status_value: str = Form("open"),
        _=Depends(authenticate),
    ):
        csrf(request, csrf_token)
        if (priority not in ("low", "normal", "high", "urgent")
                or status_value not in ("open", "in_progress")
                or not category.strip() or len(category) > 50 or len(assignee) > 100):
            raise HTTPException(422, detail="Invalid ticket metadata")
        with session_scope(request.app.state.factory) as session:
            ticket = session.scalar(select(Ticket).where(
                Ticket.id == ticket_id).with_for_update())
            if ticket is None:
                raise HTTPException(404, detail="Ticket not found")
            if ticket.status == "closed":
                raise HTTPException(409, detail="Reopen the ticket before triaging")
            ticket.priority = priority
            ticket.category = category.strip()
            ticket.assignee = assignee.strip() or None
            ticket.status = status_value
            ticket.updated_at = utcnow()
            if status_value == "in_progress":
                conv = session.get(Conversation, ticket.conversation_id)
                if conv.owner != "human":
                    conv.owner = "human"
                    conv.revision += 1
            session.add(Audit(conversation_id=ticket.conversation_id,
                              actor="operator", action="ticket_triage",
                              detail=str(ticket.id) + ":" + status_value + ":" + priority))
        return RedirectResponse("/admin/tickets", status_code=303)

    @app.post("/admin/tickets/{ticket_id}/notes")
    def add_ticket_note(request: Request, ticket_id: int,
                        content: str = Form(...), csrf_token: str = Form(...),
                        operator: str = Depends(authenticate)):
        csrf(request, csrf_token)
        if not content.strip() or len(content) > 2000:
            raise HTTPException(422, detail="Note must be 1–2000 characters")
        with session_scope(request.app.state.factory) as session:
            ticket = session.get(Ticket, ticket_id)
            if ticket is None:
                raise HTTPException(404, detail="Ticket not found")
            session.add(TicketNote(
                ticket_id=ticket_id, author=operator, content=redact(content.strip()),
            ))
            ticket.updated_at = utcnow()
            session.add(Audit(conversation_id=ticket.conversation_id, actor="operator",
                              action="ticket_private_note", detail=str(ticket_id)))
            conversation_id = ticket.conversation_id
        return RedirectResponse("/admin/conversations/" + str(conversation_id),
                                status_code=303)

    @app.post("/admin/tickets/{ticket_id}/reopen")
    def reopen_ticket(request: Request, ticket_id: int,
                      csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            ticket = session.get(Ticket, ticket_id)
            if ticket is None:
                raise HTTPException(404, detail="Ticket not found")
            if ticket.status != "closed":
                raise HTTPException(409, detail="Ticket is already active")
            current, _revision = effective_playbook(session, request.app.state.playbook)
            sla = current.get("support_sla_minutes", 60)
            minutes = sla if type(sla) is int and 5 <= sla <= 1440 else 60
            ticket.status = "open"
            ticket.first_response_at = None
            ticket.resolved_at = None
            ticket.escalated_at = None
            ticket.sla_due_at = utcnow() + timedelta(minutes=minutes)
            ticket.updated_at = utcnow()
            conv = session.get(Conversation, ticket.conversation_id)
            conv.owner = "human_pending"
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="operator",
                              action="ticket_reopen", detail=str(ticket.id)))
        return RedirectResponse("/admin/tickets", status_code=303)

    @app.get("/admin/conversations/{conversation_id}", response_class=HTMLResponse)
    def conversation_detail(request: Request, conversation_id: int, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id, with_for_update=True)
            if conv is None:
                raise HTTPException(404)
            messages = session.scalars(select(Message).where(
                Message.conversation_id == conversation_id,
            ).order_by(Message.id.desc()).limit(100)).all()
            outbound = session.scalars(select(Outbox).where(Outbox.conversation_id == conversation_id,
                Outbox.kind == "human").order_by(Outbox.id.desc()).limit(20)).all()
            current, _version = effective_playbook(session, request.app.state.playbook)
            draft = session.scalar(select(OperatorDraft).where(
                OperatorDraft.conversation_id == conv.id,
                OperatorDraft.status == "suggested",
            ).order_by(desc(OperatorDraft.id)).limit(1))
            ticket = session.scalar(select(Ticket).where(
                Ticket.conversation_id == conv.id,
            ).order_by(desc(Ticket.id)).limit(1))
            notes = session.scalars(select(TicketNote).where(
                TicketNote.ticket_id == ticket.id,
            ).order_by(desc(TicketNote.id)).limit(60)).all() if ticket else []
            return templates.TemplateResponse(request, "conversation.html", {
                "conv": conv, "messages": list(reversed(messages)), "outbound": outbound,
                "ticket": ticket, "notes": notes, "draft": draft,
                "csrf": csrf_value(request),
                "locale": current.get("locale", "en"),
                "_": lambda en, fa: fa if current.get("locale") == "fa" else en,
            })


    @app.get("/admin/playbook", response_class=HTMLResponse)
    def playbook_editor(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            live = active_version(session)
            source = live.source if live else Path(
                request.app.state.settings.business_config,
            ).read_text(encoding="utf-8")
            current, version = effective_playbook(session, request.app.state.playbook)
            revisions = session.scalars(select(PlaybookVersion).order_by(
                desc(PlaybookVersion.id),
            ).limit(25)).all()
            return templates.TemplateResponse(request, "playbook.html", {
                "source": source, "brand": current["brand"],
                "version": version, "revisions": revisions,
                "csrf": csrf_value(request), "locale": current.get("locale", "en"),
                "config": current, "flow_names": list(current.get("workflows", {})),
            })

    @app.post("/admin/playbook/basic")
    def quick_customize(request: Request, csrf_token: str = Form(...),
                        brand: str = Form(...), locale: str = Form(...),
                        welcome: str = Form(...), handoff_text: str = Form(...),
                        resolution_text: str = Form(...),
                        menu_label: list[str] = Form(...),
                        menu_action: list[str] = Form(...),
                        _=Depends(authenticate)):
        csrf(request, csrf_token)
        if (locale not in ("fa", "en") or len(brand) > 100
                or len(welcome) > 1200 or len(handoff_text) > 1200
                or len(resolution_text) > 1200 or len(menu_label) > 12
                or len(menu_label) != len(menu_action)):
            raise HTTPException(422, detail="Invalid quick configuration")
        with session_scope(request.app.state.factory) as session:
            current, _version = effective_playbook(session, request.app.state.playbook)
            custom = deepcopy(current)
            items = []
            for label, action in zip(menu_label, menu_action):
                label = label.strip()
                if label:
                    if len(label) > 80 or len(action) > 100:
                        raise HTTPException(422, detail="Invalid menu item")
                    items.append({"label": label, "action": action})
            if not items:
                raise HTTPException(422, detail="At least one menu button is required")
            custom.update({
                "brand": brand.strip(), "locale": locale, "welcome": welcome.strip(),
                "handoff_text": handoff_text.strip(),
                "resolution_text": resolution_text.strip(), "menu": items,
            })
            try:
                version = save_playbook(session, yaml.safe_dump(
                    custom, allow_unicode=True, sort_keys=False,
                ))
                session.add(Audit(actor="admin", action="playbook_quick_edit",
                                  detail=str(version.id)))
            except (ConfigError, ValueError) as exc:
                raise HTTPException(422, detail=str(exc)) from exc
        return RedirectResponse("/admin/playbook", status_code=303)

    @app.post("/admin/playbook")
    def update_playbook(request: Request, source: str = Form(...), csrf_token: str = Form(...),
                        _=Depends(authenticate)):
        csrf(request, csrf_token)
        try:
            with session_scope(request.app.state.factory) as session:
                entry = save_playbook(session, source)
                session.add(Audit(actor="admin", action="playbook_update", detail=str(entry.id)))
        except (ConfigError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RedirectResponse("/admin/playbook", status_code=303)

    @app.post("/admin/playbook/{version_id}/activate")
    def restore_playbook(request: Request, version_id: int, csrf_token: str = Form(...),
                         _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            if not activate_version(session, version_id):
                raise HTTPException(status_code=404, detail="Unknown version")
            session.add(Audit(actor="admin", action="playbook_restore", detail=str(version_id)))
        return RedirectResponse("/admin/playbook", status_code=303)

    @app.get("/admin/media/{message_id}")
    def operator_media(request: Request, message_id: int, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            message = session.get(Message, message_id)
            file_id = (message.data or {}).get("file_id") if message else None
        if not file_id:
            raise HTTPException(status_code=404, detail="Media is not available")
        try:
            data = request.app.state.telegram.download(
                str(file_id), request.app.state.settings.media_max_bytes)
        except (TelegramError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="Telegram media unavailable") from exc
        if data.startswith(bytes.fromhex("ffd8ff")):
            mime = "image/jpeg"
        elif data.startswith(bytes.fromhex("89504e470d0a1a0a")):
            mime = "image/png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        elif data[:4] == b"OggS":
            mime = "audio/ogg"
        else:
            raise HTTPException(status_code=415, detail="Unsupported media format")
        return Response(content=data, media_type=mime, headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        })

    @app.post("/admin/automation")
    def automation_toggle(request: Request, enabled: str = Form(...),
                          csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if enabled not in ("true", "false"):
            raise HTTPException(status_code=422, detail="Invalid automation state")
        with session_scope(request.app.state.factory) as session:
            flag = session.get(Control, "auto_reply_enabled")
            if flag is None:
                session.add(Control(key="auto_reply_enabled", value=enabled))
            else:
                flag.value = enabled
                flag.updated_at = utcnow()
            session.add(Audit(actor="admin", action="automation_toggle", detail=enabled))
        return RedirectResponse("/admin", status_code=303)


    @app.post("/admin/conversations/{conversation_id}/suggest")
    def suggest_operator_reply(
        request: Request, conversation_id: int,
        csrf_token: str = Form(...), _=Depends(authenticate),
    ):
        """Operator-only, cost-bounded draft; deliberately never sends to Telegram."""
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id, with_for_update=True)
            if conv is None:
                raise HTTPException(404, detail="Conversation not found")
            history = list(reversed(session.scalars(select(Message).where(
                Message.conversation_id == conversation_id,
            ).order_by(desc(Message.id)).limit(12)).all()))
            knowledge = session.scalars(select(Knowledge).where(
                Knowledge.enabled.is_(True),
            ).order_by(Knowledge.id).limit(50)).all()
            ticket = session.scalar(select(Ticket).where(
                Ticket.conversation_id == conversation_id,
                Ticket.status.in_(("open", "in_progress")),
            ).order_by(desc(Ticket.id)).limit(1))
            locale = effective_playbook(
                session, request.app.state.playbook,
            )[0].get("locale", "en")
            settings = request.app.state.settings

            def allow_call():
                if not settings.ai_api_key:
                    return False
                cutoff = utcnow() - timedelta(days=1)
                used = session.scalar(select(func.count(Audit.id)).where(
                    Audit.conversation_id == conversation_id,
                    Audit.action == "ai_call",
                    Audit.created_at >= cutoff,
                )) or 0
                if used >= settings.max_llm_calls_per_chat_per_day:
                    return False
                session.add(Audit(conversation_id=conversation_id,
                                  actor="system", action="ai_call"))
                session.flush()
                return True

            ai = AIEngine(settings, allow_call=allow_call)
            proposed, source = ai.operator_draft(
                history, knowledge, locale=locale,
                ticket_reason=ticket.category if ticket else "",
            )
            if not proposed.strip():
                raise HTTPException(503, detail="Draft unavailable")
            for previous in session.scalars(select(OperatorDraft).where(
                OperatorDraft.conversation_id == conversation_id,
                OperatorDraft.status == "suggested",
            )).all():
                previous.status = "superseded"
            session.add(OperatorDraft(
                conversation_id=conversation_id, text=proposed,
                source=source, status="suggested",
            ))
            session.add(Audit(conversation_id=conversation_id, actor="operator",
                              action="operator_draft_requested", detail=source))
        return RedirectResponse("/admin/conversations/" + str(conversation_id),
                                status_code=303)

    @app.post("/admin/conversations/{conversation_id}/draft/{draft_id}/dismiss")
    def dismiss_operator_draft(
        request: Request, conversation_id: int, draft_id: int,
        csrf_token: str = Form(...), _=Depends(authenticate),
    ):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            draft = session.scalar(select(OperatorDraft).where(
                OperatorDraft.id == draft_id,
                OperatorDraft.conversation_id == conversation_id,
            ).with_for_update())
            if draft is None:
                raise HTTPException(404, detail="Draft not found")
            if draft.status != "suggested":
                raise HTTPException(409, detail="Draft is no longer active")
            draft.status = "dismissed"
            session.add(Audit(conversation_id=conversation_id,
                              actor="operator", action="operator_draft_dismissed",
                              detail=str(draft_id)))
        return RedirectResponse("/admin/conversations/" + str(conversation_id),
                                status_code=303)

    @app.post("/admin/conversations/{conversation_id}/reply")
    def operator_reply(request: Request, conversation_id: int,
                       message: str = Form(...), csrf_token: str = Form(...),
                       draft_id: int | None = Form(None),
                       _=Depends(authenticate)):
        csrf(request, csrf_token)
        if not message.strip() or len(message) > 3500:
            raise HTTPException(status_code=422, detail="Message must be 1–3500 characters")
        with session_scope(request.app.state.factory) as session:
            conv = session.scalar(select(Conversation).where(
                Conversation.id == conversation_id).with_for_update())
            if conv is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conn = session.get(BusinessConnection, conv.business_connection_id)
            if not conn or not conn.enabled or not conn.can_reply:
                raise HTTPException(status_code=409, detail="Telegram Business reply permission unavailable")
            if not conv.last_inbound_at or utcnow() - _aware(conv.last_inbound_at) >= REPLY_WINDOW:
                raise HTTPException(status_code=409, detail="Telegram Business reply window expired")
            if draft_id is not None:
                draft = session.scalar(select(OperatorDraft).where(
                    OperatorDraft.id == draft_id,
                    OperatorDraft.conversation_id == conversation_id,
                ).with_for_update())
                if draft is None or draft.status != "suggested":
                    raise HTTPException(409, detail="Draft expired, dismissed or sent")
                draft.status = "sent"  # user may edit text before sending
            conv.owner = "human"
            conv.revision += 1
            ticket = session.scalar(select(Ticket).where(
                Ticket.conversation_id == conv.id,
                Ticket.status.in_(("open", "in_progress")),
            ).order_by(desc(Ticket.id)).limit(1))
            if ticket is not None:
                ticket.status = "in_progress"
                # First-response SLA stops ONLY after Telegram confirms delivery.
                ticket.assignee = ticket.assignee or _
                ticket.updated_at = utcnow()
            session.add(Outbox(conversation_id=conv.id, revision=conv.revision,
                               kind="human", text=message.strip(), buttons=[]))
            session.add(Audit(conversation_id=conv.id, actor="operator",
                              action="operator_reply_queued"))
        return RedirectResponse(f"/admin/conversations/{conversation_id}", status_code=303)


    @app.post("/admin/conversations/{conversation_id}/erase")
    def erase_conversation_data(
        request: Request, conversation_id: int,
        confirmation: str = Form(...), csrf_token: str = Form(...),
        _=Depends(authenticate),
    ):
        """Irreversible, admin-confirmed local deletion of a support conversation."""
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            conv = session.scalar(select(Conversation).where(
                Conversation.id == conversation_id).with_for_update())
            if conv is None:
                raise HTTPException(404, detail="Conversation not found")
            if confirmation != "ERASE " + str(conv.chat_id):
                raise HTTPException(422, detail="Type ERASE followed by the chat ID")
            inflight = session.scalar(select(Outbox.id).where(
                Outbox.conversation_id == conv.id,
                Outbox.status.in_(("sending", "uncertain")),
            ).limit(1))
            if inflight is not None:
                raise HTTPException(409, detail="Reconcile in-flight or uncertain sends first")

            # Scrub queued updates so the worker cannot recreate this old chat
            # from an update received before the erasure transaction.
            pending_events = session.scalars(select(Event).where(
                Event.status.in_(("pending", "processing")),
            ).with_for_update()).all()
            matching = []
            for event in pending_events:
                payload = event.payload or {}
                msg = (payload.get("business_message")
                       or payload.get("edited_business_message")
                       or payload.get("callback_query", {}).get("message")
                       or payload.get("deleted_business_messages")
                       or {})
                if (msg.get("business_connection_id") == conv.business_connection_id
                        and (msg.get("chat") or {}).get("id") == conv.chat_id):
                    if event.status == "processing":
                        raise HTTPException(409, detail="A matching inbound update is processing")
                    matching.append(event)
            for event in matching:
                event.status = "done"
                event.payload = {}
                event.claimed_until = None

            ticket_ids = session.scalars(select(Ticket.id).where(
                Ticket.conversation_id == conv.id,
            )).all()
            if ticket_ids:
                session.execute(delete(TicketNote).where(
                    TicketNote.ticket_id.in_(ticket_ids)))
                session.execute(delete(KnowledgeSuggestion).where(
                    KnowledgeSuggestion.ticket_id.in_(ticket_ids)))
            session.execute(delete(OperatorDraft).where(
                OperatorDraft.conversation_id == conv.id))
            session.execute(delete(Outbox).where(Outbox.conversation_id == conv.id))
            session.execute(delete(Message).where(Message.conversation_id == conv.id))
            session.execute(delete(Audit).where(Audit.conversation_id == conv.id))
            session.execute(delete(Ticket).where(Ticket.conversation_id == conv.id))
            session.execute(delete(Binding).where(
                Binding.customer_chat_id == conv.chat_id))
            session.execute(delete(Conversation).where(Conversation.id == conv.id))
            session.add(Audit(
                actor="operator", action="privacy_erasure",
                detail="local customer data erased (no identifier retained)",
            ))
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/conversations/{conversation_id}/takeover")
    def takeover(request: Request, conversation_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id, with_for_update=True)
            if conv is None:
                raise HTTPException(404)
            conv.owner = "human"
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="admin", action="takeover"))
        return RedirectResponse(f"/admin/conversations/{conversation_id}", status_code=303)

    @app.post("/admin/conversations/{conversation_id}/resume")
    def resume(request: Request, conversation_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id, with_for_update=True)
            if conv is None:
                raise HTTPException(404)
            conv.owner = "ai"
            conv.workflow, conv.step, conv.state = None, None, {}
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="admin", action="resume"))
        return RedirectResponse(f"/admin/conversations/{conversation_id}", status_code=303)


    @app.get("/admin/knowledge/review", response_class=HTMLResponse)
    def review_knowledge(request: Request, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            suggestions = session.scalars(select(KnowledgeSuggestion).where(
                KnowledgeSuggestion.status == "pending",
            ).order_by(desc(KnowledgeSuggestion.id)).limit(50)).all()
            current, _v = effective_playbook(session, request.app.state.playbook)
            return templates.TemplateResponse(request, "knowledge-review.html", {
                "suggestions": suggestions, "csrf": csrf_value(request),
                "locale": current.get("locale", "en"),
            })

    @app.post("/admin/knowledge/review/{suggestion_id}")
    def review_knowledge_action(
        request: Request, suggestion_id: int,
        decision: str = Form(...), question: str = Form(""),
        answer: str = Form(""), csrf_token: str = Form(...),
        _=Depends(authenticate),
    ):
        csrf(request, csrf_token)
        if decision not in ("approve", "reject"):
            raise HTTPException(422, detail="Invalid review action")
        if decision == "approve" and (
            not question.strip() or not answer.strip()
            or len(question) > 500 or len(answer) > 4000
        ):
            raise HTTPException(422, detail="Approved FAQ must have question and answer")
        with session_scope(request.app.state.factory) as session:
            suggestion = session.scalar(select(KnowledgeSuggestion).where(
                KnowledgeSuggestion.id == suggestion_id).with_for_update())
            if suggestion is None:
                raise HTTPException(404, detail="Suggestion not found")
            if suggestion.status != "pending":
                raise HTTPException(409, detail="Suggestion already reviewed")
            if decision == "approve":
                session.add(Knowledge(
                    question=redact(question.strip()),
                    answer=redact(answer.strip()),
                    enabled=True,
                ))
                suggestion.status = "approved"
            else:
                suggestion.status = "rejected"
            suggestion.reviewed_at = utcnow()
            session.add(Audit(actor="operator", action="knowledge_review",
                              detail=str(suggestion.id) + ":" + decision))
        return RedirectResponse("/admin/knowledge/review", status_code=303)

    @app.post("/admin/knowledge")
    def add_knowledge(request: Request, question: str = Form(...), answer: str = Form(...),
                      csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if len(question) > 500 or len(answer) > 4000 or not question.strip() or not answer.strip():
            raise HTTPException(422, detail="Invalid knowledge entry")
        with session_scope(request.app.state.factory) as session:
            session.add(Knowledge(question=question.strip(), answer=answer.strip()))
        return RedirectResponse("/admin#knowledge", status_code=303)

    @app.post("/admin/knowledge/{item_id}/delete")
    def delete_knowledge(request: Request, item_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            entry = session.get(Knowledge, item_id)
            if entry:
                session.delete(entry)
        return RedirectResponse("/admin#knowledge", status_code=303)

    @app.post("/admin/bindings")
    def add_binding_ui(request: Request, link: str = Form(...), provider: str = Form(...),
                       user_ref: str = Form(...), label: str = Form(""),
                       csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if provider not in ("marzban", "pasarguard") or len(user_ref) > 255 or not user_ref:
            raise HTTPException(422)
        if provider == "pasarguard" and not user_ref.isdecimal():
            raise HTTPException(422)
        digest = fingerprint(link, request.app.state.settings.binding_pepper)
        token_hmac = subscription_token_fingerprint(
            link, request.app.state.settings.binding_pepper)
        with session_scope(request.app.state.factory) as session:
            entry = session.scalar(select(Binding).where(Binding.link_hmac == digest))
            if entry is None:
                session.add(Binding(link_hmac=digest, token_hmac=token_hmac, provider=provider,
                                    user_ref=user_ref, label=label[:255]))
        return RedirectResponse("/admin#bindings", status_code=303)


    @app.post("/admin/outbox/{outbox_id}/resolve")
    def resolve_uncertain_delivery(
        request: Request, outbox_id: int, resolution: str = Form(...),
        csrf_token: str = Form(...), _=Depends(authenticate),
    ):
        """Only acknowledge or cancel an ambiguous send; never replay blindly."""
        csrf(request, csrf_token)
        if resolution not in ("confirmed_sent", "confirmed_not_sent"):
            raise HTTPException(422, detail="Invalid delivery reconciliation")
        with session_scope(request.app.state.factory) as session:
            job = session.scalar(select(Outbox).where(
                Outbox.id == outbox_id).with_for_update())
            if job is None:
                raise HTTPException(404, detail="Delivery not found")
            if job.status != "uncertain":
                raise HTTPException(409, detail="Only uncertain messages can be reconciled")
            job.status = "sent" if resolution == "confirmed_sent" else "cancelled"
            job.error_code = "manual_" + resolution
            job.claimed_until = None
            session.add(Audit(conversation_id=job.conversation_id, actor="operator",
                              action="delivery_reconciled", detail=str(job.id) + ":" + resolution))
        return RedirectResponse("/admin#uncertain", status_code=303)

    @app.post("/admin/tickets/{ticket_id}/close")
    def close_ticket(request: Request, ticket_id: int, csrf_token: str = Form(...),
                     resolution: str = Form(""), _=Depends(authenticate)):
        csrf(request, csrf_token)
        if len(resolution) > 2000:
            raise HTTPException(422, detail="Resolution summary exceeds 2000 characters")
        with session_scope(request.app.state.factory) as session:
            ticket = session.get(Ticket, ticket_id)
            if ticket is None:
                raise HTTPException(404)
            ticket.status = "closed"
            ticket.resolved_at = utcnow()
            ticket.resolution_summary = redact(resolution.strip()) or None
            ticket.updated_at = utcnow()
            if ticket.resolution_summary:
                previous = session.scalar(select(KnowledgeSuggestion.id).where(
                    KnowledgeSuggestion.ticket_id == ticket.id,
                ).limit(1))
                inbound = session.scalar(select(Message).where(
                    Message.conversation_id == ticket.conversation_id,
                    Message.direction == "in",
                    Message.content != "[expired]",
                ).order_by(desc(Message.id)).limit(1))
                if previous is None and inbound and inbound.content.strip():
                    session.add(KnowledgeSuggestion(
                        ticket_id=ticket.id,
                        question=redact(inbound.content)[:500],
                        answer=ticket.resolution_summary,
                        status="pending",
                    ))
            conv = session.get(Conversation, ticket.conversation_id)
            if conv.owner == "human_pending":
                conv.owner = "human"  # never resume AI implicitly
                conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="operator",
                              action="ticket_closed", detail=str(ticket.id)))
        return RedirectResponse("/admin/tickets", status_code=303)

    return app


app = build_app()
