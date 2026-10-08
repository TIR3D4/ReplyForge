"""FastAPI webhook ingestion, internal provisioning API and operator dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import hmac
from copy import deepcopy
import yaml
from pathlib import Path

from fastapi import (
    Body, Depends, FastAPI, Form, Header, HTTPException, Request
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import IntegrityError

from .config import ConfigError, Settings, load_playbook
from .database import session_factory, session_scope
from .models import (
    Audit, Binding, Conversation, Event, Knowledge, Message, Outbox, Ticket, utcnow
)
from .security import constant_time_equal, fingerprint
from .playbooks import active_version, activate_version, effective_playbook, save_playbook
from .models import PlaybookVersion
from .telegram import TelegramClient

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
        title="ReplyForge", version="0.1.0", docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )

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

    @app.post("/telegram/webhook")
    def telegram_webhook(request: Request, payload: dict = Body(...),
                         telegram_secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token")):
        s = request.app.state.settings
        if s.webhook_path != "/telegram/webhook":
            raise HTTPException(status_code=500, detail="Configured webhook path mismatch")
        if telegram_secret is None or not constant_time_equal(s.webhook_secret, telegram_secret):
            raise HTTPException(status_code=403, detail="Forbidden")
        if int(request.headers.get("content-length") or "0") > 262144:
            raise HTTPException(status_code=413, detail="Update too large")
        update_id = payload.get("update_id")
        if type(update_id) is not int or update_id < 0:
            raise HTTPException(status_code=400, detail="Invalid update_id")
        try:
            with session_scope(request.app.state.factory) as session:
                if session.get(Event, update_id) is None:
                    session.add(Event(update_id=update_id, payload=payload))
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
        with session_scope(request.app.state.factory) as session:
            existing = session.scalar(select(Binding).where(Binding.link_hmac == digest))
            if existing is None:
                existing = Binding(link_hmac=digest, provider=data.provider,
                                   user_ref=data.user_ref, label=data.label,
                                   customer_chat_id=data.customer_chat_id)
                session.add(existing)
            else:
                existing.provider, existing.user_ref = data.provider, data.user_ref
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
                "open_tickets": session.scalar(select(func.count(Ticket.id)).where(Ticket.status == "open")),
                "sent_messages": session.scalar(select(func.count(Outbox.id)).where(Outbox.status == "sent")),
                "pending_messages": session.scalar(select(func.count(Outbox.id)).where(Outbox.status.in_(("pending", "sending")))),
            }
            current, revision = effective_playbook(session, request.app.state.playbook)
            return templates.TemplateResponse(request, "dashboard.html", {
                **data, "brand": current["brand"],
                "locale": current.get("locale", "en"),
                "playbook_version": revision,
                "csrf": csrf_value(request),
                "_": lambda en, fa: fa if current.get("locale") == "fa" else en,
            })

    @app.get("/admin/conversations/{conversation_id}", response_class=HTMLResponse)
    def conversation_detail(request: Request, conversation_id: int, _=Depends(authenticate)):
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise HTTPException(404)
            messages = session.scalars(select(Message).where(
                Message.conversation_id == conversation_id,
            ).order_by(Message.id.desc()).limit(100)).all()
            current, _version = effective_playbook(session, request.app.state.playbook)
            return templates.TemplateResponse(request, "conversation.html", {
                "conv": conv, "messages": list(reversed(messages)),
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

    @app.post("/admin/conversations/{conversation_id}/takeover")
    def takeover(request: Request, conversation_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            conv = session.get(Conversation, conversation_id)
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
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise HTTPException(404)
            conv.owner = "ai"
            conv.workflow, conv.step, conv.state = None, None, {}
            conv.revision += 1
            session.add(Audit(conversation_id=conv.id, actor="admin", action="resume"))
        return RedirectResponse(f"/admin/conversations/{conversation_id}", status_code=303)

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
        with session_scope(request.app.state.factory) as session:
            entry = session.scalar(select(Binding).where(Binding.link_hmac == digest))
            if entry is None:
                session.add(Binding(link_hmac=digest, provider=provider, user_ref=user_ref,
                                    label=label[:255]))
        return RedirectResponse("/admin#bindings", status_code=303)

    @app.post("/admin/tickets/{ticket_id}/close")
    def close_ticket(request: Request, ticket_id: int, csrf_token: str = Form(...), _=Depends(authenticate)):
        csrf(request, csrf_token)
        with session_scope(request.app.state.factory) as session:
            ticket = session.get(Ticket, ticket_id)
            if ticket is None:
                raise HTTPException(404)
            ticket.status = "closed"
            ticket.updated_at = utcnow()
        return RedirectResponse("/admin#tickets", status_code=303)

    return app


app = build_app()
