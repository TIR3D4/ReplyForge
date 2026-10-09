"""Keep the shipped Alembic migration in sync with ORM metadata."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from replyforge.models import Base


def test_alembic_initial_schema_is_repeatable_and_matches_models(tmp_path):
    db = tmp_path / "migration-test.sqlite"
    url = "sqlite+pysqlite:///" + str(db)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # safe to rerun after restart
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0012_reviewed_media"
        for table in Base.metadata.tables:
            assert table in inspect(conn).get_table_names()
        delta = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert delta == []
    engine.dispose()


def test_upgrade_from_first_12_candidate_preserves_existing_rows(tmp_path):
    url = 'sqlite+pysqlite:///' + str(tmp_path/'upgrade.sqlite')
    cfg = Config('alembic.ini')
    cfg.set_main_option('sqlalchemy.url', url)
    command.upgrade(cfg, '0011_release_runtime')
    engine = create_engine(url)
    with engine.begin() as conn:
        assert 'image_data' not in {c['name'] for c in inspect(conn).get_columns('insight_tasks')}
        conn.execute(text("INSERT INTO ai_budget_days (day,used_microusd) VALUES ('2026-01-01',1500)"))
    command.upgrade(cfg, 'head')
    with engine.connect() as conn:
        assert 'image_data' in {c['name'] for c in inspect(conn).get_columns('insight_tasks')}
        assert conn.scalar(text('SELECT used_microusd FROM ai_budget_days')) == 1500
    engine.dispose()
