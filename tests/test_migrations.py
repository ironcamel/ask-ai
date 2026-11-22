from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine, select

from ask_ai.models import User

ROOT = Path(__file__).parent.parent
INITIAL_SCHEMA = "0bb83c773dd2"
BOT_USERS = "ce7e5d5988d6"


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def alembic_config(db_url: str) -> Config:
    config = Config(ROOT / "alembic.ini", toml_file=ROOT / "pyproject.toml")
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.fixture
def engine(db_url: str) -> Engine:
    return create_engine(db_url)


def usernames(engine: Engine) -> list[str]:
    with Session(engine) as session:
        return list(session.exec(select(User.username).order_by(User.username)))


def test_migrations_match_models(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        diff = compare_metadata(
            MigrationContext.configure(connection), SQLModel.metadata
        )
    assert diff == []


def test_downgrade_removes_everything(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    with engine.connect() as connection:
        assert engine.dialect.get_table_names(connection) == ["alembic_version"]


def test_adds_assistant_bots(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")

    assert usernames(engine) == ["claude", "gemini"]
    with Session(engine) as session:
        assert all(u.hashed_password is None for u in session.exec(select(User)))


def test_skips_bots_that_already_exist(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, INITIAL_SCHEMA)
    # The User model has columns this revision doesn't, so insert with plain SQL.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user (username, email, created_at)"
                " VALUES ('gemini', 'gemini@bots.example.com', '2026-01-01')"
            )
        )

    command.upgrade(alembic_config, "head")

    assert usernames(engine) == ["claude", "gemini"]


def test_downgrade_removes_only_the_bots(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")
    with Session(engine) as session:
        session.add(User(username="alice", email="alice@example.com"))
        session.commit()

    command.downgrade(alembic_config, INITIAL_SCHEMA)

    assert usernames(engine) == ["alice"]


def test_backfills_modified_at(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, BOT_USERS)

    command.upgrade(alembic_config, "head")

    with Session(engine) as session:
        bots = session.exec(select(User)).all()
    assert bots
    assert all(bot.modified_at == bot.created_at for bot in bots)
