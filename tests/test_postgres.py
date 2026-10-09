"""Validate the production PostgreSQL dialect and durable queue semantics."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from replyforge.database import claim, session_factory, session_scope
from replyforge.models import BusinessConnection, Event, Outbox, Conversation


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="No PostgreSQL configured")
def test_postgres_migrations_and_queue():
    url = os.environ["TEST_POSTGRES_URL"]
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine, factory = session_factory(url)
    with session_scope(factory) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0011_release_runtime"
        session.add(BusinessConnection(
            id="ci-business", owner_user_id=555, enabled=True, can_reply=True,
        ))
        session.flush()
        conv = Conversation(
            business_connection_id="ci-business", chat_id=42, owner="ai", state={},
        )
        session.add(conv)
        session.flush()
        session.add(Event(update_id=99999, payload={"update_id": 99999}))
        session.add(Outbox(conversation_id=conv.id, revision=1, kind="text", text="hi", buttons=[]))

    with session_scope(factory) as session:
        ev = claim(session, Event, lease_seconds=60)
        assert ev.update_id == 99999
        assert ev.status == "processing"
        job = claim(session, Outbox, lease_seconds=60)
        assert job.status == "sending"
    with session_scope(factory) as session:
        assert session.scalar(select(Event).where(Event.update_id == 99999)).status == "processing"
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='No PostgreSQL configured')
def test_postgres_delivery_serializes_with_human_takeover(test_settings, fake_telegram):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from dataclasses import replace
    import threading
    import uuid
    from replyforge.models import utcnow
    from replyforge.worker import Processor
    url = os.environ['TEST_POSTGRES_URL']
    engine, factory = session_factory(url)
    entered, release, attempted, acquired = [threading.Event() for _ in range(4)]
    identifier = 'race-' + uuid.uuid4().hex
    with session_scope(factory) as db:
        db.add(BusinessConnection(id=identifier, enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id=identifier, chat_id=123, owner='ai', last_inbound_at=utcnow(), revision=1)
        db.add(conv)
        db.flush()
        cid = conv.id
        job = Outbox(conversation_id=cid, revision=1, kind='text', text='Synthetic reply', status='sending')
        db.add(job)
        db.flush()
        jid = job.id
    original = fake_telegram.send
    def blocked_send(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    fake_telegram.send = blocked_send
    worker = Processor(replace(test_settings, database_url=url), factory, fake_telegram)
    def takeover():
        attempted.set()
        with session_scope(factory) as db:
            conv = db.get(Conversation, cid, with_for_update=True)
            acquired.set()
            conv.owner = 'human'
            conv.revision += 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        delivery = pool.submit(worker.delivery, jid)
        assert entered.wait(5)
        human = pool.submit(takeover)
        assert attempted.wait(5)
        try:
            assert not acquired.wait(.2), 'Takeover must wait for an already-started send'
        finally:
            release.set()
        delivery.result(timeout=5)
        human.result(timeout=5)
    with session_scope(factory) as db:
        assert db.get(Conversation, cid).owner == 'human'
        assert db.get(Outbox, jid).status == 'sent'
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='No PostgreSQL configured')
def test_postgres_rejects_second_worker():
    from replyforge.database import exclusive_worker
    engine, _ = session_factory(os.environ['TEST_POSTGRES_URL'])
    with exclusive_worker(engine):
        with pytest.raises(RuntimeError, match='already active'):
            with exclusive_worker(engine):
                pass
    with exclusive_worker(engine):
        pass  # A clean exit releases the advisory lock.
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='No PostgreSQL configured')
def test_postgres_retention_scrubs_json_workflow_state():
    from datetime import timedelta
    import uuid
    from replyforge.models import utcnow
    from replyforge.privacy import prune_history
    engine, factory = session_factory(os.environ['TEST_POSTGRES_URL'])
    key = 'privacy-' + uuid.uuid4().hex
    with session_scope(factory) as db:
        db.add(BusinessConnection(id=key, enabled=True, can_reply=True))
        db.flush()
        conv = Conversation(business_connection_id=key, chat_id=42,
            last_inbound_at=utcnow()-timedelta(days=200), state={'answers': {'private': 'example'}})
        db.add(conv)
        db.flush()
        cid = conv.id
    with session_scope(factory) as db:
        assert prune_history(db, 180)['conversation_state'] >= 1
    with session_scope(factory) as db:
        assert db.get(Conversation, cid).state == {}
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='No PostgreSQL configured')
def test_postgres_budget_survives_support_rollback_and_serializes_reservations(test_settings):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from decimal import Decimal
    import uuid
    from replyforge.budget import BudgetLedger
    from replyforge.models import AIUsage, AIBudgetDay, Audit, utcnow
    engine, factory = session_factory(os.environ['TEST_POSTGRES_URL'])
    scope = 'test-' + uuid.uuid4().hex
    cfg = replace(test_settings, ai_input_price='1', ai_output_price='1', ai_daily_budget_usd='10000',
                  max_llm_calls_per_chat_per_day=100)
    ledger = BudgetLedger(factory, cfg, scope)
    with pytest.raises(RuntimeError):
        with session_scope(factory) as db:
            db.add(Audit(actor='test', action=scope)); db.flush()
            reserved = ledger.reserve('synthetic', 1000, 0)
            assert reserved
            raise RuntimeError('Simulated support transition rollback')
    with session_scope(factory) as db:
        assert db.get(AIUsage, reserved).status == 'reserved'
        assert db.scalar(select(Audit.id).where(Audit.action == scope)) is None
        total = db.get(AIBudgetDay, utcnow().date().isoformat()).used_microusd
    cfg = replace(cfg, ai_daily_budget_usd=str(Decimal(total + 6000)/Decimal(1_000_000)))
    ledger = BudgetLedger(factory, cfg, scope)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ledger.reserve('synthetic', 1000, 0), range(16)))
    assert sum(bool(r) for r in results) == 6
    engine.dispose()
