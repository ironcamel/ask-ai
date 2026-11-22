from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import URL, Engine, inspect
from sqlmodel import Session, SQLModel, create_engine, select

from ask_ai.models import Comment, Post, User
from tests.helpers import temporary_database

ROOT = Path(__file__).parent.parent
INITIAL_SCHEMA = "ddffc426bce0"


@pytest.fixture
def db_url() -> Iterator[URL]:
    with temporary_database("test_migrations") as url:
        yield url


@pytest.fixture
def alembic_config(db_url: URL) -> Config:
    config = Config(ROOT / "alembic.ini", toml_file=ROOT / "pyproject.toml")
    # Percent signs in a password would otherwise be read as interpolation.
    url = db_url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def engine(db_url: URL) -> Iterator[Engine]:
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


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

    assert inspect(engine).get_table_names() == ["alembic_version"]


def test_adds_assistant_bots(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")

    assert usernames(engine) == ["claude", "gemini"]
    with Session(engine) as session:
        assert all(u.hashed_password is None for u in session.exec(select(User)))


def test_downgrade_removes_only_the_bots(alembic_config: Config, engine: Engine):
    command.upgrade(alembic_config, "head")
    with Session(engine) as session:
        alice = User(username="alice", email="alice@example.com")
        session.add(alice)
        session.flush()
        post = Post(body="@claude hi", user_id=alice.id)
        session.add(post)
        session.flush()
        claude = session.exec(select(User).where(User.username == "claude")).one()
        session.add(Comment(body="Hello", post_id=post.id, user_id=claude.id))
        session.commit()

    command.downgrade(alembic_config, INITIAL_SCHEMA)

    assert usernames(engine) == ["alice"]
    with Session(engine) as session:
        assert len(session.exec(select(Post)).all()) == 1
        assert session.exec(select(Comment)).all() == []
