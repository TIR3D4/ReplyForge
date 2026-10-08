import io
import json
import re
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.insight import analyze_export, read_export
from replyforge.models import InsightCandidate, InsightImport, Knowledge, utcnow
from replyforge.privacy import prune_history


def export_fixture():
    return {'chats': {'list': [{'type': 'personal_chat', 'name': 'Private name', 'messages': [
        {'type': 'message', 'from': 'Customer Name', 'from_id': 'user2', 'text': [
            'Connection failed Customer Name ', {'type': 'email', 'text': 'user@example.com'}]},
        {'type': 'message', 'from': 'Operator Name', 'from_id': 'user1', 'text': 'Please update the subscription.', 'photo': 'photos/a.jpg'},
    ]}]}}


def test_offline_redaction_dedup_and_role_attribution():
    data = export_fixture()
    data['chats']['list'] *= 2
    report = analyze_export(json.dumps(data).encode(), limit=100, operator_ids={'user1'})
    assert len(report.conversations) == 1
    assert report.statistics['duplicate_conversations'] == 1
    assert report.statistics['external_ai_calls'] == 0
    value = str(report)
    for secret in ['user@example.com', 'Customer Name', 'Operator Name', 'Private name', 'user1', 'user2']:
        assert secret not in value
    assert report.conversations[0]['answer'] == 'Please update the subscription.'
    assert report.conversations[0]['outcome'] == 'unverified'


def test_zip_media_inventory_and_traversal_rejection():
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as z:
        z.writestr('export/result.json', json.dumps(export_fixture()))
        z.writestr('export/photos/a.jpg', b'not sent externally')
    report = analyze_export(content.getvalue(), limit=200, operator_ids={'user1'})
    assert report.statistics['media_available'] == 1
    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, 'w') as z:
        z.writestr('../result.json', '{}')
    with pytest.raises(ValueError, match='Unsafe'):
        read_export(malicious.getvalue())


@pytest.mark.parametrize('limit,ids', [(0, {'user1'}), (5001, {'user1'}), (100, set()), (100, {'name'})])
def test_invalid_selection(limit, ids):
    with pytest.raises(ValueError):
        analyze_export(json.dumps(export_fixture()).encode(), limit=limit, operator_ids=ids)


def test_import_review_auth_dedup_and_erasure(database, test_settings, fake_telegram):
    auth = (test_settings.admin_username, test_settings.admin_password)
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        assert client.get('/admin/insight').status_code == 401
        page = client.get('/admin/insight', auth=auth)
        csrf = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        data = {'limit': '100', 'operator_ids': 'user1', 'csrf_token': csrf}
        files = {'export': ('result.json', json.dumps(export_fixture()), 'application/json')}
        assert client.post('/admin/insight/import', auth=auth, data={**data, 'csrf_token': 'bad'}, files=files).status_code == 403
        for _ in range(2):
            assert client.post('/admin/insight/import', auth=auth, data=data, files=files).status_code == 200
        with session_scope(database) as db:
            assert db.scalar(select(func.count(InsightImport.id))) == 1
            assert db.scalar(select(func.count(Knowledge.id))) == 0
            cid = db.scalar(select(InsightCandidate.id))
        decision = {'csrf_token': csrf, 'decision': 'approve', 'question': 'Connection issue', 'answer': 'Update subscription'}
        assert client.post(f'/admin/insight/{cid}/review', auth=auth, data=decision).status_code == 200
        assert client.post(f'/admin/insight/{cid}/review', auth=auth, data=decision).status_code == 409
        with session_scope(database) as db:
            assert db.scalar(select(func.count(Knowledge.id))) == 1
        assert client.post('/admin/insight/imports/1/erase', auth=auth, data={'csrf_token': csrf, 'confirmation': 'ERASE'}).status_code == 200
        with session_scope(database) as db:
            assert db.scalar(select(func.count(InsightCandidate.id))) == 0
            assert db.scalar(select(func.count(InsightImport.id))) == 0
            assert db.scalar(select(func.count(Knowledge.id))) == 1


def test_insight_retention_scrubs_candidate(database):
    with session_scope(database) as db:
        job = InsightImport(fingerprint='synthetic-fingerprint', statistics={})
        db.add(job)
        db.flush()
        db.add(InsightCandidate(import_id=job.id, digest='synthetic', category='general', question='sensitive question', answer='sensitive answer', status='pending', created_at=utcnow()-timedelta(days=200)))
    with session_scope(database) as db:
        assert prune_history(db, 180)['insight_candidates'] == 1
    with session_scope(database) as db:
        c = db.scalar(select(InsightCandidate))
        assert c.question == c.answer == '[expired]'
        assert c.status == 'expired'
        assert prune_history(db, 180)['insight_candidates'] == 0
