"""Optional, isolated periodic subscription catalog importer.

This runs as a separate process from the support Worker so slow panel APIs
cannot delay Telegram customer replies.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import sessionmaker

from .catalog import sync_provider
from .config import Settings
from .database import session_scope
from .models import Audit, Control, utcnow

log = logging.getLogger(__name__)


def run_once(settings: Settings, factory: sessionmaker, provider: str, limit: int):
    """Returns per-provider results, and continues after one provider fails."""
    chosen = ("marzban", "pasarguard") if provider == "both" else (provider,)
    results = []
    for name in chosen:
        if name not in ("marzban", "pasarguard"):
            raise ValueError("Invalid provider")
        try:
            with session_scope(factory) as db:
                summary = sync_provider(db, settings, name, max_users=limit)
                status = f"ok fetched={summary.fetched} added={summary.inserted} updated={summary.updated} conflicts={summary.conflicted}"
                results.append((name, True, status))
                db.add(Audit(actor="catalog", action="sync_complete", detail=name + " " + status))
        except Exception as exc:
            status = "failed_" + type(exc).__name__
            log.warning("Catalog sync failed for %s (%s)", name, type(exc).__name__)
            results.append((name, False, status))
        with session_scope(factory) as db:
            key = "catalog_" + name
            record = db.get(Control, key)
            value = utcnow().isoformat() + "|" + status
            if record:
                record.value = value
                record.updated_at = utcnow()
            else:
                db.add(Control(key=key, value=value))
    return results


def run_periodically(settings: Settings, factory: sessionmaker, provider: str,
                     limit: int, interval_minutes: int) -> None:
    if not 5 <= interval_minutes <= 1440:
        raise ValueError("Interval must be 5 to 1440 minutes")
    log.info("Read-only subscription catalog sync started: %s every %d minutes",
             provider, interval_minutes)
    while True:
        run_once(settings, factory, provider, limit)
        time.sleep(interval_minutes * 60)
