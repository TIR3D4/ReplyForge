from sqlalchemy import select

from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Event
from replyforge.playbooks import save_playbook
from replyforge.worker import Processor


def test_new_playbook_is_used_next_event(database, test_settings, fake_telegram):
    with session_scope(database) as session:
        session.add(BusinessConnection(id="bc", owner_user_id=555, enabled=True, can_reply=True))
        save_playbook(session, """
brand: Custom Agent
locale: en
welcome: Welcome to Custom Agent
handoff_text: A human will help
menu:
  - {label: Ask a human, action: human}
workflows: {}
""")
    worker = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as session:
        session.add(Event(update_id=9, status="processing", payload={
            "update_id": 9, "business_message": {
                "business_connection_id": "bc", "chat": {"id": 333},
                "message_id": 9, "from": {"id": 333}, "text": "Hello",
            },
        }))
    worker.process_event(9)
    worker.tick()
    assert fake_telegram.sent[0][2] == "Welcome to Custom Agent"
    with session_scope(database) as session:
        conv = session.scalar(select(Conversation))
        assert conv.state.get("_playbook_version") == 1
