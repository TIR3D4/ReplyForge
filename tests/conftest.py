from dataclasses import replace

import pytest

from replyforge.config import Settings
from replyforge.database import create_schema, session_factory


@pytest.fixture
def test_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret-123456789")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password-12345")
    monkeypatch.setenv("BINDING_PEPPER", "test-pepper-123456789012345")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-12345678901234")
    return replace(
        Settings.from_env(strict=False),
        bot_token="fake-token",
        business_config="examples/azadbird.yaml",
        database_url="sqlite+pysqlite:///" + str(tmp_path / "replyforge.db"),
    )


@pytest.fixture
def database(test_settings):
    engine, factory = session_factory(test_settings.database_url)
    create_schema(engine)
    yield factory
    engine.dispose()


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.acks = []

    def send(self, connection_id, chat_id, text, markup=None):
        self.sent.append((connection_id, chat_id, text, markup))
        return {"message_id": 100 + len(self.sent)}

    def edit(self, connection_id, chat_id, message_id, text, markup=None):
        self.edited.append((connection_id, chat_id, message_id, text, markup))
        return {"message_id": message_id}

    def answer_callback(self, callback_id):
        self.acks.append(callback_id)
        return True

    def close(self):
        pass

    def get_connection(self, connection_id):
        return {
            "id": connection_id, "user": {"id": 901}, "is_enabled": True,
            "rights": {"can_reply": True},
        }


@pytest.fixture
def fake_telegram():
    return FakeTelegram()
