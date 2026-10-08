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


def test_human_escalation_creates_operator_alert(database, test_settings, fake_telegram):
    from dataclasses import replace
    settings = replace(test_settings, support_alert_chat_id=555001)
    seed(database)
    p = Processor(settings, database, fake_telegram)
    with session_scope(database) as db:
        db.add(Event(update_id=5, payload=incoming(5, "میخوام با اپراتور انسانی حرف بزنم"), status="processing"))
    p.process_event(5)
    assert p.tick()  # customer-facing handoff message
    assert p.tick()  # operator alert
    assert len(fake_telegram.admin_alerts) == 1
    assert fake_telegram.admin_alerts[0][0] == 555001
    assert "ticket" in fake_telegram.admin_alerts[0][1].lower()
    with session_scope(database) as db:
        assert db.scalar(select(Conversation)).owner == "human_pending"
        outbound = db.scalars(select(Message).where(Message.direction == "out")).all()
        assert len(outbound) == 1  # alert must not appear in customer history


def test_receipt_evidence_is_forwarded_to_operator(database, test_settings, fake_telegram):
    from dataclasses import replace
    from replyforge.workflow import start_flow
    from replyforge.agent import AIEngine
    from replyforge.config import load_playbook
    settings = replace(test_settings, support_alert_chat_id=555001)
    seed(database)
    worker = Processor(settings, database, fake_telegram)
    # Customer is at the receipt-photo step of the payment workflow.
    with session_scope(database) as db:
        conv = Conversation(business_connection_id="bc", chat_id=1001, state={})
        db.add(conv)
        db.flush()
        start_flow(db, conv, worker.playbook, AIEngine(settings), settings, "payment")
        conv.step = "proof"
    with session_scope(database) as db:
        db.add(Event(update_id=12, status="processing", payload={
            "update_id": 12,
            "business_message": {
                "business_connection_id": "bc", "chat": {"id": 1001},
                "message_id": 12, "from": {"id": 1001},
                "photo": [{"file_id": "safe-tg-file-id"}],
            },
        }))
    worker.process_event(12)
    assert worker.tick()  # customer handoff message
    assert worker.tick()  # operator text alert
    assert worker.tick()  # attached receipt image
    assert len(fake_telegram.admin_photos) == 1
    assert fake_telegram.admin_photos[0][1] == "safe-tg-file-id"
    with session_scope(database) as db:
        assert len(db.scalars(select(Message).where(Message.direction == "out")).all()) == 1


def test_long_payment_flow_requests_sms_before_handoff(database, test_settings):
    from replyforge.agent import AIEngine
    from replyforge.config import load_playbook
    from replyforge.workflow import apply_action, accept_input
    from replyforge.models import BusinessConnection
    playbook = load_playbook("examples/azadbird.yaml")
    with session_scope(database) as db:
        db.add(BusinessConnection(id="flow", owner_user_id=10, enabled=True, can_reply=True))
        db.flush()
        c = Conversation(business_connection_id="flow", chat_id=19, state={})
        db.add(c)
        db.flush()
        ai = AIEngine(test_settings)
        apply_action(db, c, playbook, ai, test_settings, "flow:payment")
        apply_action(db, c, playbook, ai, test_settings, "choose:over15")
        assert c.step == "proof_late"
        accept_input(db, c, playbook, ai, test_settings, "", "receipt-photo")
        assert c.step == "sms_question"
        apply_action(db, c, playbook, ai, test_settings, "choose:yes")
        assert c.step == "sms"
        accept_input(db, c, playbook, ai, test_settings, "", "sms-photo")
        assert c.owner == "human_pending"
