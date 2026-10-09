import json
from datetime import timedelta
from sqlalchemy import select
from replyforge.database import session_scope
from replyforge.models import InsightImport, InsightCandidate, InsightTask, Knowledge, utcnow
from replyforge.insight_worker import tick
from replyforge.privacy import prune_history


def seed(factory):
    with session_scope(factory) as db:
        job = InsightImport(fingerprint='synthetic', statistics={})
        db.add(job); db.flush()
        candidate = InsightCandidate(import_id=job.id, digest='synthetic', category='connection',
             question='Connection failed', answer='Update subscription then test WiFi', status='pending')
        db.add(candidate); db.flush()
        task = InsightTask(import_id=job.id, candidate_id=candidate.id)
        db.add(task); db.flush()
        return task.id


class Model:
    def __init__(self, *args, **kwargs):
        pass
    def _complete(self, *args):
        return json.dumps({'question':'Connection issue', 'answer':'Update the subscription',
                          'steps':['Update subscription', 'Try another network'], 'outcome':'unverified'})


def test_refinement_is_durable_and_never_auto_publishes(database, test_settings):
    identifier = seed(database)
    assert tick(database, test_settings, engine_class=Model)
    with session_scope(database) as db:
        task = db.get(InsightTask, identifier)
        assert task.status == 'review'
        assert len(task.result['steps']) == 2
        assert not db.scalars(select(Knowledge)).all()
    assert not tick(database, test_settings, engine_class=Model)


def test_crashed_request_requires_explicit_retry(database, test_settings):
    identifier = seed(database)
    with session_scope(database) as db:
        task = db.get(InsightTask, identifier)
        task.status, task.claimed_at = 'processing', utcnow()-timedelta(minutes=10)
        task.image_data = b'synthetic'
    assert tick(database, test_settings, engine_class=Model)
    with session_scope(database) as db:
        assert db.get(InsightTask, identifier).status == 'uncertain'
        assert db.get(InsightTask, identifier).image_data is None


def test_retention_also_erases_refined_text(database, test_settings):
    identifier = seed(database)
    tick(database, test_settings, engine_class=Model)
    with session_scope(database) as db:
        db.scalar(select(InsightCandidate)).created_at = utcnow()-timedelta(days=200)
        db.get(InsightTask, identifier).image_data = b'synthetic'
    with session_scope(database) as db:
        prune_history(db, 180)
    with session_scope(database) as db:
        task = db.get(InsightTask, identifier)
        assert task.status == 'expired' and task.result == {} and task.image_data is None


def test_reviewed_image_is_used_once_and_pixels_erased(database, test_settings):
    identifier = seed(database)
    with session_scope(database) as db:
        db.get(InsightTask, identifier).image_data = b'synthetic reviewed pixels'

    class Vision(Model):
        def __init__(self, settings, **kwargs):
            assert settings.vision_enabled
        def describe_screenshot(self, content):
            assert content == b'synthetic reviewed pixels'
            return 'The app shows a connection error'
        def _complete(self, system, prompt):
            assert 'UNTRUSTED IMAGE OBSERVATIONS' in prompt
            return super()._complete(system, prompt)
    tick(database, test_settings, engine_class=Vision)
    with session_scope(database) as db:
        task = db.get(InsightTask, identifier)
        assert task.status == 'review' and task.image_data is None
        assert not db.scalars(select(Knowledge)).all()


def test_failed_image_does_not_report_successful_analysis(database, test_settings):
    identifier = seed(database)
    with session_scope(database) as db:
        db.get(InsightTask, identifier).image_data = b'synthetic'
    class Vision(Model):
        def describe_screenshot(self, content):
            return None
        def _complete(self, *args):
            raise AssertionError('Failed image must not silently become text-only success')
    tick(database, test_settings, engine_class=Vision)
    with session_scope(database) as db:
        task = db.get(InsightTask, identifier)
        assert task.status == 'failed' and task.image_data is None
