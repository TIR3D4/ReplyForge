from datetime import timedelta
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import Conversation, Event, Outbox, utcnow
from replyforge.telegram import TelegramClient, TelegramError
from replyforge.worker import Processor
from test_worker import seed, incoming


def test_old_message_does_not_reopen_reply_window(database, test_settings, fake_telegram):
    seed(database)
    payload = incoming()
    payload['business_message']['date'] = int((utcnow() - timedelta(days=2)).timestamp())
    with session_scope(database) as db:
        db.add(Event(update_id=9, payload=payload, status='processing'))
    worker = Processor(test_settings, database, fake_telegram)
    worker.process_event(9)
    worker.tick()
    assert fake_telegram.sent == []
    with session_scope(database) as db:
        assert db.scalar(select(Outbox)).status == 'cancelled'


def test_rate_limit_respects_full_delay_and_stops(database, test_settings, fake_telegram):
    seed(database)
    with session_scope(database) as db:
        conv = Conversation(business_connection_id='bc', chat_id=1001, owner='human', last_inbound_at=utcnow())
        db.add(conv)
        db.flush()
        job = Outbox(conversation_id=conv.id, revision=0, kind='human', text='Hello', status='sending')
        db.add(job)
        db.flush()
        jid = job.id
    def limited(*args, **kwargs):
        raise TelegramError('rate limited', status=429, retry_after=900)
    fake_telegram.send = limited
    worker = Processor(test_settings, database, fake_telegram)
    for attempt in range(5):
        with session_scope(database) as db:
            db.get(Outbox, jid).status = 'sending'
        worker.delivery(jid)
        with session_scope(database) as db:
            job = db.get(Outbox, jid)
            assert job.attempts == attempt + 1
            assert job.status == ('failed' if attempt == 4 else 'pending')
            if attempt < 4:
                assert job.available_at.replace(tzinfo=utcnow().tzinfo) > utcnow() + timedelta(seconds=890)


@pytest.mark.parametrize('body,status', [([], 200), ({'ok': False}, 502)])
def test_untrusted_telegram_response_is_uncertain(body, status):
    client = TelegramClient('fake', transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)))
    with pytest.raises(TelegramError) as error:
        client.send('bc', 1, 'hello')
    assert error.value.uncertain
    client.close()


def test_handoff_edit_explicitly_clears_keyboard():
    seen = []
    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 2}})
    client = TelegramClient('fake', transport=httpx.MockTransport(handler))
    client.edit('bc', 1, 2, 'human support')
    assert seen[0]['reply_markup'] == {'inline_keyboard': []}
    assert seen[0]['business_connection_id'] == 'bc'
    client.close()


def test_chunked_request_limit_before_json_parsing(database, test_settings, fake_telegram):
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        result = client.post('/telegram/webhook', content=iter([b'x' * 150000, b'x' * 150000]), headers={
            'content-type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': test_settings.webhook_secret})
        assert result.status_code == 413
