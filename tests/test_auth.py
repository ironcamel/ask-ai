from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from ask_ai.config import settings
from tests.helpers import PASSWORD, create_comment, create_post, login, sign_up


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_token(claims: dict, key: str | None = None) -> str:
    key = key or settings.jwt_secret_key.get_secret_value()
    return jwt.encode(claims, key, algorithm="HS256")


def test_login_returns_token_for_current_user(client: TestClient):
    alice = sign_up(client)

    response = client.post(
        "/auth/token", data={"username": "alice", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    me = client.get("/users/me", headers=bearer(response.json()["access_token"]))
    assert me.json() == alice.user


def test_login_ignores_username_case(client: TestClient):
    alice = sign_up(client)
    headers = login(client, "ALICE")
    assert client.get("/users/me", headers=headers).json() == alice.user


@pytest.mark.parametrize(
    ("username", "password"), [("alice", "wrong password"), ("nobody", PASSWORD)]
)
def test_login_rejects_bad_credentials(
    client: TestClient, username: str, password: str
):
    sign_up(client)
    response = client.post(
        "/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_password_is_never_returned(client: TestClient):
    alice = sign_up(client)
    for user in (alice.user, client.get(f"/users/{alice.id}").json()):
        assert "password" not in user
        assert "hashed_password" not in user


def test_password_minimum_length(client: TestClient):
    response = client.post(
        "/users",
        json={"username": "alice", "email": "a@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_bot_accounts_cannot_log_in(client: TestClient):
    alice = sign_up(client)
    create_post(client, alice, "@claude hello")  # Creates the claude bot user.

    response = client.post(
        "/auth/token", data={"username": "claude", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_write_endpoints_require_login(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])

    requests = [
        ("GET", "/users/me", None),
        ("PATCH", f"/users/{alice.id}", {"username": "x"}),
        ("DELETE", f"/users/{alice.id}", None),
        ("POST", "/posts", {"body": "hi"}),
        ("PATCH", f"/posts/{post['id']}", {"body": "hi"}),
        ("DELETE", f"/posts/{post['id']}", None),
        ("POST", "/comments", {"body": "hi", "post_id": post["id"]}),
        ("PATCH", f"/comments/{comment['id']}", {"body": "hi"}),
        ("DELETE", f"/comments/{comment['id']}", None),
    ]
    for method, url, body in requests:
        response = client.request(method, url, json=body)
        assert response.status_code == 401, (method, url)


def test_read_endpoints_are_public(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])

    for url in [
        "/users",
        f"/users/{alice.id}",
        f"/users/{alice.id}/posts",
        f"/users/{alice.id}/comments",
        "/posts",
        f"/posts/{post['id']}",
        f"/posts/{post['id']}/comments",
        "/comments",
        f"/comments/{comment['id']}",
    ]:
        assert client.get(url).status_code == 200, url


def test_only_owner_can_modify(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])

    requests = [
        ("PATCH", f"/users/{alice.id}", {"username": "x"}),
        ("DELETE", f"/users/{alice.id}", None),
        ("PATCH", f"/posts/{post['id']}", {"body": "x"}),
        ("DELETE", f"/posts/{post['id']}", None),
        ("PATCH", f"/comments/{comment['id']}", {"body": "x"}),
        ("DELETE", f"/comments/{comment['id']}", None),
    ]
    for method, url, body in requests:
        response = client.request(method, url, json=body, headers=bob.headers)
        assert response.status_code == 403, (method, url)

    # Nothing was changed.
    assert client.get(f"/users/{alice.id}").json() == alice.public
    assert client.get(f"/posts/{post['id']}").json() == post
    assert client.get(f"/comments/{comment['id']}").json() == comment


def test_rejects_invalid_tokens(client: TestClient):
    alice = sign_up(client)
    expired = datetime.now(UTC) - timedelta(minutes=1)
    later = datetime.now(UTC) + timedelta(minutes=5)

    for token in [
        "not-a-jwt",
        make_token({"sub": str(alice.id), "exp": expired}),
        make_token({"sub": str(alice.id), "exp": later}, key="x" * 32 + "wrong"),
        make_token({"sub": str(alice.id)}),  # No expiry.
        make_token({"exp": later}),  # No subject.
        make_token({"sub": "alice", "exp": later}),  # Subject isn't a user id.
    ]:
        assert client.get("/users/me", headers=bearer(token)).status_code == 401


def test_token_for_deleted_user_is_rejected(client: TestClient):
    alice = sign_up(client)
    client.delete(f"/users/{alice.id}", headers=alice.headers)

    assert client.get("/users/me", headers=alice.headers).status_code == 401


def test_token_expiry_uses_setting(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "access_token_expire_minutes", 5)
    sign_up(client)
    token = login(client, "alice")["Authorization"].removeprefix("Bearer ")

    claims = jwt.decode(token, options={"verify_signature": False})
    lifetime = claims["exp"] - datetime.now(UTC).timestamp()
    assert 4 * 60 < lifetime <= 5 * 60
