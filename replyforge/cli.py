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


def main() -> None:
    parser = argparse.ArgumentParser(prog="replyforge")
    parser.add_argument("command", choices=["init", "worker", "webhook-info", "set-webhook", "check-config"])
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
