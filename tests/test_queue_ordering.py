from datetime import timedelta

from sqlalchemy import select

from replyforge.database import claim, session_scope
from replyforge.models import Event, Conversation, Message, Outbox, utcnow
from replyforge.worker import Processor
from test_worker import seed, incoming


def test_retry_and_active_lease_block_later_input(database):
    with session_scope(database) as db:
        db.add_all([Event(update_id=1, payload={}, available_at=utcnow()+timedelta(seconds=30)),
                    Event(update_id=2, payload={})])
    with session_scope(database) as db:
        assert claim(db, Event, 60) is None
        first = db.get(Event, 1)
        first.available_at = utcnow()-timedelta(seconds=1)
        assert claim(db, Event, 60).update_id == 1
    with session_scope(database) as db:
        assert claim(db, Event, 60) is None
        db.get(Event, 1).status = 'dead'
        assert claim(db, Event, 60).update_id == 2


def test_late_message_is_archived_without_advancing_flow(database, test_settings, fake_telegram):
    seed(database)
    worker = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        worker._process_payload(db, incoming(20, 'سلام'))
    with session_scope(database) as db:
        conv = db.scalar(select(Conversation))
        revision, state = conv.revision, conv.state
        worker._process_payload(db, incoming(10, 'اپراتور'))
        assert conv.revision == revision
        assert conv.state == state
        assert conv.owner == 'ai'
        assert len(db.scalars(select(Message)).all()) == 2
        assert len(db.scalars(select(Outbox)).all()) == 1


def test_graceful_shutdown_does_not_claim_more_work(database, test_settings, fake_telegram):
    worker = Processor(test_settings, database, fake_telegram)
    worker.stop_requested.set()
    def unexpected_tick():
        raise AssertionError('Worker claimed work after stop')
    worker.tick = unexpected_tick
    worker.run()


def test_late_batch_head_does_not_discard_newer_followup(database, test_settings, fake_telegram):
    seed(database)
    worker = Processor(test_settings, database, fake_telegram)
    with session_scope(database) as db:
        worker._process_payload(db, incoming(20, 'سلام'))
    with session_scope(database) as db:
        worker._process_payload(db, incoming(10, 'old input'),
            batch_messages=[incoming(30, 'اپراتور')['business_message']])
        conv = db.scalar(select(Conversation))
        assert conv.owner == 'human_pending'
        assert len(db.scalars(select(Message)).all()) == 3
