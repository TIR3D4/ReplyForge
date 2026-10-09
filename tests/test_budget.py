from dataclasses import replace
import httpx
from sqlalchemy import select
from replyforge.budget import BudgetLedger
from replyforge.agent import AIEngine
from replyforge.database import session_scope
from replyforge.models import AIUsage, AIBudgetDay


def settings(base):
    return replace(base, ai_api_key='synthetic', ai_input_price='1', ai_output_price='2', ai_daily_budget_usd='0.01')


def test_reservation_survives_unknown_outcome_and_blocks_overspend(database, test_settings):
    ledger = BudgetLedger(database, settings(test_settings), 'synthetic')
    first = ledger.reserve('test', 8000, 500)
    assert first
    assert ledger.reserve('test', 2000, 1) is None
    ledger.settle(first, None)
    with session_scope(database) as db:
        assert db.get(AIUsage, first).status == 'uncertain'
        assert db.scalar(select(AIBudgetDay)).used_microusd == 9000


def test_validated_usage_refunds_only_difference_once(database, test_settings):
    ledger = BudgetLedger(database, settings(test_settings), 'synthetic')
    first = ledger.reserve('test', 8000, 500)
    ledger.settle(first, {'prompt_tokens': 100, 'completion_tokens': 20})
    ledger.settle(first, None, rejected=True)
    with session_scope(database) as db:
        assert db.scalar(select(AIBudgetDay)).used_microusd == 140
        assert db.get(AIUsage, first).input_tokens == 100
    assert ledger.reserve('test', 8000, 500)


def test_provider_timeout_keeps_charge_and_no_fallback(database, test_settings):
    configured = replace(settings(test_settings), ai_fallback_model='fallback')
    def timeout(_):
        raise httpx.ReadTimeout('synthetic')
    engine = AIEngine(configured, ledger=BudgetLedger(database, configured, 'synthetic'), transport=httpx.MockTransport(timeout))
    assert engine._complete('Classify', 'Hello') is None
    with session_scope(database) as db:
        rows = db.scalars(select(AIUsage)).all()
        assert len(rows) == 1 and rows[0].status == 'uncertain'


def test_unknown_pricing_blocks_external_request(database, test_settings):
    def forbidden(_):
        raise AssertionError('Unknown price must not call provider')
    configured = replace(test_settings, ai_api_key='synthetic')
    engine = AIEngine(configured, ledger=BudgetLedger(database, configured, 'synthetic'), transport=httpx.MockTransport(forbidden))
    assert engine._complete('Classify', 'Hello') is None
