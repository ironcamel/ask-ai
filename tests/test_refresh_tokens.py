import re
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select, update

from ask_ai.config import settings
from ask_ai.models import RefreshToken
from ask_ai.routers.auth import REFRESH_COOKIE
from tests.helpers import PASSWORD, FakeMailer, sign_up


def log_in(client: TestClient, username: str = "alice") -> httpx.Response:
    response = client.post(
        "/auth/token", data={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response


def refresh_token(response: httpx.Response) -> str:
    return response.cookies[REFRESH_COOKIE]


def refresh(client: TestClient, token: str | None) -> httpx.Response:
    # Sends just this token, rather than whichever the client last received.
    client.cookies.clear()
    headers = {"Cookie": f"{REFRESH_COOKIE}={token}"} if token else {}
    return client.post("/auth/refresh", headers=headers)


def can_refresh(client: TestClient, token: str) -> bool:
    return refresh(client, token).status_code == 200


def test_login_sets_refresh_cookie(client: TestClient):
    sign_up(client)
    response = log_in(client)

    attributes = {a.strip().lower() for a in response.headers["set-cookie"].split(";")}
    days = settings.refresh_token_expire_days
    assert {
        "httponly",
        "secure",
        "samesite=strict",
        "path=/auth",
        f"max-age={days * 24 * 60 * 60}",
    } <= attributes
    assert response.json()["expires_in"] == settings.access_token_expire_minutes * 60


def test_refresh_returns_new_access_token(client: TestClient):
    alice = sign_up(client)
    token = refresh_token(log_in(client))

    response = refresh(client, token)
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    access_token = response.json()["access_token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.json() == alice.user

    # The cookie holds a new refresh token, which works in turn.
    new_token = refresh_token(response)
    assert new_token != token
    assert can_refresh(client, new_token)


@pytest.mark.parametrize("token", [None, "not-a-real-token"])
def test_refresh_rejects_missing_or_invalid_token(
    client: TestClient, token: str | None
):
    sign_up(client)
    response = refresh(client, token)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired refresh token"


def test_expired_refresh_token_is_rejected(client: TestClient, test_engine: Engine):
    sign_up(client)
    token = refresh_token(log_in(client))
    # Expire it in the database, since an expired cookie isn't sent at all.
    with Session(test_engine) as session:
        session.exec(update(RefreshToken).values(expires_at=datetime.now(UTC)))
        session.commit()

    assert not can_refresh(client, token)


def test_reused_refresh_token_revokes_its_login(client: TestClient):
    sign_up(client)
    stolen = refresh_token(log_in(client))
    other_login = refresh_token(log_in(client))
    latest = refresh_token(refresh(client, stolen))

    # The token was used already, so someone else has a copy of it.
    assert not can_refresh(client, stolen)
    assert not can_refresh(client, latest)
    # Other logins are unaffected.
    assert can_refresh(client, other_login)


def test_logout_revokes_refresh_token(client: TestClient):
    sign_up(client)
    token = refresh_token(log_in(client))
    other_login = refresh_token(log_in(client))

    client.cookies.clear()
    response = client.post(
        "/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}={token}"}
    )
    assert response.status_code == 204
    assert re.match(f'{REFRESH_COOKIE}="";', response.headers["set-cookie"])

    assert not can_refresh(client, token)
    assert can_refresh(client, other_login)


def test_logout_without_refresh_token(client: TestClient):
    client.cookies.clear()
    assert client.post("/auth/logout").status_code == 204


def test_password_reset_revokes_refresh_tokens(client: TestClient, mailer: FakeMailer):
    sign_up(client)
    token = refresh_token(log_in(client))

    client.post("/auth/password-reset", json={"email": "alice@example.com"})
    reset_token = re.search(r"reset token:\n\n(\S+)", mailer.sent[-1].body).group(1)
    response = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "password": "a brand new password"},
    )
    assert response.status_code == 204

    assert not can_refresh(client, token)


def test_password_change_revokes_refresh_tokens(client: TestClient):
    alice = sign_up(client)
    token = refresh_token(log_in(client))
    url = f"/users/{alice.id}"

    # Other changes leave the user logged in.
    client.patch(url, json={"username": "alicia"}, headers=alice.headers)
    token = refresh_token(refresh(client, token))

    response = client.patch(
        url,
        json={"password": "a brand new password", "current_password": PASSWORD},
        headers=alice.headers,
    )
    assert response.status_code == 200
    assert not can_refresh(client, token)


def test_only_a_hash_of_the_refresh_token_is_stored(
    client: TestClient, test_engine: Engine
):
    sign_up(client)
    token = refresh_token(log_in(client))

    with Session(test_engine) as session:
        rows = session.exec(select(RefreshToken)).all()
    # One from signing up, one from logging in again.
    assert len(rows) == 2
    assert all(token not in row.token_hash for row in rows)
