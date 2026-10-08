"""Declarative, persistent conversation state machine. All replies are proposals."""
from __future__ import annotations

from dataclasses import dataclass, field
import secrets
from datetime import datetime, timezone
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .agent import AIEngine
from .config import Settings
from .integrations import ProviderError, describe, lookup
from .models import Audit, Binding, Conversation, Knowledge, Ticket
from .security import extract_link, fingerprint, redact, subscription_token_fingerprint


@dataclass
class Proposal:
    text: str
    actions: list[tuple[str, str]] = field(default_factory=list)
    menu: bool = True




def infer_customer_slots(text: str) -> dict[str, str]:
    """Extract obvious customer-provided device/app details without an LLM call."""
    value = (text or "").casefold()
    slots: dict[str, str] = {}
    if any(x in value for x in ("آیفون", "ایفون", "iphone", "ios")):
        slots["device"] = "ios"
    elif any(x in value for x in ("اندروید", "android", "سامسونگ", "شیائومی")):
        slots["device"] = "android"
    elif any(x in value for x in ("ویندوز", "windows", "لپ تاپ", "لپ‌تاپ")):
        slots["device"] = "windows"
    for name, aliases in (
        ("v2rayNG", ("v2rayng", "وی تو ری ان جی")),
        ("V2Box", ("v2box", "وی تو باکس")),
        ("Streisand", ("streisand", "استرایسند")),
        ("Happ", ("happ",)),
        ("Hiddify", ("hiddify", "هیدیفای")),
    ):
        if any(re.search(r"\b" + re.escape(alias) + r"\b", value) for alias in aliases):
            slots["application"] = name
            break
    return slots

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
        # Don't re-ask what the customer already explicitly told us during this flow.
        if conversation.workflow == "connection" and conversation.step in ("device", "app"):
            field = "device" if conversation.step == "device" else "application"
            prefilled = (conversation.state or {}).get("recent_slots", {}).get(field)
            if prefilled and state.get("field") == field and state.get("next"):
                data = dict(conversation.state or {})
                answers = dict(data.get("answers") or {})
                answers[field] = prefilled
                data["answers"] = answers
                data["recent_slots"] = {k: v for k, v in data["recent_slots"].items() if k != field}
                conversation.state = data
                conversation.step = state["next"]
                continue
        kind = state.get("type")
        if kind == "handoff":
            return human(session, conversation, playbook, reason=conversation.workflow)
        if kind == "complete":
            conversation.workflow = None
            conversation.step = None
            question = "مشکلت کامل حل شد؟" if is_fa(playbook) else "Was your issue resolved?"
            return Proposal(playbook.get("resolution_text", "Done.") + "\n\n" + question,
                            [("✅ بله" if is_fa(playbook) else "✅ Yes", "feedback:yes"),
                             ("❌ نه" if is_fa(playbook) else "❌ No", "feedback:no"),
                             ("🏠 منو" if is_fa(playbook) else "🏠 Menu", "home")])
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
    prior_slots = dict((conv.state or {}).get("recent_slots") or {})
    conv.state = {"answers": {}, "recent_slots": prior_slots,
                  "flow_started_at": datetime.now(timezone.utc).isoformat()}
    return _display_state(session, conv, playbook, ai, settings)


def apply_action(session: Session, conv: Conversation, playbook: dict, ai: AIEngine,
                 settings: Settings, action: str) -> Proposal:
    if conv.owner != "ai":
        return Proposal(playbook.get("handoff_text", "Human assistance is active."), [], False)
    if action == "human":
        return human(session, conv, playbook)
    if action == "feedback:yes":
        session.add(Audit(conversation_id=conv.id, actor="customer", action="feedback_positive"))
        return Proposal(
            "ممنون از بازخوردت 🌿" if is_fa(playbook) else "Thanks for your feedback!",
            [("🏠 منوی اصلی" if is_fa(playbook) else "🏠 Main menu", "home")],
        )
    if action == "feedback:no":
        session.add(Audit(conversation_id=conv.id, actor="customer", action="feedback_negative"))
        return human(session, conv, playbook, reason="unsolved_after_guidance")
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
    slots = infer_customer_slots(text)
    if slots:
        info = dict(conv.state or {})
        info["recent_slots"] = {**info.get("recent_slots", {}), **slots}
        conv.state = info
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
        digest = fingerprint(url, settings.binding_pepper)
        token_digest = subscription_token_fingerprint(url, settings.binding_pepper)
        clauses = [Binding.link_hmac == digest]
        if token_digest is not None:
            clauses.append(Binding.token_hmac == token_digest)
        matches = session.scalars(select(Binding).where(or_(*clauses))).all()
        matches = [entry for entry in matches if (
            entry.customer_chat_id is None or entry.customer_chat_id == conv.chat_id
        )]
        # Ambiguous or unknown ownership is never resolved by guessing.
        if len(matches) != 1:
            return human(session, conv, playbook, reason="subscription_unmatched")
        binding = matches[0]
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
    buttons = [
        {"text": label[:50], "callback_data": f"rf:{nonce}:{idx}"}
        for idx, (label, _action) in enumerate(actions[:20])
    ]
    rows: list[list[dict]] = []
    for button in buttons:
        if (rows and len(rows[-1]) == 1 and
                len(rows[-1][0]["text"]) <= 22 and len(button["text"]) <= 22):
            rows[-1].append(button)
        else:
            rows.append([button])
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
