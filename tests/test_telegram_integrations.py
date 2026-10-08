import httpx

from replyforge.integrations import MarzbanAdapter, PasarguardAdapter
from replyforge.telegram import TelegramClient, TelegramError
from dataclasses import replace


def test_marzban_adapter_reads_usage(test_settings):
    s = replace(test_settings,
                marzban_base_url="https://marzban.example",
                marzban_username="admin", marzban_password="pw")
    def handler(request):
        if request.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "jwt"})
        assert request.headers["Authorization"] == "Bearer jwt"
        return httpx.Response(200, json={"status": "active", "used_traffic": 100, "data_limit": 200, "expire": 0})
    result = MarzbanAdapter(s, transport=httpx.MockTransport(handler)).lookup("some_user")
    assert result.remaining_bytes == 100


def test_pasarguard_adapter_reads_by_id(test_settings):
    s = replace(test_settings, pasarguard_base_url="https://pg.example", pasarguard_api_key="key")
    def handler(request):
        assert request.url.path == "/api/user/by-id/77"
        assert request.headers["X-Api-Key"] == "key"
        return httpx.Response(200, json={"status": "active", "used_traffic": 10, "data_limit": 0, "expire": 0})
    result = PasarguardAdapter(s, transport=httpx.MockTransport(handler)).lookup("77")
    assert result.remaining_bytes is None


def test_telegram_client_sends_business_connection():
    def handler(req):
        assert req.url.path.endswith("/sendMessage")
        payload = __import__("json").loads(req.content)
        assert payload["business_connection_id"] == "bc1"
        assert payload["chat_id"] == 123
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 456}})
    bot = TelegramClient("fake", transport=httpx.MockTransport(handler))
    assert bot.send("bc1", 123, "Hello")["message_id"] == 456
    bot.close()
