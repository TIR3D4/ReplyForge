"""Operator media previews remain private and do not expose the bot token."""
from fastapi.testclient import TestClient

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Message


def test_image_preview_requires_admin_auth(database, test_settings, fake_telegram):
    with session_scope(database) as session:
        session.add(BusinessConnection(id="bc", owner_user_id=100,
                                      enabled=True, can_reply=True))
        session.flush()
        c = Conversation(business_connection_id="bc", chat_id=101, state={})
        session.add(c)
        session.flush()
        m = Message(conversation_id=c.id, telegram_message_id=900,
                    direction="in", kind="photo", content="",
                    data={"file_id": "image-safe-id"})
        session.add(m)
        session.flush()
        mid = m.id
    fake_telegram.files["image-safe-id"] = bytes.fromhex("ffd8ff") + b"testimage"
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        assert client.get(f"/admin/media/{mid}").status_code == 401
        response = client.get(f"/admin/media/{mid}", auth=(
            test_settings.admin_username, test_settings.admin_password))
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("image/jpeg")
        assert response.headers["Cache-Control"] == "private, no-store"
        assert b"testimage" in response.content
        assert client.get("/admin/media/99999", auth=(
            test_settings.admin_username, test_settings.admin_password)).status_code == 404
