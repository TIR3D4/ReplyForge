from fastapi.testclient import TestClient
from replyforge.app import build_app


def test_failed_login_throttle_is_shared_between_app_instances(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        for _ in range(30):
            assert client.get('/admin', auth=('wrong', 'wrong')).status_code == 401
        assert client.get('/admin', auth=('wrong', 'wrong')).status_code == 429
    with TestClient(build_app(test_settings, factory=database, telegram=fake_telegram)) as other:
        assert other.get('/admin', auth=('wrong', 'wrong')).status_code == 429
