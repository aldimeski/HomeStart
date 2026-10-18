from alembic import context
from sqlalchemy import create_engine

from homestart.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # The application passes its own connection; the alembic CLI falls back to the ini settings.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    from homestart.config import load_settings, prepare_directories

    settings = load_settings()
    prepare_directories(settings)
    engine = create_engine(f"sqlite:///{settings.db_file}")
    with engine.begin() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
