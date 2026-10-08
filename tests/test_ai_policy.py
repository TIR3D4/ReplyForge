from dataclasses import replace
import json
import re
import httpx
from fastapi.testclient import TestClient
from replyforge.agent import AIEngine
from replyforge.app import build_app
from replyforge.ai_policy import effective_settings
from replyforge.database import session_scope


def test_fallback_redaction_and_separate_attempt_permission(test_settings):
    attempts, requests = [], []
    def allow():
        attempts.append(1)
        return True
    def handle(req):
        requests.append(json.loads(req.content))
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'human'}}]})
    cfg = replace(test_settings, ai_api_key='test', ai_fallback_model='fallback', ai_max_output_tokens=80)
    ai = AIEngine(cfg, transport=httpx.MockTransport(handle), allow_call=allow)
    assert ai._complete('classify', 'Contact user@example.com +98 912 123 4567') == 'human'
    assert len(attempts) == 2
    assert requests[1]['model'] == 'fallback'
    assert requests[1]['max_tokens'] == 80
    assert 'user@example.com' not in str(requests)
    assert '912' not in str(requests)


def test_timeout_is_not_retried(test_settings):
    attempts = []
    def handle(req):
        attempts.append(1)
        raise httpx.ReadTimeout('unknown result')
    ai = AIEngine(replace(test_settings, ai_api_key='test', ai_fallback_model='fallback'), transport=httpx.MockTransport(handle))
    assert ai._complete('system', 'hello') is None
    assert len(attempts) == 1


def test_runtime_policy_and_playground_without_external_key(database, test_settings, fake_telegram):
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        page = client.get('/admin/agent', auth=auth)
        assert page.status_code == 200
        token = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        data = {'csrf_token': token, 'model': 'local-model', 'max_output_tokens': '400', 'calls_per_chat_per_day': '5'}
        assert client.post('/admin/agent', data=data, auth=auth).status_code == 200
        with session_scope(database) as db:
            cfg = effective_settings(db, test_settings)
            assert cfg.ai_model == 'local-model'
            assert cfg.max_llm_calls_per_chat_per_day == 5
        assert client.post('/admin/agent', data={**data, 'max_output_tokens': '9999'}, auth=auth).status_code == 422
        res = client.post('/admin/agent/test', data={'csrf_token': token, 'text': 'پرداخت کردم'}, auth=auth)
        assert res.status_code == 200
        assert 'flow:payment' in res.text
        assert not fake_telegram.sent


def test_binary_choices_are_not_guessed_from_position(test_settings):
    ai = AIEngine(test_settings)
    assert ai.select_choice('fixed', [{'value': 'ios', 'label': 'iPhone'}, {'value': 'android', 'label': 'Android'}]) is None
    assert ai.select_choice('still not working', [{'value': 'no', 'label': 'No'}, {'value': 'yes', 'label': 'Yes'}]) == 'no'
