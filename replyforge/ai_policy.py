"""Validated, non-secret runtime AI settings. Tools remain deterministic and read-only."""
from dataclasses import replace
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from .models import Control, utcnow


class AIPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(default='gpt-4.1-mini', min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_./:-]+$')
    fallback_model: str = Field(default='', max_length=120, pattern=r'^[A-Za-z0-9_./:-]*$')
    max_output_tokens: int = Field(default=250, ge=32, le=2000)
    calls_per_chat_per_day: int = Field(default=40, ge=0, le=500)
    vision_enabled: bool = False
    voice_enabled: bool = False


def policy_for(session, settings) -> AIPolicy:
    values = dict(model=settings.ai_model, fallback_model=settings.ai_fallback_model,
                  max_output_tokens=settings.ai_max_output_tokens,
                  calls_per_chat_per_day=settings.max_llm_calls_per_chat_per_day,
                  vision_enabled=settings.vision_enabled, voice_enabled=settings.voice_enabled)
    for row in session.scalars(select(Control).where(Control.key.like('ai.%'))):
        key = row.key[3:]
        if key in AIPolicy.model_fields:
            values[key] = row.value
    return AIPolicy.model_validate(values)


def effective_settings(session, settings):
    policy = policy_for(session, settings)
    return replace(settings, ai_model=policy.model, ai_fallback_model=policy.fallback_model,
                   ai_max_output_tokens=policy.max_output_tokens,
                   max_llm_calls_per_chat_per_day=policy.calls_per_chat_per_day,
                   vision_enabled=policy.vision_enabled, voice_enabled=policy.voice_enabled)


def save_policy(session, policy: AIPolicy) -> None:
    for key, value in policy.model_dump().items():
        name = 'ai.' + key
        serialized = str(value).lower() if isinstance(value, bool) else str(value)
        row = session.get(Control, name)
        if row is None:
            session.add(Control(key=name, value=serialized))
        else:
            row.value = serialized
            row.updated_at = utcnow()
