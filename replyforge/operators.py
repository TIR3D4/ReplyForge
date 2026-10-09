"""Local operator credentials with explicit role boundaries; no plaintext password persistence."""
import hashlib
import hmac
import secrets
import re


def hash_password(password: str) -> str:
    if not 16 <= len(password) <= 256:
        raise ValueError('Password must have 16–256 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def verify_password(password: str, encoded: str) -> bool:
    if len(password) > 256:
        return False
    try:
        method, salt, expected = encoded.split('$')
        if method != 'scrypt':
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


def operator_route_allowed(method: str, path: str) -> bool:
    if method == 'GET':
        return path in ('/admin/tickets', '/admin/inbox') or bool(re.fullmatch(r'/admin/(conversations|media)/\d+', path))
    if method != 'POST':
        return False
    return bool(re.fullmatch(r'/admin/(?:conversations/\d+/(?:reply|suggest|takeover|resume|draft/\d+/dismiss)|tickets/\d+/(?:triage|notes|close|reopen))', path))
