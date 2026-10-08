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
