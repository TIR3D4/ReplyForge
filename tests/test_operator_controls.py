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



def test_two_queued_operator_replies_preserve_order(database, test_settings, fake_telegram):
    """A later human revision must not invalidate an earlier intentional reply."""
    settings = replace(test_settings, auto_reply_enabled=False)
    _seed(database)
    proc = Processor(settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=601, payload=_inbound(601), status="processing"))
    proc.process_event(601)
    with session_scope(database) as db:
        conv_id = db.scalar(select(Conversation)).id
    app = build_app(settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        for text in ("پیام اول", "پیام دوم"):
            response = client.post(
                f"/admin/conversations/{conv_id}/reply", auth=_auth(settings),
                data={"csrf_token": _csrf(settings), "message": text},
                follow_redirects=False,
            )
            assert response.status_code == 303
    assert proc.tick()
    assert proc.tick()
    assert [item[2] for item in fake_telegram.sent] == ["پیام اول", "پیام دوم"]
    with session_scope(database) as db:
        outbox = db.scalars(select(Outbox).order_by(Outbox.id)).all()
        assert [item.status for item in outbox] == ["sent", "sent"]


def test_uncertain_reply_blocks_next_until_explicit_reconciliation(
    database, test_settings, fake_telegram,
):
    settings = replace(test_settings, auto_reply_enabled=False)
    _seed(database)
    proc = Processor(settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=602, payload=_inbound(602), status="processing"))
    proc.process_event(602)
    with session_scope(database) as db:
        conv_id = db.scalar(select(Conversation)).id
    app = build_app(settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        for message in ("اولی", "دومی"):
            assert client.post(
                f"/admin/conversations/{conv_id}/reply", auth=_auth(settings),
                data={"csrf_token": _csrf(settings), "message": message},
                follow_redirects=False,
            ).status_code == 303
    from replyforge.telegram import TelegramError
    original_send = fake_telegram.send
    attempts = []

    def flaky_send(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise TelegramError("transport_unconfirmed", uncertain=True)
        return original_send(*args, **kwargs)

    fake_telegram.send = flaky_send
    assert proc.tick()  # First send becomes uncertain
    assert proc.tick()  # Second send is gated
    assert len(fake_telegram.sent) == 0
    with session_scope(database) as db:
        uncertain = db.scalar(select(Outbox).where(Outbox.status == "uncertain"))
        assert uncertain is not None
        second = db.scalar(select(Outbox).where(Outbox.id > uncertain.id))
        assert second.status == "pending"

    with TestClient(app) as client:
        invalid = client.post(
            f"/admin/outbox/{uncertain.id}/resolve", auth=_auth(settings),
            data={"csrf_token": "wrong", "resolution": "confirmed_sent"},
        )
        assert invalid.status_code == 403
        confirmed = client.post(
            f"/admin/outbox/{uncertain.id}/resolve", auth=_auth(settings),
            data={"csrf_token": _csrf(settings), "resolution": "confirmed_sent"},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303
    from replyforge.models import utcnow
    from datetime import timedelta
    with session_scope(database) as db:
        next_job = db.scalar(select(Outbox).where(Outbox.id == second.id))
        next_job.available_at = utcnow() - timedelta(seconds=1)
    assert proc.tick()
    assert [item[2] for item in fake_telegram.sent] == ["دومی"]


def test_browser_validation_errors_are_readable_and_api_errors_remain_json(database, test_settings, fake_telegram):
    from fastapi.testclient import TestClient
    from replyforge.app import build_app
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        client.auth = (test_settings.admin_username, test_settings.admin_password)
        response = client.post('/admin/agent', headers={'Accept': 'text/html'}, data={})
        assert response.status_code == 422
        assert 'text/html' in response.headers['content-type']
        assert '<h1>' in response.text
        assert client.post('/admin/agent', data={}).headers['content-type'] == 'application/json'
