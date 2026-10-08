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
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0008_delivery_attempts"
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
