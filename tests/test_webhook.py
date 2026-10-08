from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import Binding, Event
from replyforge.security import fingerprint


def test_secret_and_durable_update_dedup(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        url = "/telegram/webhook"
        payload = {"update_id": 1, "business_message": {"message_id": 1}}
        assert client.post(url, json=payload).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": test_settings.webhook_secret}
        assert client.post(url, json=payload, headers=headers).status_code == 200
        assert client.post(url, json=payload, headers=headers).status_code == 200
        with session_scope(database) as db:
            assert len(db.scalars(select(Event)).all()) == 1


def test_admin_requires_auth_and_csrf(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        assert client.get("/admin").status_code == 401
        auth = (test_settings.admin_username, test_settings.admin_password)
        assert client.get("/admin", auth=auth).status_code == 200
        res = client.post("/admin/knowledge", auth=auth, data={
            "question": "test", "answer": "answer", "csrf_token": "wrong"
        })
        assert res.status_code == 403


def test_internal_binding_does_not_save_plain_link(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    url = "https://example.com/sub/super-secret"
    with TestClient(app) as client:
        res = client.post("/api/bindings", json={
            "link": url, "provider": "marzban", "user_ref": "client_17",
        }, headers={"X-Internal-Api-Key": test_settings.internal_api_key})
        assert res.status_code == 200, res.text
        with session_scope(database) as db:
            b = db.scalar(select(Binding))
            assert b.link_hmac == fingerprint(url, test_settings.binding_pepper)
            assert url not in str(b.__dict__)
