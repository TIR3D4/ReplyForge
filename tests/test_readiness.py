"""Operational readiness must not claim healthy when the worker has stopped."""
from fastapi.testclient import TestClient

from replyforge.app import build_app
from replyforge.worker import Processor, worker_is_alive
from replyforge.database import session_scope


def test_ready_endpoint_requires_worker_heartbeat(database, test_settings, fake_telegram):
    app = build_app(test_settings, factory=database, telegram=fake_telegram)
    with TestClient(app) as client:
        healthy_api = client.get("/healthz")
        assert healthy_api.status_code == 200
        readiness = client.get("/readyz")
        assert readiness.status_code == 503
        assert readiness.json()["worker"] == "stale_or_missing"
        Processor(test_settings, database, fake_telegram).heartbeat()
        assert client.get("/readyz").status_code == 200
    with session_scope(database) as session:
        assert worker_is_alive(session)
