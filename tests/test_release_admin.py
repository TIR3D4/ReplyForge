import re
from fastapi.testclient import TestClient
from sqlalchemy import select
from replyforge.app import build_app
from replyforge.database import session_scope
from replyforge.models import PlaybookVersion
from test_insight_worker import seed, Model
from replyforge.insight_worker import tick


def test_guided_builder_and_reviewed_workflow_publication(database, test_settings, fake_telegram):
    task_id = seed(database)
    tick(database, test_settings, engine_class=Model)
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        client.auth = (test_settings.admin_username, test_settings.admin_password)
        page = client.get('/admin/playbook')
        token = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        common = {'csrf_token':token}
        assert client.post('/admin/playbook/create-flow', data={**common,'name':'returns','title':'Returns','prompt':'Order?'}).status_code == 200
        assert client.post('/admin/playbook/build-step', data={**common,'flow':'returns','step':'start','kind':'text','prompt':'Which order?','target':'missing'}).status_code == 422
        response = client.post(f'/admin/insight/tasks/{task_id}/publish-workflow', data={**common,
            'name':'learned','title':'Learned support','steps':'Update subscription\nTry another network'})
        assert response.status_code == 200
        assert client.post(f'/admin/insight/tasks/{task_id}/publish-workflow', data={**common,
            'name':'again','title':'Again','steps':'Update'}).status_code == 409
        assert client.get('/admin/inbox').status_code == 200
    with session_scope(database) as db:
        active = db.scalar(select(PlaybookVersion).where(PlaybookVersion.active.is_(True)))
        assert 'learned' in active.source


def test_service_notice_requires_admin_and_reaches_menu(database, test_settings, fake_telegram):
    from replyforge.workflow import root_menu
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as client:
        client.auth = (test_settings.admin_username, test_settings.admin_password)
        page = client.get('/admin/connections')
        token = re.search(r'name="csrf_token" value="([^"]+)', page.text)[1]
        assert client.post('/admin/service-notice', data={'csrf_token':token,'message':'Maintenance until 14:00'}).status_code == 200
    assert 'Maintenance' in root_menu({'welcome':'Hello','menu':[], 'service_notice':'Maintenance'}).text
