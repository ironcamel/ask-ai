"""Sending email, over SMTP."""

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Annotated

from fastapi import Depends

from ask_ai.config import settings

logger = logging.getLogger(__name__)

# Sends a message, given the recipient, subject and plain-text body.
Mailer = Callable[[str, str, str], None]


def send_email(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    if settings.smtp_host is None:
        logger.warning("SMTP_HOST is not set, so this email was not sent:\n%s", message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(
                settings.smtp_username, settings.smtp_password.get_secret_value()
            )
        smtp.send_message(message)


def get_mailer() -> Mailer:
    return send_email


MailerDep = Annotated[Mailer, Depends(get_mailer)]
