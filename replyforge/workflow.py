"""Declarative, persistent conversation state machine. All replies are proposals."""
from __future__ import annotations

from dataclasses import dataclass, field
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import AIEngine
from .config import Settings
from .integrations import ProviderError, describe, lookup
from .models import Binding, Conversation, Knowledge, Ticket
from .security import extract_link, fingerprint, redact


@dataclass
class Proposal:
    text: str
    actions: list[tuple[str, str]] = field(default_factory=list)
    menu: bool = True


def is_fa(playbook):
    return playbook.get("locale") == "fa"


def root_menu(playbook: dict) -> Proposal:
    return Proposal(
        playbook["welcome"],
        [(button["label"], button["action"]) for button in playbook["menu"]],
    )


def human(session: Session, conversation: Conversation, playbook: dict, reason="requested") -> Proposal:
    conversation.owner = "human_pending"
    existing = session.scalar(select(Ticket).where(
        Ticket.conversation_id == conversation.id, Ticket.status == "open",
    ))
    if existing is None:
        session.add(Ticket(conversation_id=conversation.id, reason=reason))
    return Proposal(playbook.get("handoff_text", "Human support has been requested."), [], False)


def _choose_actions(playbook: dict, state: dict) -> list[tuple[str, str]]:
    actions = [(str(item["label"]), "choose:" + str(item["value"])) for item in state.get("options", [])]
    actions.append(("👩‍💻 اپراتور" if is_fa(playbook) else "👩‍💻 Human", "human"))
    actions.append(("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Main menu", "home"))
    return actions


def _display_state(session: Session, conversation: Conversation, playbook: dict,
                   ai: AIEngine, settings: Settings) -> Proposal:
    """Follow terminal states without asking the customer to click an empty menu."""
    for _ in range(10):
        flow = playbook["workflows"][conversation.workflow]
        state = flow["states"][conversation.step]
        kind = state.get("type")
        if kind == "handoff":
            return human(session, conversation, playbook, reason=conversation.workflow)
        if kind == "complete":
            conversation.workflow = None
            conversation.step = None
            return Proposal(playbook.get("resolution_text", "Done."),
                            [("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Main menu", "home")])
        if kind == "knowledge":
            q = str((conversation.state or {}).get("answers", {}).get("question", ""))
            entries = session.scalars(select(Knowledge).where(Knowledge.enabled.is_(True))).all()
            answer = ai.knowledge_answer(q, entries)
            if answer is None:
                return human(session, conversation, playbook, reason="knowledge_unavailable")
            conversation.workflow = None
            conversation.step = None
            return Proposal(answer, [("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Main menu", "home")])
        prompt = str(state.get("prompt", "Please provide the requested information."))
        if conversation.step == "refresh":
            app_name = str((conversation.state or {}).get("answers", {}).get("application", "")).casefold()
            for app_key, guide in (playbook.get("tutorials") or {}).items():
                if str(app_key).casefold() in app_name:
                    prompt = str(guide) + "\n\n" + prompt
                    break
        return Proposal(prompt, _choose_actions(playbook, state))
    return human(session, conversation, playbook, reason="workflow_cycle")


def start_flow(session: Session, conv: Conversation, playbook: dict, ai: AIEngine,
               settings: Settings, name: str) -> Proposal:
    flow = playbook["workflows"].get(name)
    if flow is None:
        return root_menu(playbook)
    conv.workflow = name
    conv.step = flow["start"]
    conv.state = {"answers": {}}
    return _display_state(session, conv, playbook, ai, settings)


def apply_action(session: Session, conv: Conversation, playbook: dict, ai: AIEngine,
                 settings: Settings, action: str) -> Proposal:
    if conv.owner != "ai":
        return Proposal(playbook.get("handoff_text", "Human assistance is active."), [], False)
    if action == "human":
        return human(session, conv, playbook)
    if action == "home":
        conv.workflow = None
        conv.step = None
        conv.state = {}
        return root_menu(playbook)
    if action.startswith("flow:"):
        return start_flow(session, conv, playbook, ai, settings, action[5:])
    if action.startswith("choose:") and conv.workflow and conv.step:
        flow = playbook["workflows"][conv.workflow]
        state = flow["states"][conv.step]
        if state.get("input") != "choice":
            return _display_state(session, conv, playbook, ai, settings)
        value = action[7:]
        option = next((o for o in state.get("options", []) if str(o["value"]) == value), None)
        if option is None:
            return _display_state(session, conv, playbook, ai, settings)
        info = dict(conv.state or {})
        answers = dict(info.get("answers") or {})
        answers[str(state.get("field", conv.step))] = value
        info["answers"] = answers
        conv.state = info
        conv.step = option.get("next", state.get("next"))
        return _display_state(session, conv, playbook, ai, settings)
    return root_menu(playbook)


