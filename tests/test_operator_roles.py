import re
from fastapi.testclient import TestClient
from sqlalchemy import select
from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import Operator
from replyforge.operators import hash_password, verify_password


def test_password_hash_is_salted():
    raw = 'synthetic-test-password'
    first, second = hash_password(raw), hash_password(raw)
    assert first != second
    assert raw not in first
    assert verify_password(raw, first)
    assert not verify_password('wrong-password', first)


def test_operator_cannot_escalate_privileges(database, test_settings, fake_telegram):
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        page = client.get('/admin/operators', auth=auth)
        token = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        data = {'csrf_token': token, 'username': 'support-staff', 'password': 'synthetic-staff-password', 'role': 'operator'}
        assert client.post('/admin/operators', auth=auth, data=data).status_code == 200
        staff_auth = ('support-staff', 'synthetic-staff-password')
        assert client.get('/admin/tickets', auth=staff_auth).status_code == 200
        for path in ['/admin/operators', '/admin/agent', '/admin/insight', '/admin/system']:
            assert client.get(path, auth=staff_auth).status_code == 403
        for path in ['/admin/operators', '/admin/automation', '/admin/conversations/1/erase']:
            assert client.post(path, auth=staff_auth, data={'csrf_token': token}).status_code == 403
        assert client.post('/admin/operators/1/disable', auth=auth, data={'csrf_token': token}).status_code == 200
        assert client.get('/admin/tickets', auth=staff_auth).status_code == 401
        with session_scope(database) as db:
            assert 'synthetic-staff-password' not in db.scalar(select(Operator)).password_hash
