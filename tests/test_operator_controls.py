"""Human-agent coordination and monitor-only controls."""
from dataclasses import replace
import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Control, Event, Outbox
from replyforge.worker import Processor


def _auth(settings):
    return settings.admin_username, settings.admin_password


def _csrf(settings):
    return hmac.new(settings.binding_pepper.encode(), b"replyforge-admin-csrf", hashlib.sha256).hexdigest()


def _inbound(update_id, chat_id=1001, text="سلام"):
    return {"update_id": update_id, "business_message": {
        "business_connection_id": "bc", "chat": {"id": chat_id},
        "message_id": update_id, "from": {"id": chat_id}, "text": text
    }}


def _seed(database):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))


def test_monitor_mode_records_customer_and_suppresses_ai(database, test_settings, fake_telegram):
    settings = replace(test_settings, auto_reply_enabled=False)
    _seed(database)
    p = Processor(settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=70, payload=_inbound(70), status="processing"))
    p.process_event(70)
    assert p.tick() is False
    with session_scope(database) as db:
        assert db.scalar(select(Conversation)).chat_id == 1001
        assert db.scalar(select(Outbox)) is None


def test_enable_ai_from_admin_and_pause_again(database, test_settings, fake_telegram):
    settings = replace(test_settings, auto_reply_enabled=False)
    _seed(database)
    app = build_app(settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        assert "حالت مشاهده" in client.get("/admin", auth=_auth(settings)).text
        response = client.post("/admin/automation", auth=_auth(settings), data={
            "enabled": "true", "csrf_token": _csrf(settings),
        }, follow_redirects=False)
        assert response.status_code == 303
    with session_scope(database) as db:
        assert db.get(Control, "auto_reply_enabled").value == "true"
        db.add(Event(update_id=71, payload=_inbound(71), status="processing"))
    p = Processor(settings, database, fake_telegram)
    p.process_event(71)
    p.tick()
    assert len(fake_telegram.sent) == 1
    with TestClient(app) as client:
        client.post("/admin/automation", auth=_auth(settings), data={
            "enabled": "false", "csrf_token": _csrf(settings),
        })
    with session_scope(database) as db:
        db.add(Event(update_id=72, payload=_inbound(72, text="وصل نمیشه"), status="processing"))
    p.process_event(72)
    assert p.tick() is False
    assert len(fake_telegram.sent) == 1


def test_human_reply_uses_business_identity_with_ai_paused(database, test_settings, fake_telegram):
    settings = replace(test_settings, auto_reply_enabled=False)
    _seed(database)
    p = Processor(settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=81, payload=_inbound(81), status="processing"))
    p.process_event(81)
    with session_scope(database) as db:
        conversation_id = db.scalar(select(Conversation)).id
    app = build_app(settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        invalid = client.post(f"/admin/conversations/{conversation_id}/reply",
                              auth=_auth(settings), data={"message": "Hello", "csrf_token": "bad"})
        assert invalid.status_code == 403
        accepted = client.post(f"/admin/conversations/{conversation_id}/reply",
                               auth=_auth(settings),
                               data={"message": "سلام، پیگیری می‌کنم.", "csrf_token": _csrf(settings)},
                               follow_redirects=False)
        assert accepted.status_code == 303
    assert p.tick() is True
    assert fake_telegram.sent[-1][2] == "سلام، پیگیری می‌کنم."
    with session_scope(database) as db:
        conv = db.scalar(select(Conversation))
        assert conv.owner == "human"
        assert db.scalar(select(Outbox)).status == "sent"


def test_emergency_pause_cancels_queued_ai_reply(database, test_settings, fake_telegram):
    _seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=91, payload=_inbound(91), status="processing"))
    p.process_event(91)
    with session_scope(database) as db:
        db.add(Control(key="auto_reply_enabled", value="false"))
    assert p.tick() is True
    assert fake_telegram.sent == []
    with session_scope(database) as db:
        assert db.scalar(select(Outbox)).status == "cancelled"


def test_human_takeover_preempts_queued_ai_reply(database, test_settings, fake_telegram):
    _seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=92, payload=_inbound(92), status="processing"))
    p.process_event(92)
    with session_scope(database) as db:
        c = db.scalar(select(Conversation))
        c.owner = "human"
        c.revision += 1
    p.tick()
    assert fake_telegram.sent == []
    with session_scope(database) as db:
        assert db.scalar(select(Outbox)).status == "cancelled"
