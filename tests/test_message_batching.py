"""Customer message bursts are analyzed as one interaction without losing history."""
from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Event, Message, Outbox, utcnow
from replyforge.worker import Processor


def update(uid, chat=71, text="سلام", owner=False):
    return {"update_id": uid, "business_message": {
        "business_connection_id": "bc", "chat": {"id": chat},
        "message_id": uid, "from": {"id": 901 if owner else chat},
        "text": text,
    }}


def test_webhook_debounce_applies_only_to_business_messages(
    database, test_settings, fake_telegram,
):
    settings = replace(test_settings, message_debounce_ms=2000)
    app = build_app(settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        secret = {"X-Telegram-Bot-Api-Secret-Token": settings.webhook_secret}
        assert client.post("/telegram/webhook", json=update(701), headers=secret).status_code == 200
        assert client.post("/telegram/webhook", json={
            "update_id": 702, "business_connection": {
                "id": "bc", "is_enabled": True, "user": {"id": 901},
            }}, headers=secret).status_code == 200
        with session_scope(database) as session:
            later = session.get(Event, 701)
            immediate = session.get(Event, 702)
            assert later.available_at > immediate.available_at


def test_burst_preserves_individual_messages_but_one_response(
    database, test_settings, fake_telegram,
):
    settings = replace(test_settings, message_debounce_ms=1200)
    with session_scope(database) as session:
        session.add(BusinessConnection(
            id="bc", owner_user_id=901, enabled=True, can_reply=True,
        ))
        for payload in (
            update(801, text="سلام"),
            update(802, text="رسیدم تایید نشده، کمک"),
            update(803, text="۲۰ دقیقه گذشته"),
        ):
            session.add(Event(update_id=payload["update_id"], payload=payload,
                              status="pending", available_at=utcnow() - timedelta(seconds=1)))
    processor = Processor(settings, database, fake_telegram)
    assert processor.tick()  # one event claim
    assert processor.tick()  # one outgoing response
    assert processor.tick() is False
    assert len(fake_telegram.sent) == 1
    with session_scope(database) as session:
        events = session.scalars(select(Event).order_by(Event.update_id)).all()
        assert [e.status for e in events] == ["done", "done", "done"]
        assert all(e.payload == {} for e in events)
        msgs = session.scalars(select(Message).where(Message.direction == "in")).all()
        assert len(msgs) == 3
        assert session.scalar(select(Conversation)).workflow == "payment"
        assert len(session.scalars(select(Outbox)).all()) == 1


def test_coalescing_stops_on_owner_and_different_chats(
    database, test_settings, fake_telegram,
):
    settings = replace(test_settings, message_debounce_ms=1000)
    with session_scope(database) as session:
        session.add(BusinessConnection(
            id="bc", owner_user_id=901, enabled=True, can_reply=True,
        ))
        for payload in (
            update(810, text="Hello"),
            update(811, text="Human reply", owner=True),
            update(812, text="Connection broken"),
        ):
            session.add(Event(update_id=payload["update_id"], payload=payload,
                              status="pending", available_at=utcnow() - timedelta(seconds=1)))
    proc = Processor(settings, database, fake_telegram)
    assert proc.tick()  # customer
    with session_scope(database) as session:
        assert session.get(Event, 810).status == "done"
        assert session.get(Event, 811).status == "pending"
        assert session.get(Event, 812).status == "pending"
    assert proc.tick()  # human takeover prevents auto response
    assert proc.tick()  # last customer message recorded in human-owned chat
    assert proc.tick()  # cancel queued stale AI proposal
    assert len(fake_telegram.sent) == 0
    with session_scope(database) as session:
        conv = session.scalar(select(Conversation))
        assert conv.owner == "human"
        assert len(session.scalars(select(Message)).all()) == 3
