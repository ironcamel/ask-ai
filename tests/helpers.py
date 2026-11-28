from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.pool import NullPool

from ask_ai.config import settings

PASSWORD = "correct horse battery staple"


@dataclass
class Email:
    to: str
    subject: str
    body: str


class FakeMailer:
    """Stands in for SMTP: records the emails instead of sending them."""

    def __init__(self):
        self.sent: list[Email] = []
        self.error: Exception | None = None

    def __call__(self, to: str, subject: str, body: str) -> None:
        if self.error:
            raise self.error
        self.sent.append(Email(to, subject, body))


@dataclass
class Account:
    """A signed-up user and the headers that authenticate as them."""

    user: dict
    headers: dict[str, str]

    @property
    def id(self) -> int:
        return self.user["id"]

    @property
    def public(self) -> dict:
        """The user as others see them, without the email address."""
        return {k: v for k, v in self.user.items() if k != "email"}


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def sign_up(client: TestClient, username: str = "alice") -> Account:
    response = client.post(
        "/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return Account(response.json(), login(client, username))


def create_post(client: TestClient, author: Account, body: str = "First post") -> dict:
    response = client.post("/posts", json={"body": body}, headers=author.headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_comment(
    client: TestClient, author: Account, post_id: int, body: str = "Nice"
) -> dict:
    response = client.post(
        "/comments", json={"body": body, "post_id": post_id}, headers=author.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@contextmanager
def temporary_database(suffix: str) -> Iterator[URL]:
    """Create an empty database next to DATABASE_URL's, and drop it afterwards.

    It's named after DATABASE_URL's database, e.g. "ask_ai_test" for "ask_ai".
    """
    url = make_url(settings.database_url)
    name = f"{url.database}_{suffix}"
    server = create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with server.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name)
    finally:
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
