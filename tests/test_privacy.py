from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select

from replyforge.database import session_scope
from replyforge.models import (
    BusinessConnection, Conversation, Message, Outbox, Ticket,
    TicketNote, OperatorDraft, KnowledgeSuggestion, utcnow,
)
from replyforge.privacy import prune_history


def test_retention_scrubs_text_and_file_ids_but_not_recent_records(database):
    old = utcnow() - timedelta(days=200)
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=900,
                                  enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id="bc", chat_id=44, state={})
        db.add(conv)
        db.flush()
        db.add(Message(conversation_id=conv.id, telegram_message_id=10,
                       direction="in", kind="photo",
                       content="secret older content", data={"file_id": "tg-secret-file"},
                       created_at=old))
        db.add(Message(conversation_id=conv.id, telegram_message_id=11,
                       direction="in", kind="text",
                       content="recent data", data={}, created_at=utcnow()))
        db.add(Outbox(conversation_id=conv.id, revision=1, kind="human",
                      text="private outgoing", buttons=[], status="sent", created_at=old))
        db.add(Outbox(conversation_id=conv.id, revision=2, kind="human",
                      text="uncertain should remain", buttons=[], status="uncertain",
                      created_at=old))
        db.add(OperatorDraft(conversation_id=conv.id, text="old draft",
                             source="fallback", status="suggested", created_at=old))
        ticket = Ticket(conversation_id=conv.id, status="closed",
                        resolved_at=old, resolution_summary="sensitive old summary")
        db.add(ticket)
        db.flush()
        db.add(TicketNote(ticket_id=ticket.id, author="operator",
                          content="private old note", created_at=old))
        db.add(KnowledgeSuggestion(ticket_id=ticket.id, question="old question",
                                   answer="old answer", status="pending",
                                   created_at=old))
    with session_scope(database) as db:
        result = prune_history(db, retention_days=180)
        assert result == {
            "messages": 1, "outbox": 1, "notes": 1, "drafts": 1, "suggestions": 1,
            "ticket_summaries": 1, "insight_candidates": 0,
        }
    with session_scope(database) as db:
        messages = db.scalars(select(Message).order_by(Message.id)).all()
        assert messages[0].content == "[expired]"
        assert messages[0].data == {}
        assert messages[1].content == "recent data"
        outputs = db.scalars(select(Outbox).order_by(Outbox.id)).all()
        assert outputs[0].text == "[expired]"
        assert outputs[1].text == "uncertain should remain"
        assert db.scalar(select(OperatorDraft)).status == "expired"
        assert db.scalar(select(TicketNote)).content == "[expired]"
        assert db.scalar(select(Ticket)).resolution_summary == "[expired]"
        candidate = db.scalar(select(KnowledgeSuggestion))
        assert candidate.question == "[expired]"
        assert candidate.status == "expired"
        assert not any(prune_history(db, retention_days=180).values())


def test_retention_can_be_disabled(database):
    with session_scope(database) as db:
        assert not any(prune_history(db, 0).values())
