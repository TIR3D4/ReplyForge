"""Quality loop: customer confirmation and transparent human escalation."""
from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.config import load_playbook
from replyforge.database import session_scope
from replyforge.models import Audit, BusinessConnection, Conversation, Ticket
from replyforge.workflow import apply_action


def test_resolution_feedback_and_escalation(database, test_settings):
    playbook = load_playbook("examples/azadbird.yaml")
    with session_scope(database) as session:
        session.add(BusinessConnection(id="b", owner_user_id=99, enabled=True, can_reply=True))
        session.flush()
        conv = Conversation(business_connection_id="b", chat_id=101, state={})
        session.add(conv)
        session.flush()
        ai = AIEngine(test_settings)
        apply_action(session, conv, playbook, ai, test_settings, "flow:connection")
        # The subscription stage is verified elsewhere; simulate a verified account.
        conv.step = "refresh"
        p = apply_action(session, conv, playbook, ai, test_settings, "choose:fixed")
        assert conv.workflow is None
        assert "feedback:yes" in [a for _, a in p.actions]
        yes = apply_action(session, conv, playbook, ai, test_settings, "feedback:yes")
        assert "ممنون" in yes.text
        assert session.scalar(select(Audit).where(Audit.action == "feedback_positive"))
        no = apply_action(session, conv, playbook, ai, test_settings, "feedback:no")
        assert conv.owner == "human_pending"
        assert session.scalar(select(Audit).where(Audit.action == "feedback_negative"))
        assert session.scalar(select(Ticket).where(Ticket.reason == "unsolved_after_guidance"))
