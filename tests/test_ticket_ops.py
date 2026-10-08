"""Operator workflow: priority, SLA, private notes, ownership and reopening."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.config import ConfigError, load_playbook, parse_playbook_yaml
from replyforge.database import session_scope
from replyforge.models import (
    Audit, BusinessConnection, Conversation, Outbox, Ticket, TicketNote, utcnow,
)
from replyforge.worker import Processor


def auth(settings):
    return settings.admin_username, settings.admin_password


def csrf(settings):
    return hmac.new(settings.binding_pepper.encode(), b"replyforge-admin-csrf",
                    hashlib.sha256).hexdigest()


def create_ticket(db, *, sla_overdue=False):
    db.add(BusinessConnection(
        id="support", owner_user_id=901, enabled=True, can_reply=True,
    ))
    db.flush()
    c = Conversation(business_connection_id="support", chat_id=7001,
                     owner="human_pending", state={},
                     last_inbound_at=utcnow())
    db.add(c)
    db.flush()
    ticket = Ticket(conversation_id=c.id, reason="payment", category="payment",
                    priority="high", sla_due_at=utcnow() +
                    timedelta(minutes=-30 if sla_overdue else 30))
    db.add(ticket)
    db.flush()
    return c.id, ticket.id


def test_ticket_triage_notes_close_and_reopen(database, test_settings, fake_telegram):
    with session_scope(database) as db:
        conversation_id, ticket_id = create_ticket(db)
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        assert client.get("/admin/tickets").status_code == 401
        board = client.get("/admin/tickets", auth=auth(test_settings))
        assert board.status_code == 200
        assert "payment" in board.text
        detail = client.get(f"/admin/conversations/{conversation_id}", auth=auth(test_settings))
        assert "Ticket management" in detail.text or "مدیریت تیکت" in detail.text

        bad = client.post(f"/admin/tickets/{ticket_id}/triage",
                          auth=auth(test_settings), data={
            "csrf_token": csrf(test_settings), "priority": "superhigh",
            "category": "payment", "assignee": "Nora",
        })
        assert bad.status_code == 422

        good = client.post(f"/admin/tickets/{ticket_id}/triage",
                           auth=auth(test_settings), follow_redirects=False, data={
            "csrf_token": csrf(test_settings), "priority": "urgent",
            "category": "billing", "assignee": "Nora", "status_value": "in_progress",
        })
        assert good.status_code == 303
        with session_scope(database) as db:
            t = db.get(Ticket, ticket_id)
            assert (t.priority, t.assignee, t.category, t.status) == (
                "urgent", "Nora", "billing", "in_progress")
            assert db.get(Conversation, conversation_id).owner == "human"

        note = client.post(f"/admin/tickets/{ticket_id}/notes",
                           auth=auth(test_settings), follow_redirects=False, data={
            "csrf_token": csrf(test_settings),
            "content": "Check order https://example.org/sub/bearer-token",
        })
        assert note.status_code == 303
        with session_scope(database) as db:
            memo = db.scalar(select(TicketNote))
            assert "[redacted link]" in memo.content

        closed = client.post(f"/admin/tickets/{ticket_id}/close",
                             auth=auth(test_settings), follow_redirects=False, data={
            "csrf_token": csrf(test_settings), "resolution": "Manually verified",
        })
        assert closed.status_code == 303
        with session_scope(database) as db:
            t = db.get(Ticket, ticket_id)
            assert t.status == "closed"
            assert t.resolved_at is not None
            assert db.get(Conversation, conversation_id).owner == "human"
        reopened = client.post(f"/admin/tickets/{ticket_id}/reopen",
                               auth=auth(test_settings), follow_redirects=False,
                               data={"csrf_token": csrf(test_settings)})
        assert reopened.status_code == 303
        with session_scope(database) as db:
            t = db.get(Ticket, ticket_id)
            assert t.status == "open"
            assert t.first_response_at is None
            assert db.get(Conversation, conversation_id).owner == "human_pending"


def test_operator_reply_starts_first_response_sla(database, test_settings, fake_telegram):
    with session_scope(database) as db:
        conversation_id, ticket_id = create_ticket(db)
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        assert client.post(f"/admin/conversations/{conversation_id}/reply",
                           auth=auth(test_settings), follow_redirects=False, data={
            "csrf_token": csrf(test_settings), "message": "در حال بررسی است",
        }).status_code == 303
    with session_scope(database) as db:
        t = db.get(Ticket, ticket_id)
        assert t.status == "in_progress"
        assert t.first_response_at is not None
        assert t.assignee == test_settings.admin_username


def test_sla_escalates_exactly_once_and_notifies_operator(
    database, test_settings, fake_telegram,
):
    settings = replace(test_settings, support_alert_chat_id=999991)
    with session_scope(database) as db:
        _, ticket_id = create_ticket(db, sla_overdue=True)
    p = Processor(settings, database, fake_telegram)
    assert p.tick()
    assert p.tick()
    assert p.tick() is False
    assert len(fake_telegram.admin_alerts) == 1
    assert str(ticket_id) in fake_telegram.admin_alerts[0][1]
    with session_scope(database) as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket.escalated_at is not None
        assert ticket.priority == "urgent"
        audit = db.scalar(select(Audit).where(
            Audit.action == "ticket_sla_escalation"))
        assert audit is not None


def test_playbook_sla_rejects_ambiguous_and_unsafe_values():
    text = open("config/business.yaml", encoding="utf-8").read()
    for invalid in ('support_sla_minutes: 0', 'support_sla_minutes: true',
                    'support_sla_minutes: 20000'):
        import re
        source = re.sub(r"support_sla_minutes: \d+", invalid, text)
        try:
            parse_playbook_yaml(source)
        except ConfigError:
            pass
        else:
            raise AssertionError(invalid + " should fail")
