"""Read-only subscription catalog and relay-domain privacy regression tests."""
from dataclasses import replace

import httpx
from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.catalog import list_panel_users, sync_provider
from replyforge.config import load_playbook
from replyforge.database import session_scope
from replyforge.integrations import normalize
from replyforge.models import Binding, BusinessConnection, Conversation
from replyforge.security import fingerprint, subscription_token_fingerprint
from replyforge.workflow import apply_action, accept_input

TOKEN = "abcdefghijklmnopqrstuvwxyz_0123456789"


def test_normalized_relay_token_preserves_privacy(test_settings):
    a = "https://source.example.com/sub/" + TOKEN
    b = "https://relay.example.ir/prefix/sub/" + TOKEN + "/info"
    assert subscription_token_fingerprint(a, test_settings.binding_pepper) == (
        subscription_token_fingerprint(b, test_settings.binding_pepper))
    assert subscription_token_fingerprint("https://example.com/sub/short", test_settings.binding_pepper) is None
    assert subscription_token_fingerprint("vless://" + TOKEN, test_settings.binding_pepper) is None


def test_sync_marzban_catalog_and_match_relay_link(database, test_settings, monkeypatch):
    settings = replace(test_settings, marzban_base_url="https://panel.example.org",
                       marzban_username="admin", marzban_password="pass")
    def handler(req):
        if req.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "jwt"})
        assert req.headers["Authorization"] == "Bearer jwt"
        assert req.url.path == "/api/users"
        return httpx.Response(200, json={"users": [{
            "username": "first", "subscription_url": "https://panel.example.org/sub/" + TOKEN,
        }], "total": 1})
    with session_scope(database) as db:
        stats = sync_provider(db, settings, "marzban", transport=httpx.MockTransport(handler))
        assert stats.inserted == 1
        assert stats.conflicted == 0
    with session_scope(database) as db:
        binding = db.scalar(select(Binding))
        assert binding.token_hmac == subscription_token_fingerprint(
            "https://relay.example.ir/sub/" + TOKEN, settings.binding_pepper)
        assert TOKEN not in str(binding.__dict__)
        db.add(BusinessConnection(id="bc", owner_user_id=10, enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id="bc", chat_id=22, state={})
        db.add(conv)
        db.flush()
        playbook = load_playbook("examples/azadbird.yaml")
        apply_action(db, conv, playbook, AIEngine(settings), settings, "flow:subscription")
        monkeypatch.setattr("replyforge.workflow.lookup",
            lambda settings, provider, ref: normalize(provider, {
                "status": "active", "used_traffic": 2, "data_limit": 0,
                "expire": 0,
            }))
        reply = accept_input(db, conv, playbook, AIEngine(settings), settings,
                             "https://relay.example.ir/sub/" + TOKEN, None)
        assert "نامحدود" in reply.text
        assert conv.owner == "ai"


def test_pasarguard_sync_uses_stable_numeric_id(database, test_settings):
    settings = replace(test_settings, pasarguard_base_url="https://pg.example.org",
                       pasarguard_api_key="read-only-test")
    def handler(req):
        assert req.headers["X-Api-Key"] == "read-only-test"
        return httpx.Response(200, json={"users": [{
            "id": 73, "username": "customer_73",
            "subscription_url": "https://pg.example.org/sub/" + TOKEN,
        }], "total": 1})
    with session_scope(database) as db:
        result = sync_provider(db, settings, "pasarguard", transport=httpx.MockTransport(handler))
        assert result.inserted == 1
        assert db.scalar(select(Binding)).user_ref == "73"
        same = sync_provider(db, settings, "pasarguard", transport=httpx.MockTransport(handler))
        assert same.inserted == 0
        assert same.updated == 1


def test_catalog_does_not_silently_reassign_existing_token(database, test_settings):
    settings = replace(test_settings, marzban_base_url="https://panel.example",
                       marzban_username="a", marzban_password="pw")
    with session_scope(database) as db:
        url = "https://panel.example/sub/" + TOKEN
        db.add(Binding(link_hmac=fingerprint(url, settings.binding_pepper),
                       token_hmac=subscription_token_fingerprint(url, settings.binding_pepper),
                       provider="marzban", user_ref="alice"))
    def handler(req):
        if req.url.path.endswith("token"):
            return httpx.Response(200, json={"access_token": "x"})
        return httpx.Response(200, json={"users": [{
            "username": "bob",
            "subscription_url": "https://panel.example/sub/" + TOKEN,
        }], "total": 1})
    with session_scope(database) as db:
        result = sync_provider(db, settings, "marzban", transport=httpx.MockTransport(handler))
        assert result.conflicted == 1
        assert db.scalar(select(Binding)).user_ref == "alice"
