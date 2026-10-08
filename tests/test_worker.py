from sqlalchemy import select

from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Event, Message, Outbox, Ticket
from replyforge.telegram import TelegramError
from replyforge.worker import Processor


def incoming(mid=9, txt="سلام"):
    return {"update_id": mid, "business_message": {
        "business_connection_id": "bc", "chat": {"id": 1001},
        "message_id": mid, "from": {"id": 1001}, "text": txt,
    }}


def seed(database):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))


def test_first_message_sends_one_menu_and_duplicate_is_ignored(database, test_settings, fake_telegram):
    seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=9, payload=incoming(), status="processing"))
    p.process_event(9)
    assert p.tick()  # outbox delivery
    assert len(fake_telegram.sent) == 1
    with session_scope(database) as db:
        assert db.scalar(select(Outbox)).status == "sent"
        conv = db.scalar(select(Conversation))
        assert conv.menu_message_id == 101
        assert db.scalar(select(Message).where(Message.direction == "in")) is not None
    # A replayed message id cannot trigger another reply.
    with session_scope(database) as db:
        db.add(Event(update_id=10, payload=incoming(10, "ignored"), status="processing"))
    p.process_event(10)
    assert p.tick()
    assert len(fake_telegram.edited) == 1  # initial menu edits, not chat spam


def test_owner_message_stops_ai_and_cancels_pending(database, test_settings, fake_telegram):
    seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=9, payload=incoming(), status="processing"))
    p.process_event(9)
    with session_scope(database) as db:
        db.add(Event(update_id=10, payload={"update_id": 10, "business_message": {
            "business_connection_id": "bc", "chat": {"id": 1001},
            "message_id": 10, "from": {"id": 901}, "text": "I'll take over",
        }}, status="processing"))
    p.process_event(10)
    p.tick()
    assert fake_telegram.sent == []
    with session_scope(database) as db:
        conv = db.scalar(select(Conversation))
        assert conv.owner == "human"
        assert db.scalar(select(Outbox)).status == "cancelled"


def test_callback_edits_existing_menu(database, test_settings, fake_telegram):
    seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=9, payload=incoming(), status="processing"))
    p.process_event(9)
    p.tick()
    with session_scope(database) as db:
        c = db.scalar(select(Conversation))
        payload = f"rf:{c.state['menu_nonce']}:0"
        db.add(Event(update_id=11, payload={"update_id": 11, "callback_query": {
            "id": "c1", "from": {"id": 1001}, "data": payload,
            "message": {"message_id": 101, "business_connection_id": "bc",
                        "chat": {"id": 1001}},
        }}, status="processing"))
    p.process_event(11)
    p.tick()
    assert len(fake_telegram.sent) == 1
    assert len(fake_telegram.edited) == 1
    with session_scope(database) as db:
        assert db.scalar(select(Conversation)).step == "link"


def test_uncertain_send_is_not_automatically_retried(database, test_settings, fake_telegram):
    seed(database)
    p = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=9, payload=incoming(), status="processing"))
    p.process_event(9)
    def fail(*args, **kwargs):
        raise TelegramError("transport_unconfirmed", uncertain=True)
    fake_telegram.send = fail
    assert p.tick()
    with session_scope(database) as db:
        assert db.scalar(select(Outbox)).status == "uncertain"
    assert not p.tick()
