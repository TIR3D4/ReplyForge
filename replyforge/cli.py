"""Command-line setup and worker entry point."""
from __future__ import annotations

import argparse
import logging

from .config import Settings, load_playbook
from .database import session_factory
from alembic import command
from alembic.config import Config
from .telegram import TelegramClient
from .worker import Processor
from .catalog import sync_provider
from .database import session_scope
from .privacy import prune_history
from .syncer import run_periodically


def main() -> None:
    parser = argparse.ArgumentParser(prog="replyforge")
    parser.add_argument("command", choices=["init", "worker", "webhook-info", "set-webhook", "check-config", "sync-subscriptions", "sync-daemon", "prune"])
    parser.add_argument("--provider", choices=["marzban", "pasarguard", "both"], default="both")
    parser.add_argument("--limit", type=int, default=2000, help="Maximum users per provider, up to 20000")
    parser.add_argument("--interval-minutes", type=int, default=60, help="sync-daemon polling interval (5-1440)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env(strict=args.command not in ("check-config",))
    cfg = load_playbook(s.business_config)
    if args.command == "check-config":
        print("Valid playbook:", cfg["brand"], "workflows:", ", ".join(cfg["workflows"]))
        return
    engine, factory = session_factory(s.database_url)
    if args.command == "init":
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", s.database_url.replace("%", "%%"))
        command.upgrade(alembic_cfg, "head")
        print("ReplyForge migrations up to date.")
        return
    if args.command == "prune":
        with session_scope(factory) as db:
            summary = prune_history(db, s.retention_days)
        print("Pruned expired support content:", summary)
        return
    if args.command == "sync-daemon":
        run_periodically(s, factory, args.provider, args.limit, args.interval_minutes)
        return
    if args.command == "sync-subscriptions":
        providers = ("marzban", "pasarguard") if args.provider == "both" else (args.provider,)
        for provider in providers:
            try:
                with session_scope(factory) as db:
                    summary = sync_provider(db, s, provider, max_users=args.limit)
                    print(provider, "fetched:", summary.fetched, "new:", summary.inserted,
                          "updated:", summary.updated, "skipped:", summary.skipped,
                          "conflicts:", summary.conflicted)
            except Exception as exc:
                logging.error("Subscription sync failed for %s (%s)", provider, type(exc).__name__)
                raise SystemExit(2) from exc
        return
    bot = TelegramClient(s.bot_token)
    try:
        if args.command == "worker":
            Processor(s, factory, bot).run()
        elif args.command == "webhook-info":
            print(bot.webhook_info())
        elif args.command == "set-webhook":
            if not s.webhook_public_url.startswith("https://"):
                raise RuntimeError("WEBHOOK_PUBLIC_URL must be HTTPS")
            public_url = s.webhook_public_url.rstrip("/") + s.webhook_path
            print(bot.set_webhook(public_url, s.webhook_secret))
    finally:
        bot.close()


if __name__ == "__main__":
    main()
