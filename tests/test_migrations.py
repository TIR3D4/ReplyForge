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
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0004_token_bindings"
        for table in Base.metadata.tables:
            assert table in inspect(conn).get_table_names()
        delta = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert delta == []
    engine.dispose()
