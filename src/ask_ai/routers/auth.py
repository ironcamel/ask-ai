import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from ask_ai.config import settings
from ask_ai.database import SessionDep
from ask_ai.mail import Mailer, MailerDep
from ask_ai.models import PasswordReset, PasswordResetRequest, User
from ask_ai.security import (
    Token,
    authenticate_user,
    create_access_token,
    create_password_reset_token,
    reset_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token")
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return create_access_token(user)


def _reset_email_body(user: User, token: str) -> str:
    minutes = settings.password_reset_token_expire_minutes
    if settings.password_reset_url:
        link = f"{settings.password_reset_url}?{urlencode({'token': token})}"
        how = f"To choose a new password, go to:\n\n{link}"
    else:
        how = f"To choose a new password, use this reset token:\n\n{token}"
    return (
        f"Hi {user.username},\n\n"
        "Someone asked to reset the password for your ask-ai account. "
        f"{how}\n\n"
        f"It works once, within {minutes} minutes. If you didn't ask for this, "
        "ignore this email and your password stays the same.\n"
    )


def _send_reset_email(mailer: Mailer, to: str, body: str) -> None:
    # Runs after the response, so it logs failures rather than raising them.
    try:
        mailer(to, "Reset your ask-ai password", body)
    except Exception:
        logger.exception("Failed to send a password reset email")


@router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
def request_password_reset(
    request: PasswordResetRequest,
    session: SessionDep,
    mailer: MailerDep,
    background_tasks: BackgroundTasks,
) -> None:
    """Email a password reset token to the account with this address.

    The response is the same whether or not there is such an account, so it
    doesn't reveal which addresses have one.
    """
    user = session.exec(select(User).where(User.email == request.email)).first()
    # Accounts without a password, such as the assistant bots, can't log in.
    if user is None or user.hashed_password is None:
        return
    token = create_password_reset_token(session, user)
    body = _reset_email_body(user, token)
    background_tasks.add_task(_send_reset_email, mailer, user.email, body)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(reset: PasswordReset, session: SessionDep) -> None:
    """Set a new password with a reset token from the email."""
    if reset_password(session, reset.token, reset.password) is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token"
        )
