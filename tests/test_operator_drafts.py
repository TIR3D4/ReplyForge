"""AI suggestions remain auditable drafts; never send without operator action."""
import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import (
    Audit, BusinessConnection, Conversation, Message, OperatorDraft, Outbox, utcnow,
)
from replyforge.worker import Processor


def csrf(settings):
    return hmac.new(settings.binding_pepper.encode(),
                    b"replyforge-admin-csrf", hashlib.sha256).hexdigest()


def seed(db):
    db.add(BusinessConnection(id="bot", owner_user_id=901, enabled=True, can_reply=True))
    db.flush()
    conv = Conversation(business_connection_id="bot", chat_id=200,
                        owner="human_pending", state={}, last_inbound_at=utcnow())
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, telegram_message_id=11,
                   direction="in", content="V2Box وصل نمیشه",
                   kind="text", data={}))
    return conv.id


def test_suggest_is_review_only_and_can_be_dismissed(
    database, test_settings, fake_telegram,
):
    with session_scope(database) as session:
        cid = seed(session)
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(app) as client:
        assert client.post(f"/admin/conversations/{cid}/suggest",
                           auth=auth, data={"csrf_token": "bad"}).status_code == 403
        result = client.post(f"/admin/conversations/{cid}/suggest", auth=auth,
                             data={"csrf_token": csrf(test_settings)}, follow_redirects=False)
        assert result.status_code == 303
        assert fake_telegram.sent == []
        with session_scope(database) as session:
            draft = session.scalar(select(OperatorDraft))
            assert draft.status == "suggested"
            assert draft.source == "safe_fallback"
            did = draft.id
        page = client.get(f"/admin/conversations/{cid}", auth=auth)
        assert "draft_id" in page.text
        assert "V2Box" in page.text
        assert client.post(f"/admin/conversations/{cid}/draft/{did}/dismiss",
                           auth=auth, data={"csrf_token": csrf(test_settings)},
                           follow_redirects=False).status_code == 303
        with session_scope(database) as session:
            assert session.get(OperatorDraft, did).status == "dismissed"
        assert client.post(f"/admin/conversations/{cid}/reply", auth=auth, data={
            "csrf_token": csrf(test_settings), "message": "Reply",
            "draft_id": did,
        }).status_code == 409


def test_approved_draft_requires_explicit_operator_send(
    database, test_settings, fake_telegram,
):
    from replyforge.models import Knowledge
    with session_scope(database) as session:
        cid = seed(session)
        session.add(Knowledge(question="V2Box وصل نمیشه",
                              answer="اشتراکت را بروزرسانی کن و دوباره بررسی کن."))
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(app) as client:
        assert client.post(f"/admin/conversations/{cid}/suggest",
                           auth=auth, data={"csrf_token": csrf(test_settings)},
                           follow_redirects=False).status_code == 303
        with session_scope(database) as session:
            draft = session.scalar(select(OperatorDraft))
            assert draft.source == "approved_knowledge"
            did = draft.id
        assert fake_telegram.sent == []
        answer = "طبق بررسی، ابتدا اشتراک رو به‌روز کن."
        assert client.post(f"/admin/conversations/{cid}/reply", auth=auth,
                           data={"csrf_token": csrf(test_settings), "message": answer,
                                 "draft_id": did}, follow_redirects=False).status_code == 303
        with session_scope(database) as session:
            assert session.get(OperatorDraft, did).status == "sent"
            assert session.scalar(select(Outbox).where(Outbox.kind == "human")).text == answer
        processor = Processor(test_settings, database, fake_telegram)
        assert processor.tick() is True
        assert fake_telegram.sent[0][2] == answer


def test_payment_draft_never_claims_received_funds(test_settings):
    from replyforge.models import Message
    ai = AIEngine(test_settings, allow_call=lambda: False)
    message = Message(direction="in", content="رسیدم تایید نشده، پول رسید؟")
    text, source = ai.operator_draft([message], [], locale="fa", ticket_reason="payment")
    assert source == "payment_safety"
    assert "بررسی" in text
    assert "واریز" in text
