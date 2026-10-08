"""Read-only catalog importer for Marzban and Pasarguard subscriptions.

Maps panel-issued bearer links to stable, hashed identities. Never downloads
customer-submitted URLs; only trusted panel-admin APIs are contacted.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
import httpx

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .integrations import ProviderError
from .models import Binding
from .security import fingerprint, subscription_token_fingerprint


@dataclass
class SyncStats:
    provider: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    conflicted: int = 0


def list_panel_users(settings: Settings, provider: str, *, max_users: int = 2000,
                     transport=None) -> list[dict]:
    """Fetch paged user summaries. Caller must have authorized read permission."""
    if not 1 <= max_users <= 20000:
        raise ValueError("max_users must be between 1 and 20000")
    if provider not in ("marzban", "pasarguard"):
        raise ValueError("Unsupported provider")
    if provider == "marzban":
        if not (settings.marzban_base_url and settings.marzban_username and settings.marzban_password):
            raise ProviderError("marzban_not_configured")
        base_url = settings.marzban_base_url
    else:
        if not (settings.pasarguard_base_url and settings.pasarguard_api_key):
            raise ProviderError("pasarguard_not_configured")
        base_url = settings.pasarguard_base_url

    result: list[dict] = []
    try:
        with httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=15,
                          transport=transport, follow_redirects=False) as client:
            if provider == "marzban":
                response = client.post("api/admin/token", data={
                    "username": settings.marzban_username,
                    "password": settings.marzban_password,
                })
                response.raise_for_status()
                headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            else:
                headers = {"X-Api-Key": settings.pasarguard_api_key}
            page_size = 100
            for offset in range(0, max_users, page_size):
                limit = min(page_size, max_users - offset)
                response = client.get("api/users", headers=headers,
                                      params={"offset": offset, "limit": limit})
                response.raise_for_status()
                data = response.json()
                records = data.get("users")
                if not isinstance(records, list):
                    raise ProviderError("unexpected_user_listing")
                result.extend(record for record in records if isinstance(record, dict))
                if len(records) < limit or (
                    isinstance(data.get("total"), int)
                    and offset + len(records) >= data["total"]
                ):
                    break
        return result
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError(provider + "_catalog_unavailable") from exc


def sync_provider(session: Session, settings: Settings, provider: str,
                  *, max_users: int = 2000, transport=None) -> SyncStats:
    users = list_panel_users(settings, provider, max_users=max_users, transport=transport)
    stats = SyncStats(provider=provider, fetched=len(users))
    for user in users:
        url = user.get("subscription_url")
        if not isinstance(url, str) or len(url) > 2048:
            stats.skipped += 1
            continue
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            stats.skipped += 1
            continue
        user_ref = str(user.get("username") or "") if provider == "marzban" else str(user.get("id") or "")
        if not user_ref or (provider == "pasarguard" and not user_ref.isdecimal()):
            stats.skipped += 1
            continue
        token_hash = subscription_token_fingerprint(url, settings.binding_pepper)
        if not token_hash:
            stats.skipped += 1
            continue
        exact = fingerprint(url, settings.binding_pepper)
        matches = session.scalars(select(Binding).where(
            or_(Binding.link_hmac == exact,
                (Binding.token_hmac == token_hash) & (Binding.provider == provider))
        )).all()
        if len(matches) > 1 or (
            matches and (matches[0].provider != provider or matches[0].user_ref != user_ref)
        ):
            # Never reassign an existing bearer token to a different account silently.
            stats.conflicted += 1
            continue
        if matches:
            item = matches[0]
            item.token_hmac = token_hash
            stats.updated += 1
        else:
            session.add(Binding(link_hmac=exact, token_hmac=token_hash,
                                provider=provider, user_ref=user_ref,
                                label=str(user.get("username") or "")[:255]))
            stats.inserted += 1
    session.flush()
    return stats
