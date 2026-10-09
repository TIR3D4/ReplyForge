"""Durable, conservative model cost reservations, independent of support transactions."""
from decimal import Decimal, ROUND_CEILING
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .database import session_scope
from .models import AIBudgetDay, AIUsage, utcnow


def micros(tokens: int, price: str) -> int:
    # USD per million tokens is numerically micro-USD per token.
    return int((Decimal(tokens) * Decimal(price)).to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    def __init__(self, factory, settings, scope: str):
        self.factory, self.settings, self.scope = factory, settings, scope

    def reserve(self, model: str, input_bound: int, output_bound: int) -> str | None:
        s = self.settings
        if Decimal(s.ai_input_price) <= 0 or Decimal(s.ai_output_price) <= 0:
            return None  # Unknown pricing is never treated as free usage.
        amount = micros(input_bound, s.ai_input_price) + micros(output_bound, s.ai_output_price)
        ceiling = micros(1_000_000, s.ai_daily_budget_usd)
        day = utcnow().date().isoformat()
        try:
            with session_scope(self.factory) as db:
                dialect = db.bind.dialect.name
                if dialect == 'postgresql':
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                db.execute(insert(AIBudgetDay).values(day=day, used_microusd=0).on_conflict_do_nothing())
                bucket = db.get(AIBudgetDay, day, with_for_update=True)
                calls = db.scalar(select(func.count(AIUsage.id)).where(
                    AIUsage.day == day, AIUsage.scope == self.scope)) or 0
                if calls >= s.max_llm_calls_per_chat_per_day or bucket.used_microusd + amount > ceiling:
                    return None
                identifier = uuid.uuid4().hex
                bucket.used_microusd += amount
                db.add(AIUsage(id=identifier, day=day, scope=self.scope, model=model[:120],
                    reserved_microusd=amount, charged_microusd=amount, status='reserved',
                    input_price=s.ai_input_price, output_price=s.ai_output_price))
                return identifier
        except SQLAlchemyError:
            return None  # Failure to persist permission forbids the external request.

    def settle(self, identifier: str, usage: dict | None, *, rejected: bool = False) -> None:
        try:
            with session_scope(self.factory) as db:
                item = db.get(AIUsage, identifier)
                if not item or item.status != 'reserved':
                    return
                bucket = db.get(AIBudgetDay, item.day, with_for_update=True)
                db.refresh(item, with_for_update=True)
                if item.status != 'reserved':
                    return
                if rejected:
                    actual, status = 0, 'rejected'
                elif (isinstance(usage, dict)
                      and type(usage.get('prompt_tokens')) is int
                      and type(usage.get('completion_tokens')) is int
                      and 0 <= usage['prompt_tokens'] <= 10_000_000
                      and 0 <= usage['completion_tokens'] <= 10_000_000):
                    actual = micros(usage['prompt_tokens'], item.input_price) + micros(usage['completion_tokens'], item.output_price)
                    item.input_tokens = usage['prompt_tokens']
                    item.output_tokens = usage['completion_tokens']
                    status = 'settled' if actual <= item.reserved_microusd else 'overrun'
                else:
                    actual, status = item.reserved_microusd, 'uncertain'
                bucket.used_microusd += actual - item.charged_microusd
                item.charged_microusd, item.status = actual, status
        except SQLAlchemyError:
            pass  # Keep the full durable reservation on failure; never refund speculatively.
