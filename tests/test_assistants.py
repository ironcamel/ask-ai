from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from ask_ai.assistants import LLM_THREADS, find_mention
from ask_ai.config import settings
from ask_ai.models import MAX_BODY_LENGTH, AssistantQuery
from tests.conftest import FakeAssistant
from tests.helpers import create_comment, create_post, sign_up

NAMES = ["claude", "gemini"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("@claude what is 2+2?", "claude"),
        ("@claude, what is 2+2?", "claude"),
        ("What is 2+2, @gemini?", "gemini"),
        ("hey @claude\nwhat is 2+2", "claude"),
        ("(@claude) what is 2+2", "claude"),
        # Only the first mention counts.
        ("@gemini and @claude, compare notes", "gemini"),
        ("@claude what? @claude!", "claude"),
        # Nothing but mentions and punctuation: no question to send.
        ("@claude", None),
        ("  @claude,  ", None),
        ("@claude @gemini?", None),
        # Not mentions.
        ("@claudette hi", None),
        ("mail bob@claude.example", None),
        ("@Claude hi", None),
        ("claude hi", None),
        ("no mention", None),
    ],
)
def test_find_mention(body: str, expected: str | None):
    assert find_mention(body, NAMES) == expected


@pytest.mark.parametrize("name", NAMES)
def test_mention_posts_answer_as_comment(
    client: TestClient, assistants: dict[str, FakeAssistant], name: str
):
    user = sign_up(client)
    post = create_post(client, user, body=f"@{name} why is the sky blue?")

    assert assistants[name].queries == [f"@{name} why is the sky blue?"]
    other = next(a for n, a in assistants.items() if n != name)
    assert other.queries == []

    [comment] = client.get(f"/posts/{post['id']}/comments").json()
    assert comment["body"] == f"{name} says: @{name} why is the sky blue?"

    bot = client.get(f"/users/{comment['user_id']}").json()
    assert bot["username"] == name


def test_bot_user_is_reused(client: TestClient):
    user = sign_up(client)
    first = create_post(client, user, body="@claude one")
    second = create_post(client, user, body="@claude two")

    [c1] = client.get(f"/posts/{first['id']}/comments").json()
    [c2] = client.get(f"/posts/{second['id']}/comments").json()
    assert c1["user_id"] == c2["user_id"]
    assert [u["username"] for u in client.get("/users").json()] == ["alice", "claude"]


def test_post_without_mention_gets_no_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    user = sign_up(client)
    post = create_post(client, user, body="Email me at bob@claude.example")

    assert client.get(f"/posts/{post['id']}/comments").json() == []
    assert all(a.queries == [] for a in assistants.values())


def test_updating_post_does_not_trigger_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    user = sign_up(client)
    post = create_post(client, user)
    response = client.patch(
        f"/posts/{post['id']}", json={"body": "@claude hello"}, headers=user.headers
    )
    assert response.status_code == 200

    assert assistants["claude"].queries == []


def test_llm_failure_still_creates_post(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    assistants["gemini"].error = RuntimeError("API is down")
    user = sign_up(client)
    post = create_post(client, user, body="@gemini hello")

    assert client.get(f"/posts/{post['id']}").status_code == 200
    assert client.get(f"/posts/{post['id']}/comments").json() == []


@pytest.mark.parametrize("name", NAMES)
def test_mention_in_comment_answers_on_same_post(
    client: TestClient, assistants: dict[str, FakeAssistant], name: str
):
    alice = sign_up(client)
    post = create_post(client, alice, "Water boils at 100C at sea level.")
    other = create_post(client, alice, "Another post")
    question = create_comment(client, alice, post["id"], f"And on Everest, @{name}?")

    assert assistants[name].queries == [f"And on Everest, @{name}?"]
    comments = client.get(f"/posts/{post['id']}/comments").json()
    assert [c["body"] for c in comments] == [
        question["body"],
        f"{name} says: And on Everest, @{name}?",
    ]
    assert client.get(f"/users/{comments[1]['user_id']}").json()["username"] == name
    assert client.get(f"/posts/{other['id']}/comments").json() == []


def test_comment_without_mention_gets_no_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    alice = sign_up(client)
    post = create_post(client, alice)
    create_comment(client, alice, post["id"], "@claudette thanks")

    assert len(client.get(f"/posts/{post['id']}/comments").json()) == 1
    assert all(a.queries == [] for a in assistants.values())


def test_updating_comment_does_not_trigger_reply(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])
    response = client.patch(
        f"/comments/{comment['id']}",
        json={"body": "@claude hello"},
        headers=alice.headers,
    )
    assert response.status_code == 200

    assert assistants["claude"].queries == []


