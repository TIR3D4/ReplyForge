"""Provider-adapter boundary. No user-controlled URL is ever fetched."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from .config import Settings


@dataclass(frozen=True)
class SubscriptionStatus:
    provider: str
    status: str
    used_bytes: int
    limit_bytes: int | None
    expires_at: datetime | None
    checked_at: datetime
    error: str | None = None

    @property
    def remaining_bytes(self) -> int | None:
        if self.limit_bytes is None:
            return None
        return max(0, self.limit_bytes - self.used_bytes)


def _expiration(value):
    if not value or value == 0:
        return None
    try:
        if isinstance(value, str) and not value.isdigit():
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        # Marzban sends seconds as int, some clients send milliseconds.
        raw = int(value)
        if raw > 100_000_000_000:
            raw //= 1000
        return datetime.fromtimestamp(raw, timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None


def normalize(provider: str, value: dict) -> SubscriptionStatus:
    # Missing or changed upstream fields must not become fabricated unlimited accounts.
    if not isinstance(value, dict) or not {'status', 'used_traffic', 'data_limit', 'expire'} <= value.keys():
        raise ProviderError(provider + "_schema_mismatch")
    if value['status'] not in ('active', 'disabled', 'limited', 'expired', 'on_hold'):
        raise ProviderError(provider + "_unknown_status")
    for key in ('used_traffic', 'data_limit'):
        item = value[key]
        if item is None and key == 'data_limit':
            continue
        if type(item) is not int or item < 0:
            raise ProviderError(provider + "_invalid_usage")
    if value['expire'] not in (None, 0) and _expiration(value['expire']) is None:
        raise ProviderError(provider + "_invalid_expiration")
    limit = int(value.get("data_limit") or 0)
    return SubscriptionStatus(
        provider=provider,
        status=str(value.get("status") or "unknown"),
        used_bytes=int(value.get("used_traffic") or 0),
        limit_bytes=limit if limit > 0 else None,
        expires_at=_expiration(value.get("expire")),
        checked_at=datetime.now(timezone.utc),
    )


class ProviderError(Exception):
    pass


def verify_version(client, headers: dict, expected: str, provider: str) -> None:
    """Optional exact-version gate. Never infer protocol compatibility from branding.

    PasarGuard requires system.read in addition to users.read for this opt-in
    probe. Keep the default users.read-only path available to least-privilege keys.
    """
    if not expected:
        return
    response = client.get("api/system", headers=headers)
    response.raise_for_status()
    data = response.json()
    actual = data.get("version") if isinstance(data, dict) else None
    if not isinstance(actual, str) or actual.removeprefix("v") != expected.removeprefix("v"):
        raise ProviderError(provider + "_version_mismatch")


class MarzbanAdapter:
    def __init__(self, settings: Settings, *, transport=None):
        self.s = settings
        self.transport = transport

    def lookup(self, user_ref: str) -> SubscriptionStatus:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_]{1,255}", user_ref):
            raise ProviderError("marzban_invalid_user_ref")
        if not self.s.marzban_base_url or not self.s.marzban_username or not self.s.marzban_password:
            raise ProviderError("marzban_not_configured")
        try:
            with httpx.Client(base_url=self.s.marzban_base_url.rstrip("/") + "/", timeout=8,
                              transport=self.transport, follow_redirects=False) as client:
                auth = client.post("api/admin/token", data={
                    "username": self.s.marzban_username, "password": self.s.marzban_password,
                })
                auth.raise_for_status()
                token = auth.json()["access_token"]
                headers = {"Authorization": "Bearer " + token}
                verify_version(client, headers, self.s.marzban_expected_version, "marzban")
                result = client.get("api/user/" + quote(user_ref, safe=""), headers=headers)
                result.raise_for_status()
                return normalize("marzban", result.json())
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise ProviderError("marzban_unavailable") from exc


class PasarguardAdapter:
    def __init__(self, settings: Settings, *, transport=None):
        self.s = settings
        self.transport = transport

    def lookup(self, user_ref: str) -> SubscriptionStatus:
        if not self.s.pasarguard_base_url or not self.s.pasarguard_api_key:
            raise ProviderError("pasarguard_not_configured")
        # Use a stable numeric ID when provisioned. Avoid username/ID API ambiguity.
        if not user_ref.isdecimal():
            raise ProviderError("pasarguard_requires_numeric_user_id")
        try:
            with httpx.Client(base_url=self.s.pasarguard_base_url.rstrip("/") + "/", timeout=8,
                              transport=self.transport, follow_redirects=False) as client:
                headers = {"X-Api-Key": self.s.pasarguard_api_key}
                verify_version(client, headers, self.s.pasarguard_expected_version, "pasarguard")
                r = client.get("api/user/by-id/" + quote(user_ref, safe=""), headers=headers)
                r.raise_for_status()
                return normalize("pasarguard", r.json())
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("pasarguard_unavailable") from exc


def lookup(settings: Settings, provider: str, user_ref: str) -> SubscriptionStatus:
    if provider == "marzban":
        return MarzbanAdapter(settings).lookup(user_ref)
    if provider == "pasarguard":
        return PasarguardAdapter(settings).lookup(user_ref)
    raise ProviderError("unknown_provider")


def describe(status: SubscriptionStatus, locale: str) -> str:
    fa = locale == "fa"
    if status.expires_at:
        expiry = status.expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:
        expiry = "بدون تاریخ مشخص" if fa else "not set"
    if status.remaining_bytes is None:
        remaining = "نامحدود" if fa else "unlimited"
    else:
        remaining = f"{status.remaining_bytes / 1024**3:.2f} GB"
    if fa:
        return f"📊 وضعیت ثبت‌شده سرویس: {status.status}\nحجم باقی‌مانده: {remaining}\nانقضا: {expiry}\nاین اطلاعات وضعیت حسابه؛ سلامت اتصال رو تضمین نمی‌کنه."
    return f"📊 Account status: {status.status}\nRemaining quota: {remaining}\nExpiry: {expiry}\nAn active account does not guarantee network connectivity."
