from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.config import load_playbook
from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Knowledge, Ticket, Binding
from replyforge.security import fingerprint
from replyforge.workflow import (
    accept_input, apply_action, build_markup, callback_action, root_menu
)


def conv_in_db(session):
    session.add(BusinessConnection(id="bc-test", owner_user_id=901, enabled=True, can_reply=True))
    session.flush()
    c = Conversation(business_connection_id="bc-test", chat_id=222, state={})
    session.add(c)
    session.flush()
    return c


def test_guided_troubleshooting_and_human_handoff(database, test_settings):
    playbook = load_playbook(test_settings.business_config)
    ai = AIEngine(test_settings)
    with session_scope(database) as db:
        c = conv_in_db(db)
        proposal = apply_action(db, c, playbook, ai, test_settings, "flow:connection")
        assert c.step == "link"
        assert "اشتراکت" in proposal.text
        # Never trust a random subscription token.
        p = accept_input(db, c, playbook, ai, test_settings,
                         "https://example.com/sub/private-key", None)
        assert c.owner == "human_pending"
        assert "پشتیبان" in p.text
        assert db.scalar(select(Ticket).where(Ticket.conversation_id == c.id)) is not None


def test_choice_and_menu_nonce_protect_against_old_buttons(database, test_settings):
    playbook = load_playbook(test_settings.business_config)
    ai = AIEngine(test_settings)
    with session_scope(database) as db:
        c = conv_in_db(db)
        apply_action(db, c, playbook, ai, test_settings, "flow:payment")
        assert c.step == "when"
        markup = build_markup(c, [
            ("کمتر از ۵ دقیقه", "choose:under5"),
            ("بیشتر از ۱۵ دقیقه", "choose:over15"),
        ])
        data = markup["inline_keyboard"][0][0]["callback_data"]
        assert callback_action(c, data) == "choose:under5"
        p = apply_action(db, c, playbook, ai, test_settings, "choose:under5")
        assert c.step == "proof"
        assert "رسید" in p.text
        build_markup(c, [("🏠", "home")])
        assert callback_action(c, data) is None
        photo = accept_input(db, c, playbook, ai, test_settings, "", "telegram-file-id")
        assert c.owner == "human_pending"
        assert "پشتیبان" in photo.text


def test_knowledge_requires_verified_entry(database, test_settings):
    playbook = load_playbook(test_settings.business_config)
    ai = AIEngine(test_settings)
    with session_scope(database) as db:
        c = conv_in_db(db)
        db.add(Knowledge(question="چطور خرید کنم", answer="از صفحه خرید استفاده کنید"))
        db.flush()
        apply_action(db, c, playbook, ai, test_settings, "flow:subscription")
        assert c.step == "link"
        # An unrelated workflow must not allow arbitrary model output.
        assert ai.knowledge_answer("کاملاً بی ربط", db.scalars(select(Knowledge)).all()) is None


def test_menu_is_config_driven(test_settings):
    p = root_menu(load_playbook(test_settings.business_config))
    assert any(a == "flow:connection" for _, a in p.actions)
