"""Explicit customer erasure deletes local PII without modifying external services."""
import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import (
    AIUsage, Audit, Binding, BusinessConnection, Conversation, Event, KnowledgeSuggestion,
    Message, OperatorDraft, Outbox, Ticket, TicketNote, utcnow,
)
from replyforge.security import fingerprint


def csrf(settings):
    return hmac.new(settings.binding_pepper.encode(),
                    b"replyforge-admin-csrf", hashlib.sha256).hexdigest()


def seed(session, settings, outbox_status="sent"):
    session.add(BusinessConnection(id="bc", enabled=True, can_reply=True,
                                   owner_user_id=901))
    session.flush()
    conv = Conversation(business_connection_id="bc", chat_id=77, state={},
                        owner="human", last_inbound_at=utcnow())
    session.add(conv)
    session.flush()
    session.add(Message(conversation_id=conv.id, telegram_message_id=1,
                        direction="in", kind="photo", content="private content",
                        data={"file_id": "sensitive-id"}))
    session.add(Outbox(conversation_id=conv.id, revision=1, kind="human",
                       text="private reply", buttons=[], status=outbox_status))
    session.add(OperatorDraft(conversation_id=conv.id, text="private draft",
                              source="safe_fallback", status="suggested"))
    ticket = Ticket(conversation_id=conv.id, reason="payment")
    session.add(ticket)
    session.flush()
    session.add(TicketNote(ticket_id=ticket.id, author="admin",
                           content="operator sensitive note"))
    session.add(KnowledgeSuggestion(ticket_id=ticket.id,
                                    question="old question", answer="old answer"))
    session.add(Binding(link_hmac=fingerprint("test-link", settings.binding_pepper),
                        provider="marzban", user_ref="sample",
                        customer_chat_id=conv.chat_id))
    session.add(Event(update_id=888, payload={"update_id": 888, "business_message": {
        "business_connection_id": "bc", "chat": {"id": 77},
        "message_id": 888, "from": {"id": 77}, "text": "private inbound",
    }}, status="pending"))
    session.flush()
    return conv.id


def test_erasure_requires_double_confirmation_and_removes_customer_records(
    database, test_settings, fake_telegram,
):
    with session_scope(database) as db:
        cid = seed(db, test_settings)
    from dataclasses import replace
    from replyforge.budget import BudgetLedger
    ledger = BudgetLedger(database, replace(test_settings, ai_input_price='1', ai_output_price='1'), f'chat:{cid}')
    usage_id = ledger.reserve('synthetic', 100, 10)
    assert usage_id
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(app) as client:
        assert client.post(f"/admin/conversations/{cid}/erase", auth=auth,
                           data={"csrf_token": csrf(test_settings),
                                 "confirmation": "ERASE WRONG"}).status_code == 422
        assert client.post(f"/admin/conversations/{cid}/erase", auth=auth,
                           data={"csrf_token": "wrong",
                                 "confirmation": "ERASE 77"}).status_code == 403
        response = client.post(f"/admin/conversations/{cid}/erase", auth=auth,
                               follow_redirects=False, data={
            "csrf_token": csrf(test_settings), "confirmation": "ERASE 77",
        })
        assert response.status_code == 303
        assert client.get(f"/admin/conversations/{cid}", auth=auth).status_code == 404
    with session_scope(database) as db:
        for cls in (Conversation, Message, Outbox, Ticket, TicketNote,
                    KnowledgeSuggestion, OperatorDraft, Binding):
            assert db.scalar(select(cls)) is None
        assert db.get(AIUsage, usage_id).scope == "erased"
        assert db.get(AIUsage, usage_id).reserved_microusd == 110
        ev = db.get(Event, 888)
        assert ev.status == "done"
        assert ev.payload == {}
        audit = db.scalar(select(Audit))
        assert audit.action == "privacy_erasure"
        assert "77" not in audit.detail


def test_ambiguous_delivery_blocks_irreversible_erase(
    database, test_settings, fake_telegram,
):
    with session_scope(database) as db:
        cid = seed(db, test_settings, outbox_status="uncertain")
    with TestClient(build_app(test_settings, factory=database,
                              telegram=fake_telegram)) as client:
        response = client.post(f"/admin/conversations/{cid}/erase",
                               auth=(test_settings.admin_username,
                                     test_settings.admin_password),
                               data={"csrf_token": csrf(test_settings),
                                     "confirmation": "ERASE 77"})
        assert response.status_code == 409
    with session_scope(database) as db:
        assert db.get(Conversation, cid) is not None
