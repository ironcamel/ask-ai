from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlmodel import SQLModel, create_engine

from ask_ai.assistants import get_assistants
from ask_ai.config import settings
from ask_ai.database import get_engine
from ask_ai.mail import get_mailer
from ask_ai.main import app
from tests.helpers import FakeMailer, temporary_database


class FakeAssistant:
    """Stands in for an LLM: records queries and answers with a canned reply."""

    def __init__(self, name: str):
        self.name = name
        self.queries: list[str] = []
        self.error: Exception | None = None

    def __call__(self, query: str) -> str:
        self.queries.append(query)
        if self.error:
            raise self.error
        return f"{self.name} says: {query}"


@pytest.fixture(autouse=True)
def jwt_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr("test-secret-key-that-is-at-least-32-bytes"),
    )


@pytest.fixture
def assistants() -> dict[str, FakeAssistant]:
    return {"claude": FakeAssistant("claude"), "gemini": FakeAssistant("gemini")}


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    with temporary_database("test") as url:
        engine = create_engine(url)
        SQLModel.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def client(
    test_engine: Engine, assistants: dict[str, FakeAssistant], mailer: FakeMailer
) -> Iterator[TestClient]:
    # Each test starts with empty tables, and ids counting from 1 again.
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    with test_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY"))

    app.dependency_overrides[get_engine] = lambda: test_engine
    app.dependency_overrides[get_assistants] = lambda: assistants
    app.dependency_overrides[get_mailer] = lambda: mailer
    yield TestClient(app)
    app.dependency_overrides.clear()
