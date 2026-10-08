"""Alembic environment for ReplyForge."""
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from replyforge.models import Base

config = context.config
target_metadata = Base.metadata
url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("DATABASE_URL must be set")


def run_migrations_offline():
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(section, prefix="sqlalchemy.",
                                     poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
