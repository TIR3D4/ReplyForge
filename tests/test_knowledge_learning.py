"""Past support resolutions become knowledge only after deliberate operator approval."""
import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import (
    BusinessConnection, Conversation, Knowledge, KnowledgeSuggestion, Message, Ticket,
    utcnow,
)


def csrf(settings):
    return hmac.new(settings.binding_pepper.encode(),
                    b"replyforge-admin-csrf", hashlib.sha256).hexdigest()


def test_resolved_ticket_creates_unpublished_review_candidate(
    database, test_settings, fake_telegram,
):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id="bc", chat_id=1001,
                            owner="human", state={}, last_inbound_at=utcnow())
        db.add(conv)
        db.flush()
        ticket = Ticket(conversation_id=conv.id, status="in_progress",
                        reason="connection", category="connection")
        db.add(ticket)
        db.add(Message(conversation_id=conv.id, direction="in", kind="text",
                       telegram_message_id=1, content="V2Box کار نمیکنه", data={}))
        db.flush()
        tid = ticket.id
    auth = (test_settings.admin_username, test_settings.admin_password)
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        closed = client.post(f"/admin/tickets/{tid}/close", auth=auth,
                             follow_redirects=False, data={
            "csrf_token": csrf(test_settings),
            "resolution": "اشتراک را در برنامه بروزرسانی کنید و دوباره تست بگیرید.",
        })
        assert closed.status_code == 303
        with session_scope(database) as db:
            proposal = db.scalar(select(KnowledgeSuggestion))
            assert proposal.status == "pending"
            assert db.scalar(select(Knowledge)) is None
            proposal_id = proposal.id
        board = client.get("/admin/knowledge/review", auth=auth)
        assert board.status_code == 200
        assert "V2Box" in board.text
        bad = client.post(f"/admin/knowledge/review/{proposal_id}", auth=auth, data={
            "csrf_token": "invalid", "decision": "approve", "question": "Q", "answer": "A",
        })
        assert bad.status_code == 403
        approved = client.post(f"/admin/knowledge/review/{proposal_id}", auth=auth,
                               follow_redirects=False, data={
            "csrf_token": csrf(test_settings),
            "decision": "approve",
            "question": "چطور اشتراک V2Box رو بروزرسانی کنم؟",
            "answer": "اشتراک را در برنامه بروزرسانی کنید.",
        })
        assert approved.status_code == 303
        with session_scope(database) as db:
            suggestion = db.get(KnowledgeSuggestion, proposal_id)
            assert suggestion.status == "approved"
            assert db.scalar(select(Knowledge)).answer == "اشتراک را در برنامه بروزرسانی کنید."
        duplicate = client.post(f"/admin/knowledge/review/{proposal_id}", auth=auth,
                                data={
            "csrf_token": csrf(test_settings), "decision": "approve",
            "question": "Q", "answer": "A",
        })
        assert duplicate.status_code == 409


def test_missing_resolution_does_not_create_knowledge(database, test_settings, fake_telegram):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=901, enabled=True, can_reply=True))
        db.flush()
        c = Conversation(business_connection_id="bc", chat_id=100, owner="human", state={})
        db.add(c)
        db.flush()
        t = Ticket(conversation_id=c.id, reason="general")
        db.add(t)
        db.flush()
        ticket_id = t.id
    with TestClient(build_app(test_settings, factory=database,
                              telegram=fake_telegram)) as client:
        assert client.post(f"/admin/tickets/{ticket_id}/close",
                           auth=(test_settings.admin_username, test_settings.admin_password),
                           data={"csrf_token": csrf(test_settings)}).status_code == 200
        with session_scope(database) as db:
            assert db.scalar(select(KnowledgeSuggestion)) is None
