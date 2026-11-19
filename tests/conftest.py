from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from ask_ai.assistants import get_assistants
from ask_ai.config import settings
from ask_ai.database import get_engine
from ask_ai.main import app


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
def client(assistants: dict[str, FakeAssistant]) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_assistants] = lambda: assistants
    yield TestClient(app)
    app.dependency_overrides.clear()
