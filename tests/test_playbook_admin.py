import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import PlaybookVersion


def test_authenticated_editor_and_version_restore(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    auth = (test_settings.admin_username, test_settings.admin_password)
    csrf = hmac.new(test_settings.binding_pepper.encode(),
                    b"replyforge-admin-csrf", hashlib.sha256).hexdigest()
    content = """
brand: Integration Shop
locale: en
welcome: Hello
handoff_text: Coming soon
menu:
  - {label: Human, action: human}
workflows: {}
"""
    with TestClient(app) as client:
        assert client.get("/admin/playbook").status_code == 401
        assert client.get("/admin/playbook", auth=auth).status_code == 200
        assert client.post("/admin/playbook", auth=auth,
                           data={"source": content, "csrf_token": "bad"}).status_code == 403
        response = client.post("/admin/playbook", auth=auth,
                               data={"source": content, "csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303
        assert "Integration Shop" in client.get("/admin", auth=auth).text
        with session_scope(database) as db:
            first = db.scalar(select(PlaybookVersion))
            assert first.active is True
            first_id = first.id
        second = content.replace("Integration Shop", "Second Shop")
        assert client.post("/admin/playbook", auth=auth,
                           data={"source": second, "csrf_token": csrf}).status_code == 200
        assert "Second Shop" in client.get("/admin", auth=auth).text
        assert client.post(f"/admin/playbook/{first_id}/activate", auth=auth,
                           data={"csrf_token": csrf}).status_code == 200
        assert "Integration Shop" in client.get("/admin", auth=auth).text
        assert client.post("/admin/playbook", auth=auth,
                           data={"source": "brand: Invalid", "csrf_token": csrf}).status_code == 422


def test_no_code_menu_customization(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    auth = (test_settings.admin_username, test_settings.admin_password)
    csrf = hmac.new(test_settings.binding_pepper.encode(),
                    b"replyforge-admin-csrf", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        body = {
            "csrf_token": csrf,
            "brand": "New Support Co",
            "locale": "fa",
            "welcome": "سلام مشتری عزیز",
            "handoff_text": "منتظر اپراتور باشید",
            "resolution_text": "مشکل حل شد",
            "menu_label": ["👤 اپراتور", "📦 سفارش", ""],
            "menu_action": ["human", "flow:delivery", "human"],
        }
        response = client.post("/admin/playbook/basic", auth=auth,
                               data=body, follow_redirects=False)
        assert response.status_code == 303, response.text
        panel = client.get("/admin/playbook", auth=auth)
        assert "New Support Co" in panel.text
        with session_scope(database) as session:
            version = session.scalar(select(PlaybookVersion))
            assert version.active is True
            from replyforge.config import parse_playbook_yaml
            config = parse_playbook_yaml(version.source)
            assert config["locale"] == "fa"
            assert len(config["menu"]) == 2
        body["menu_action"] = ["human", "flow:not_defined", "human"]
        assert client.post("/admin/playbook/basic", auth=auth, data=body).status_code == 422


def test_guided_step_editor_validates_transition(database, test_settings, fake_telegram):
    import re
    from fastapi.testclient import TestClient
    from replyforge.app import build_app
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        page = client.get('/admin/playbook', auth=auth)
        token = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        data = {'csrf_token': token, 'flow': 'connection', 'step': 'app', 'prompt': 'Your question?', 'next_step': 'does-not-exist'}
        assert client.post('/admin/playbook/step', auth=auth, data=data).status_code == 422
        data['next_step'] = 'refresh'
        assert client.post('/admin/playbook/step', auth=auth, data=data).status_code == 200
