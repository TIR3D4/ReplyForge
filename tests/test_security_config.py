import pytest

from replyforge.agent import AIEngine, local_intent
from replyforge.config import ConfigError, load_playbook
from replyforge.integrations import normalize
from replyforge.security import extract_link, fingerprint, redact
from replyforge.workflow import root_menu


def test_playbooks_validate():
    public = load_playbook("config/business.yaml")
    vpn = load_playbook("examples/azadbird.yaml")
    assert public["brand"] == "ReplyForge Support"
    assert "connection" in vpn["workflows"]
    assert len(root_menu(vpn).actions) == 5


def test_invalid_playbook_does_not_allow_undefined_actions(tmp_path):
    file = tmp_path / "invalid.yaml"
    file.write_text("brand: X\nmenu: [{label: X, action: 'flow:missing'}]\nworkflows: {}\n")
    with pytest.raises(ConfigError):
        load_playbook(file)


def test_redaction_fingerprints_and_urls():
    raw = "vless://uuid@server:443#node"
    link = "https://example.com/sub/abc-secret"
    assert extract_link("Please check " + raw) == raw
    assert extract_link(link) == link
    assert fingerprint(link, "a-secret") == fingerprint(link, "a-secret")
    assert fingerprint(link, "a-secret") != fingerprint(link, "other-secret")
    assert link not in redact(link)
    assert "4111111111111111" not in redact("Card 4111111111111111")


def test_local_routing_for_persian():
    assert local_intent("فیلترشکنم وصل نمیشه", {"connection"}) == "flow:connection"
    assert local_intent("رسیدم هنوز تایید نشده", {"payment"}) == "flow:payment"
    assert local_intent("hello", {"connection"}) is None


def test_quota_normalization():
    s = normalize("marzban", {
        "status": "active", "used_traffic": 100, "data_limit": 150,
        "expire": 0,
    })
    assert s.remaining_bytes == 50
    assert s.expires_at is None
    assert normalize("marzban", {"data_limit": 0}).remaining_bytes is None


def test_ai_fallback_never_creates_payment_confirmation(test_settings):
    ai = AIEngine(test_settings)
    assert ai._complete("instructions", "customer text") is None
    assert ai.knowledge_answer("I paid", []) is None
