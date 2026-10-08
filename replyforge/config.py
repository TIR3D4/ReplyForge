"""Environment and validated business playbook configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    webhook_secret: str
    admin_username: str
    admin_password: str
    binding_pepper: str
    internal_api_key: str
    support_alert_chat_id: int | None
    database_url: str
    business_config: str
    webhook_public_url: str
    webhook_path: str
    poll_seconds: float
    max_llm_calls_per_chat_per_day: int
    lease_seconds: int
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    marzban_base_url: str
    marzban_username: str
    marzban_password: str
    pasarguard_base_url: str
    pasarguard_api_key: str
    allow_http_panels: bool

    @classmethod
    def from_env(cls, *, strict: bool = True) -> "Settings":
        def g(name: str, default: str = "") -> str:
            return os.getenv(name, default).strip()
        obj = cls(
            bot_token=g("BOT_TOKEN"),
            webhook_secret=g("WEBHOOK_SECRET"),
            admin_username=g("ADMIN_USERNAME", "admin"),
            admin_password=g("ADMIN_PASSWORD"),
            binding_pepper=g("BINDING_PEPPER"),
            internal_api_key=g("INTERNAL_API_KEY"),
            support_alert_chat_id=int(g("SUPPORT_ALERT_CHAT_ID")) if g("SUPPORT_ALERT_CHAT_ID") else None,
            database_url=g("DATABASE_URL", "sqlite+pysqlite:///:memory:"),
            business_config=g("BUSINESS_CONFIG", "config/business.yaml"),
            webhook_public_url=g("WEBHOOK_PUBLIC_URL"),
            webhook_path=g("WEBHOOK_PATH", "/telegram/webhook"),
            poll_seconds=float(g("WORKER_POLL_SECONDS", "1")),
            max_llm_calls_per_chat_per_day=int(g("MAX_LLM_CALLS_PER_CHAT_PER_DAY", "40")),
            lease_seconds=int(g("WORKER_LEASE_SECONDS", "120")),
            ai_api_key=g("AI_API_KEY"),
            ai_base_url=g("AI_BASE_URL", "https://api.openai.com/v1"),
            ai_model=g("AI_MODEL", "gpt-4.1-mini"),
            marzban_base_url=g("MARZBAN_BASE_URL"),
            marzban_username=g("MARZBAN_USERNAME"),
            marzban_password=g("MARZBAN_PASSWORD"),
            pasarguard_base_url=g("PASARGUARD_BASE_URL"),
            pasarguard_api_key=g("PASARGUARD_API_KEY"),
            allow_http_panels=g("ALLOW_HTTP_PANELS", "false").lower() == "true",
        )
        if strict:
            required = {
                "BOT_TOKEN": obj.bot_token,
                "WEBHOOK_SECRET": obj.webhook_secret,
                "ADMIN_PASSWORD": obj.admin_password,
                "BINDING_PEPPER": obj.binding_pepper,
                "INTERNAL_API_KEY": obj.internal_api_key,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ConfigError("Missing required secrets: " + ", ".join(missing))
            if min(len(obj.webhook_secret), len(obj.admin_password),
                   len(obj.binding_pepper), len(obj.internal_api_key)) < 16:
                raise ConfigError("Secrets must be at least 16 characters")
        if obj.support_alert_chat_id == 0:
            raise ConfigError("SUPPORT_ALERT_CHAT_ID must be a non-zero Telegram chat ID")
        if obj.max_llm_calls_per_chat_per_day < 0:
            raise ConfigError("MAX_LLM_CALLS_PER_CHAT_PER_DAY cannot be negative")
        if obj.poll_seconds <= 0 or obj.lease_seconds < 20:
            raise ConfigError("Invalid worker intervals")
        if obj.webhook_path != "/telegram/webhook":
            raise ConfigError("V1 only supports WEBHOOK_PATH=/telegram/webhook")
        for name, url in (("AI_BASE_URL", obj.ai_base_url),
                          ("MARZBAN_BASE_URL", obj.marzban_base_url),
                          ("PASARGUARD_BASE_URL", obj.pasarguard_base_url)):
            if url:
                parsed = urlsplit(url)
                if parsed.scheme not in (("https", "http") if obj.allow_http_panels and name != "AI_BASE_URL" else ("https",)):
                    raise ConfigError(name + " must use HTTPS")
                if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ConfigError(name + " is not a valid service URL")
        return obj


@lru_cache
def settings() -> Settings:
    return Settings.from_env()


def parse_playbook_yaml(source: str) -> dict[str, Any]:
    try:
        config = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ConfigError("Invalid YAML syntax") from exc
    return validate_playbook(config)


def load_playbook(path: str | Path) -> dict[str, Any]:
    return parse_playbook_yaml(Path(path).read_text(encoding="utf-8"))


def validate_playbook(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ConfigError("Playbook must be a mapping")
    if not isinstance(config.get("brand"), str) or not config["brand"]:
        raise ConfigError("Playbook requires brand")
    menu = config.get("menu")
    workflows = config.get("workflows")
    if not isinstance(menu, list) or not isinstance(workflows, dict):
        raise ConfigError("Playbook requires menu list and workflows mapping")
    for button in menu:
        if not isinstance(button, dict) or not button.get("label") or not button.get("action"):
            raise ConfigError("Menu buttons require label and action")
        action = button["action"]
        if not isinstance(action, str):
            raise ConfigError("Menu action must be a string")
        if action != "human" and not (action.startswith("flow:") and action[5:] in workflows):
            raise ConfigError("Invalid menu action: " + str(action))
    for name, flow in workflows.items():
        if not isinstance(flow, dict) or not isinstance(flow.get("states"), dict):
            raise ConfigError("Workflow " + name + " requires states")
        states = flow["states"]
        if flow.get("start") not in states:
            raise ConfigError("Workflow " + name + " missing start state")
        for step, state in states.items():
            if not isinstance(state, dict):
                raise ConfigError("Invalid state " + step)
            destination = state.get("next")
            if destination is not None and destination not in states:
                raise ConfigError("Invalid next state " + str(destination))
            options = state.get("options", [])
            if not isinstance(options, list):
                raise ConfigError("Options must be a list")
            if state.get("input") == "choice" and not options:
                raise ConfigError("Choice state requires options")
            for option in options:
                if not isinstance(option, dict) or "label" not in option or "value" not in option:
                    raise ConfigError("Choice options require label and value")
                target = option.get("next", destination)
                if target not in states:
                    raise ConfigError("Invalid option next " + str(target))
            if state.get("type") not in (None, "handoff", "complete", "knowledge"):
                raise ConfigError("Unsupported state type")
            if state.get("type") is None and state.get("input") not in ("text", "choice", "subscription", "photo", "question"):
                raise ConfigError("Unsupported input type")
    return config
