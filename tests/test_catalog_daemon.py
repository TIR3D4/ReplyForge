"""Optional catalog-sync process is isolated from customer responses."""
from replyforge.database import session_scope
from replyforge.models import Control
from replyforge.syncer import run_once


def test_catalog_sync_continues_after_one_provider_fails(database, test_settings, monkeypatch):
    providers = []
    def fake_sync(db, settings, provider, max_users):
        providers.append(provider)
        if provider == "marzban":
            raise RuntimeError("panel offline")
        from replyforge.catalog import SyncStats
        return SyncStats(provider="pasarguard", fetched=2, inserted=2)
    monkeypatch.setattr("replyforge.syncer.sync_provider", fake_sync)
    result = run_once(test_settings, database, "both", 10)
    assert providers == ["marzban", "pasarguard"]
    assert result[0][1] is False and result[1][1] is True
    with session_scope(database) as db:
        assert "failed" in db.get(Control, "catalog_marzban").value
        assert "ok" in db.get(Control, "catalog_pasarguard").value