def _is_subscription_active(status):
    return status.status.casefold() == "active" and (
        status.remaining_bytes is None or status.remaining_bytes > 0
    ) and (status.expires_at is None or status.expires_at > status.checked_at)


def accept_input(session: Session, conv: Conversation, playbook: dict, ai: AIEngine,
                 settings: Settings, text: str, photo_file_id: str | None) -> Proposal:
    if conv.owner != "ai":
        return Proposal("", [], False)
    lowered = text.casefold()
    if any(hint in lowered for hint in ("پشتیبان انسانی", "اپراتور انسانی", "human support", "speak to human")):
        return human(session, conv, playbook)
    if lowered.strip() in ("منو", "منوی اصلی", "menu", "/start"):
        return apply_action(session, conv, playbook, ai, settings, "home")
    if not conv.workflow:
        action = ai.select_intent(redact(text), playbook["menu"]) if text else None
        if action:
            proposal = apply_action(session, conv, playbook, ai, settings, action)
            if action == "flow:question" and text.strip() and conv.workflow:
                return accept_input(session, conv, playbook, ai, settings, text, photo_file_id)
            return proposal
        if text.strip():
            entries = session.scalars(select(Knowledge).where(Knowledge.enabled.is_(True))).all()
            answer = ai.knowledge_answer(text, entries)
            if answer is not None:
                return Proposal(answer, [("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Menu", "home")])
        return root_menu(playbook)

    flow = playbook["workflows"][conv.workflow]
    state = flow["states"][conv.step]
    kind = state.get("input")
    if kind == "choice":
        value = ai.select_choice(redact(text), state.get("options", []))
        if value is None:
            return Proposal(
                "یکی از گزینه‌ها رو انتخاب کن یا توضیح بیشتری بده." if is_fa(playbook)
                else "Please select an option or clarify.",
                _choose_actions(playbook, state),
            )
        return apply_action(session, conv, playbook, ai, settings, "choose:" + value)
    if kind == "photo":
        if not photo_file_id:
            return _display_state(session, conv, playbook, ai, settings)
        value = photo_file_id
    elif kind == "subscription":
        url = extract_link(text)
        if not url:
            return _display_state(session, conv, playbook, ai, settings)
        binding = session.scalar(select(Binding).where(
            Binding.link_hmac == fingerprint(url, settings.binding_pepper),
        ))
        if binding is None or (binding.customer_chat_id is not None and binding.customer_chat_id != conv.chat_id):
            return human(session, conv, playbook, reason="subscription_unmatched")
        try:
            status = lookup(settings, binding.provider, binding.user_ref)
        except ProviderError:
            return human(session, conv, playbook, reason="panel_unavailable")
        details = describe(status, playbook.get("locale", "en"))
        if not _is_subscription_active(status):
            conv.workflow, conv.step = None, None
            return Proposal(details + (
                "\nبرای بررسی یا تمدید می‌تونی به اپراتور پیام بدی."
                if is_fa(playbook) else "\nPlease contact support for help with renewal."
            ), [("👩‍💻 اپراتور" if is_fa(playbook) else "👩‍💻 Human", "human"),
                ("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Menu", "home")])
        value = "verified:" + binding.provider  # never store raw subscription tokens
    elif kind in ("text", "question"):
        if not text.strip():
            return _display_state(session, conv, playbook, ai, settings)
        value = redact(text)[:500]
    else:
        return _display_state(session, conv, playbook, ai, settings)

    data = dict(conv.state or {})
    answers = dict(data.get("answers") or {})
    answers[str(state.get("field", conv.step))] = value
    data["answers"] = answers
    conv.state = data
    conv.step = state.get("next")
    next_proposal = _display_state(session, conv, playbook, ai, settings)
    if kind == "subscription":
        next_proposal.text = details + "\n\n" + next_proposal.text
    return next_proposal


def build_markup(conversation: Conversation, actions: list[tuple[str, str]]):
    """Callback data <=64 bytes. Verify this nonce and button index on every click."""
    nonce = secrets.token_hex(4)
    data = dict(conversation.state or {})
    data["menu_nonce"] = nonce
    data["menu_actions"] = [action for _, action in actions]
    conversation.state = data
    rows = [
        [{"text": label[:50], "callback_data": f"rf:{nonce}:{idx}"}]
        for idx, (label, _action) in enumerate(actions[:20])
    ]
    return {"inline_keyboard": rows} if rows else None


def callback_action(conv: Conversation, payload: str) -> str | None:
    pieces = payload.split(":")
    if len(pieces) != 3 or pieces[0] != "rf":
        return None
    state = conv.state or {}
    if pieces[1] != state.get("menu_nonce"):
        return None
    try:
        idx = int(pieces[2])
        return state.get("menu_actions", [])[idx] if 0 <= idx < 20 else None
    except (ValueError, TypeError, IndexError):
        return None
