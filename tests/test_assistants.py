import pytest
from fastapi.testclient import TestClient

from ask_ai.assistants import parse_mention
from tests.conftest import FakeAssistant
from tests.test_api import create_post, create_user

NAMES = ["claude", "gemini"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("@claude what is 2+2?", ("claude", "what is 2+2?")),
        ("@gemini\n  tell me a joke  ", ("gemini", "tell me a joke")),
        ("@claude, what is 2+2?", ("claude", "what is 2+2?")),
        ("@gemini,tell me a joke", ("gemini", "tell me a joke")),
        ("@claude,", None),
        ("@claude,  ", None),
        ("@claude", None),
        ("@claude   ", None),
        ("@claudette hi", None),
        ("hey @claude hi", None),
        ("@Claude hi", None),
        ("no mention", None),
    ],
)
def test_parse_mention(body: str, expected: tuple[str, str] | None):
    assert parse_mention(body, NAMES) == expected


@pytest.mark.parametrize("name", NAMES)
def test_mention_posts_answer_as_comment(
    client: TestClient, assistants: dict[str, FakeAssistant], name: str
):
    user = create_user(client)
    post = create_post(client, user["id"], body=f"@{name} why is the sky blue?")

    assert assistants[name].queries == ["why is the sky blue?"]
    other = next(a for n, a in assistants.items() if n != name)
    assert other.queries == []

    [comment] = client.get(f"/posts/{post['id']}/comments").json()
    assert comment["body"] == f"{name} says: why is the sky blue?"

    bot = client.get(f"/users/{comment['user_id']}").json()
    assert bot["username"] == name


def test_bot_user_is_reused(client: TestClient):
    user = create_user(client)
    first = create_post(client, user["id"], body="@claude one")
    second = create_post(client, user["id"], body="@claude two")

    [c1] = client.get(f"/posts/{first['id']}/comments").json()
    [c2] = client.get(f"/posts/{second['id']}/comments").json()
    assert c1["user_id"] == c2["user_id"]
    assert [u["username"] for u in client.get("/users").json()] == ["alice", "claude"]


def test_post_without_mention_gets_no_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    user = create_user(client)
    post = create_post(client, user["id"], body="Just a regular post about @claude")

    assert client.get(f"/posts/{post['id']}/comments").json() == []
    assert all(a.queries == [] for a in assistants.values())


def test_updating_post_does_not_trigger_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    user = create_user(client)
    post = create_post(client, user["id"])
    client.patch(f"/posts/{post['id']}", json={"body": "@claude hello"})

    assert assistants["claude"].queries == []


def test_llm_failure_still_creates_post(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    assistants["gemini"].error = RuntimeError("API is down")
    user = create_user(client)
    post = create_post(client, user["id"], body="@gemini hello")

    assert client.get(f"/posts/{post['id']}").status_code == 200
    assert client.get(f"/posts/{post['id']}/comments").json() == []


@pytest.mark.parametrize("name", NAMES)
def test_assistant_usernames_are_reserved(client: TestClient, name: str):
    response = client.post(
        "/users", json={"username": name, "email": "someone@example.com"}
    )
    assert response.status_code == 422

    user = create_user(client)
    response = client.patch(f"/users/{user['id']}", json={"username": name})
    assert response.status_code == 422
