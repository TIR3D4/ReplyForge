"""Multimodal support is bounded, opt-in and never auto-verifies finances."""
from dataclasses import replace
import json

import httpx
from sqlalchemy import select

from replyforge.agent import AIEngine
from replyforge.database import session_scope
from replyforge.models import BusinessConnection, Conversation, Event, Ticket
from replyforge.telegram import TelegramClient, TelegramError
from replyforge.worker import Processor


def test_telegram_file_download_is_bounded():
    def handler(request):
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {
                "file_size": 4, "file_path": "photos/test.jpg"
            }})
        assert request.url.host == "api.telegram.org"
        assert request.url.path == "/file/bot123:ABC/photos/test.jpg"
        return httpx.Response(200, content=b"ABCD")
    bot = TelegramClient("123:ABC", transport=httpx.MockTransport(handler))
    assert bot.download("file-1", 20) == b"ABCD"
    bot.close()


def test_telegram_file_download_rejects_traversal_and_oversize():
    def traversal(request):
        return httpx.Response(200, json={"ok": True, "result": {"file_path": "../etc/passwd"}})
    bot = TelegramClient("123:ABC", transport=httpx.MockTransport(traversal))
    try:
        try:
            bot.download("id", 500)
            assert False, "must reject traversal"
        except TelegramError as e:
            assert e.status == 400
    finally:
        bot.close()

    def huge(request):
        return httpx.Response(200, json={"ok": True, "result": {
            "file_size": 100000000, "file_path": "voice/file.ogg"
        }})
    bot = TelegramClient("123:ABC", transport=httpx.MockTransport(huge))
    try:
        try:
            bot.download("id", 1000)
            assert False, "must reject large media"
        except TelegramError as e:
            assert e.status == 413
    finally:
        bot.close()


def test_screenshot_analysis_opt_in_budget_and_no_raw_card(test_settings):
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "خطای اتصال در V2Box دیده می‌شود"
        }}]})
    raw = b"\xff\xd8\xff" + b"abc" * 6
    s = replace(test_settings, vision_enabled=True, ai_api_key="fake")
    engine = AIEngine(s, transport=httpx.MockTransport(handler), allow_call=lambda: True)
    assert "V2Box" in engine.describe_screenshot(raw)
    assert len(received) == 1
    assert "image_url" in json.dumps(received[0])
    assert engine.describe_screenshot(b"not image") is None
    denied = AIEngine(s, transport=httpx.MockTransport(handler), allow_call=lambda: False)
    assert denied.describe_screenshot(raw) is None
    assert len(received) == 1


def test_voice_transcription_uses_provider_only_when_enabled(test_settings):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "وصل نمیشه"})
    settings = replace(test_settings, voice_enabled=True, ai_api_key="fake")
    agent = AIEngine(settings, transport=httpx.MockTransport(handler), allow_call=lambda: True)
    assert agent.transcribe_voice(b"OggS-small") == "وصل نمیشه"
    assert requests[0].url.path.endswith("/audio/transcriptions")
    disabled = AIEngine(replace(settings, voice_enabled=False),
                        transport=httpx.MockTransport(handler))
    assert disabled.transcribe_voice(b"OggS-small") is None
    assert len(requests) == 1


def test_voice_without_consent_requests_text_and_not_human_secret(database, test_settings, fake_telegram):
    with session_scope(database) as db:
        db.add(BusinessConnection(id="bc", owner_user_id=900, enabled=True, can_reply=True))
        db.add(Event(update_id=771, status="processing", payload={"update_id": 771,
            "business_message": {"business_connection_id": "bc",
                "chat": {"id": 100}, "message_id": 771,
                "from": {"id": 100}, "voice": {"file_id": "voice-1"}}}))
    fake_telegram.files["voice-1"] = b"OggS"
    p = Processor(test_settings, database, fake_telegram)
    p.process_event(771)
    p.tick()
    assert "ویست دریافت شد" in fake_telegram.sent[0][2]
    with session_scope(database) as db:
        assert db.scalar(select(Conversation)).owner == "ai"
        assert db.scalar(select(Ticket)) is None
