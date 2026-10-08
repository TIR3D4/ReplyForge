"""Customer follow-up evidence and owner-authored messages are recoverable."""
from dataclasses import replace

from sqlalchemy import select

from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Event, Message
from replyforge.worker import Processor


def test_human_owner_message_persisted_once(database, test_settings, fake_telegram):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))
        db.flush()
        db.add(Conversation(business_connection_id="bc", chat_id=100, owner="ai", state={}))
        for event_id in (700, 701):
            db.add(Event(update_id=event_id, status="processing", payload={
                "business_message": {
                    "business_connection_id": "bc", "chat": {"id": 100},
                    "from": {"id": 901}, "message_id": 700,
                    "text": "اول لینک اشتراک رو بفرستید",
                },
            }))
    processor = Processor(test_settings, database, fake_telegram)
    processor.process_event(700)
    processor.process_event(701)
    with session_scope(database) as db:
        messages = db.scalars(select(Message).where(Message.direction == "out")).all()
        assert len(messages) == 1
        assert messages[0].content == "اول لینک اشتراک رو بفرستید"
        assert db.scalar(select(Conversation)).owner == "human"


def test_customer_evidence_after_handoff_reaches_operator(database, test_settings, fake_telegram):
    settings = replace(test_settings, support_alert_chat_id=33333,
                       auto_reply_enabled=False)
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))
        db.flush()
        db.add(Conversation(business_connection_id="bc", chat_id=100,
                            owner="human_pending", state={}))
        db.add(Event(update_id=710, status="processing", payload={
            "business_message": {
                "business_connection_id": "bc", "chat": {"id": 100},
                "from": {"id": 100}, "message_id": 710,
                "photo": [{"file_id": "receipt-id-710"}],
            },
        }))
    processor = Processor(settings, database, fake_telegram)
    processor.process_event(710)
    assert processor.tick()
    assert processor.tick()
    assert fake_telegram.admin_photos[0][1] == "receipt-id-710"
    assert fake_telegram.admin_alerts[0][0] == 33333
    with session_scope(database) as db:
        assert db.scalar(select(Conversation)).owner == "human_pending"
