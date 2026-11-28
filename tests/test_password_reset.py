import logging
import re
import ssl
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from ask_ai.config import settings
from ask_ai.mail import send_email
from ask_ai.models import PasswordResetToken
from tests.helpers import PASSWORD, FakeMailer, create_post, sign_up

NEW_PASSWORD = "a brand new password"


def request_reset(client: TestClient, email: str = "alice@example.com") -> None:
    response = client.post("/auth/password-reset", json={"email": email})
    assert response.status_code == 204, response.text


def emailed_token(mailer: FakeMailer) -> str:
    match = re.search(r"reset token:\n\n(\S+)", mailer.sent[-1].body)
    assert match, mailer.sent[-1].body
    return match.group(1)


def confirm(client: TestClient, token: str, password: str = NEW_PASSWORD):
    return client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": password}
    )


def can_log_in(client: TestClient, password: str) -> bool:
    response = client.post(
        "/auth/token", data={"username": "alice", "password": password}
    )
    return response.status_code == 200


def test_reset_password(client: TestClient, mailer: FakeMailer):
    sign_up(client)
    request_reset(client)

    [email] = mailer.sent
    assert email.to == "alice@example.com"
    assert email.subject == "Reset your ask-ai password"

    assert confirm(client, emailed_token(mailer)).status_code == 204
    assert can_log_in(client, NEW_PASSWORD)
    assert not can_log_in(client, PASSWORD)


@pytest.mark.parametrize("email", ["nobody@example.com", "claude@bots.example.com"])
def test_no_email_without_an_account_to_reset(
    client: TestClient, mailer: FakeMailer, email: str
):
    alice = sign_up(client)
    create_post(client, alice, "@claude hello")  # Creates the claude bot user.

    request_reset(client, email)  # Responds the same as for a real account.
    assert mailer.sent == []


def test_token_works_once(client: TestClient, mailer: FakeMailer):
    sign_up(client)
    request_reset(client)
    token = emailed_token(mailer)

    assert confirm(client, token).status_code == 204
    response = confirm(client, token, "yet another password")
    assert response.status_code == 400
    assert can_log_in(client, NEW_PASSWORD)


def test_new_request_replaces_earlier_token(
    client: TestClient, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "password_reset_email_interval_minutes", 0)
    sign_up(client)
    request_reset(client)
    first = emailed_token(mailer)
    request_reset(client)
    second = emailed_token(mailer)

    assert confirm(client, first).status_code == 400
    assert confirm(client, second).status_code == 204


def test_reset_emails_are_spaced_out(
    client: TestClient, mailer: FakeMailer, test_engine: Engine
):
    sign_up(client)
    request_reset(client)
    token = emailed_token(mailer)
    request_reset(client)  # Too soon: responds the same, but sends nothing.

    assert len(mailer.sent) == 1
    with Session(test_engine) as session:
        row = session.exec(select(PasswordResetToken)).one()
        row.created_at -= timedelta(
            minutes=settings.password_reset_email_interval_minutes
        )
        session.add(row)
        session.commit()

    request_reset(client)
    assert len(mailer.sent) == 2
    assert confirm(client, token).status_code == 400  # Replaced by the new one.


def test_expired_token_is_rejected(
    client: TestClient, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "password_reset_token_expire_minutes", -1)
    sign_up(client)
    request_reset(client)

    assert confirm(client, emailed_token(mailer)).status_code == 400
    assert can_log_in(client, PASSWORD)


def test_invalid_token_is_rejected(client: TestClient):
    sign_up(client)
    response = confirm(client, "not-a-real-token")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"


def test_new_password_minimum_length(client: TestClient, mailer: FakeMailer):
    sign_up(client)
    request_reset(client)

    assert confirm(client, emailed_token(mailer), "short").status_code == 422
    assert can_log_in(client, PASSWORD)


def test_only_a_hash_of_the_token_is_stored(
    client: TestClient, mailer: FakeMailer, test_engine: Engine
):
    sign_up(client)
    request_reset(client)
    token = emailed_token(mailer)

    with Session(test_engine) as session:
        [row] = session.exec(select(PasswordResetToken)).all()
    assert token not in row.token_hash


def test_email_links_to_reset_page(
    client: TestClient, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        settings, "password_reset_url", "https://example.com/reset-password"
    )
    sign_up(client)
    request_reset(client)

    match = re.search(
        r"https://example\.com/reset-password\?token=(\S+)", mailer.sent[0].body
    )
    assert match, mailer.sent[0].body
    assert confirm(client, match.group(1)).status_code == 204


def test_mail_failure_is_logged(
    client: TestClient, mailer: FakeMailer, caplog: pytest.LogCaptureFixture
):
    mailer.error = ConnectionRefusedError("SMTP server is down")
    sign_up(client)

    with caplog.at_level(logging.ERROR):
        request_reset(client)

    assert "Failed to send a password reset email" in caplog.text


def test_email_is_logged_without_smtp(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(settings, "smtp_host", None)

    with caplog.at_level(logging.WARNING):
        send_email("alice@example.com", "Hello", "The body")

    assert "SMTP_HOST is not set" in caplog.text
    assert "To: alice@example.com" in caplog.text
    assert "The body" in caplog.text


def test_smtp_verifies_the_server_certificate(monkeypatch: pytest.MonkeyPatch):
    contexts: list[ssl.SSLContext] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            pass

        def starttls(self, *, context: ssl.SSLContext | None = None):
            contexts.append(context)

        def send_message(self, message):
            pass

    monkeypatch.setattr("ask_ai.mail.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "smtp_username", None)  # Whatever .env says.

    send_email("alice@example.com", "Hello", "The body")

    [context] = contexts
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
