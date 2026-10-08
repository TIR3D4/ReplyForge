"""Credential-safe handling of customer content."""
from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import urlsplit

CONFIG_LINK = re.compile(r"(?i)(?:https?://[^\s<>]+|(?:vless|vmess|trojan|ss|hysteria2|hy2|tuic|wg)://[^\s<>]+)")
BANK_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
TOKEN = re.compile(r"(?i)(?:bearer|token|password|secret)[ \t]*[:=][ \t]*\S+")


def redact(text: str) -> str:
    return TOKEN.sub("[redacted credential]", BANK_CARD.sub("[redacted number]", CONFIG_LINK.sub("[redacted link]", text or ""))[:4000]


def extract_link(text: str) -> str | None:
    match = CONFIG_LINK.search(text or "")
    if not match:
        return None
    value = match.group(0).rstrip(".,;)]}")
    return value if 4 <= len(value) <= 2048 else None


def fingerprint(value: str, pepper: str) -> str:
    """HMAC avoids an unsalted searchable table of private subscription tokens."""
    value = value.strip()
    if not value or len(value) > 2048:
        raise ValueError("Invalid link")
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def constant_time_equal(expected: str, actual: str) -> bool:
    return hmac.compare_digest(expected.encode(), actual.encode())


def ensure_public_http_url(value: str) -> None:
    """Do not fetch customer-controlled URLs; this validates admin URLs only."""
    split = urlsplit(value)
    if split.scheme != "https" or not split.hostname:
        raise ValueError("An HTTPS URL is required")