def test_llm_failure_still_creates_comment(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    assistants["claude"].error = RuntimeError("API is down")
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"], "@claude hello")

    assert client.get(f"/posts/{post['id']}/comments").json() == [comment]


def test_only_first_mentioned_assistant_answers(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    question = "@gemini or @claude, which is bigger: 9 or 11?"
    alice = sign_up(client)
    post = create_post(client, alice, question)

    assert assistants["gemini"].queries == [question]
    assert assistants["claude"].queries == []
    [comment] = client.get(f"/posts/{post['id']}/comments").json()
    assert comment["body"] == f"gemini says: {question}"


def test_mention_without_question_is_not_sent(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    alice = sign_up(client)
    post = create_post(client, alice, "@claude")
    create_comment(client, alice, post["id"], "@gemini!")

    assert all(a.queries == [] for a in assistants.values())
    assert client.get(f"/posts/{post['id']}/comments").json()[0]["body"] == "@gemini!"


@pytest.mark.parametrize("name", NAMES + [n.upper() for n in NAMES])
def test_assistant_usernames_are_reserved(client: TestClient, name: str):
    response = client.post(
        "/users",
        json={"username": name, "email": "x@example.com", "password": "password123"},
    )
    assert response.status_code == 422

    user = sign_up(client)
    response = client.patch(
        f"/users/{user.id}", json={"username": name}, headers=user.headers
    )
    assert response.status_code == 422


def test_answer_can_be_longer_than_users_can_write(client: TestClient):
    alice = sign_up(client)
    question = "@claude " + "x" * (MAX_BODY_LENGTH - len("@claude "))
    post = create_post(client, alice, question)

    [comment] = client.get(f"/posts/{post['id']}/comments").json()
    assert len(comment["body"]) > MAX_BODY_LENGTH


def test_user_quota(
    client: TestClient,
    assistants: dict[str, FakeAssistant],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "assistant_queries_per_user_per_hour", 2)
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")
    post = create_post(client, alice, "@claude one")
    create_comment(client, alice, post["id"], "@gemini two")

    response = client.post(
        "/posts", json={"body": "@claude three"}, headers=alice.headers
    )
    assert response.status_code == 429
    response = client.post(
        "/comments",
        json={"post_id": post["id"], "body": "@claude three"},
        headers=alice.headers,
    )
    assert response.status_code == 429
    # Rejected questions aren't sent, or posted.
    assert assistants["claude"].queries == ["@claude one"]
    assert len(client.get("/posts").json()) == 1
    assert len(client.get("/comments").json()) == 3  # Two questions, one answer.

    # Alice can still write without asking, and Bob has his own quota.
    create_post(client, alice, "no question")
    create_post(client, bob, "@claude four")


def test_overall_quota(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "assistant_queries_per_hour", 2)
    create_post(client, sign_up(client, "alice"), "@claude one")
    create_post(client, sign_up(client, "bob"), "@claude two")

    carol = sign_up(client, "carol")
    response = client.post(
        "/posts", json={"body": "@claude three"}, headers=carol.headers
    )
    assert response.status_code == 429
    assert response.json()["detail"] == (
        "The assistants have answered too many questions this hour"
    )


def test_quota_counts_only_the_last_hour(
    client: TestClient, test_engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "assistant_queries_per_user_per_hour", 1)
    alice = sign_up(client)
    with Session(test_engine) as session:
        old = datetime.now(UTC) - timedelta(hours=1, minutes=1)
        session.add(AssistantQuery(user_id=alice.id, created_at=old))
        session.commit()

    create_post(client, alice, "@claude hello")

    with Session(test_engine) as session:
        [query] = session.exec(select(AssistantQuery)).all()
    assert query.created_at > old  # The old one was cleared out.


def test_answers_run_in_their_own_threads(
    client: TestClient, assistants: dict[str, FakeAssistant]
):
    borrowed = []

    def ask(query: str) -> str:
        borrowed.append(LLM_THREADS.borrowed_tokens)
        return "An answer"

    assistants["claude"] = ask
    create_post(client, sign_up(client), "@claude hello")

    assert borrowed == [1]
    assert LLM_THREADS.borrowed_tokens == 0
