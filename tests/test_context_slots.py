"""Natural customer details should reduce support friction and AI token use."""
from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.config import load_playbook
from replyforge.database import session_scope
from replyforge.integrations import normalize
from replyforge.models import Binding, BusinessConnection, Conversation
from replyforge.security import fingerprint
from replyforge.workflow import accept_input, infer_customer_slots


def test_persian_client_and_app_extraction():
    assert infer_customer_slots("من آیفون دارم با V2Box کانکت نمیشه") == {
        "device": "ios", "application": "V2Box",
    }
    assert infer_customer_slots("روی اندروید v2rayNG استفاده میکنم") == {
        "device": "android", "application": "v2rayNG",
    }


def test_emoji_label_free_text_choice_without_ai_api(test_settings):
    ai = AIEngine(test_settings)
    options = [
        {"label": "📱 آیفون", "value": "ios"},
        {"label": "🤖 اندروید", "value": "android"},
        {"label": "💻 ویندوز", "value": "windows"},
    ]
    assert ai.select_choice("اندروید", options) == "android"
    assert ai.select_choice("ویندوز", options) == "windows"


def test_already_known_device_and_app_are_not_reasked(database, test_settings, monkeypatch):
    s = test_settings
    playbook = load_playbook("examples/azadbird.yaml")
    full_link = "https://example.net/sub/long-verified-0123456789"
    with session_scope(database) as db:
        db.add(BusinessConnection(id="b", owner_user_id=77, enabled=True, can_reply=True))
        db.add(Binding(link_hmac=fingerprint(full_link, s.binding_pepper),
                       provider="marzban", user_ref="client", label="client"))
        db.flush()
        conv = Conversation(business_connection_id="b", chat_id=1337, state={})
        db.add(conv)
        db.flush()
        first = accept_input(db, conv, playbook, AIEngine(s), s,
                             "آیفون دارم، V2Box وصل نمیشه", None)
        assert "اشتراکت" in first.text
        assert conv.step == "link"
        monkeypatch.setattr("replyforge.workflow.lookup", lambda *args: normalize(
            "marzban", {"status": "active", "used_traffic": 0, "data_limit": 0, "expire": 0}
        ))
        answer = accept_input(db, conv, playbook, AIEngine(s), s, full_link, None)
        assert conv.step == "refresh"
        assert conv.state["answers"]["device"] == "ios"
        assert conv.state["answers"]["application"] == "V2Box"
        assert "V2Box" in answer.text
