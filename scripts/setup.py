#!/usr/bin/env python3
"""Interactive, secure configuration bootstrap for new ReplyForge deployments."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import secrets


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Generate a secure .env for ReplyForge")
    parser.add_argument("--preset", choices=["generic", "azadbird"], default="generic")
    args = parser.parse_args()
    env_file = ROOT / ".env"
    if env_file.exists():
        raise SystemExit(".env already exists. Aborting to protect existing secrets.")

    token = getpass.getpass("Telegram BotFather token: ").strip()
    if not token or ":" not in token:
        raise SystemExit("Invalid bot token. Nothing was written.")
    domain = input("Public HTTPS origin (e.g. https://support.example.com): ").strip().rstrip("/")
    if not domain.startswith("https://") or "/" in domain[8:] or len(domain) < 12:
        raise SystemExit("Enter a valid HTTPS origin. Nothing was written.")
    username = input("Admin username [admin]: ").strip() or "admin"
    if not username.isascii() or not username.replace("_", "").isalnum():
        raise SystemExit("Admin username must use simple ASCII letters, digits or underscore.")
    password = getpass.getpass("Admin password (min 16 chars): ")
    if len(password) < 16 or "\n" in password or "\r" in password:
        raise SystemExit("Password must contain at least 16 characters, no newlines.")

    preset = "examples/azadbird.yaml" if args.preset == "azadbird" else "config/business.yaml"
    replacements = {
        "BOT_TOKEN": token,
        "WEBHOOK_SECRET": secrets.token_hex(32),
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD": password,
        "BINDING_PEPPER": secrets.token_hex(32),
        "INTERNAL_API_KEY": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "WEBHOOK_PUBLIC_URL": domain,
        "BUSINESS_CONFIG": preset,
    }
    sample = (ROOT / ".env.example").read_text(encoding="utf-8")
    lines = []
    for line in sample.splitlines():
        key, sep, _ = line.partition("=")
        if sep and key in replacements:
            # We do not interpolate untrusted values into shell commands.
            if any(ch in replacements[key] for ch in ("\n", "\r", "#")):
                raise SystemExit("Forbidden character in input; .env not written.")
            line = key + "=" + replacements[key]
        lines.append(line)
    os.umask(0o077)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Created .env (mode 0600). Keep it private.")
    print("Next: docker compose up -d --build")
    print("Then: docker compose exec api replyforge set-webhook")


if __name__ == "__main__":
    main()
