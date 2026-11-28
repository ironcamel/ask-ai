import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Response,
    status,
)
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
    create_refresh_token,
    reset_password,
    reset_recently_requested,
    revoke_refresh_token,
    rotate_refresh_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# The refresh token is kept in a cookie that page scripts can't read, which
# browsers send only to the /auth endpoints, over HTTPS, from this site's own
# pages. Browsers treat localhost as secure, so it works in development too.
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


@router.post("/token")
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    response: Response,
) -> Token:
    """Log in, and get an access token and a refresh token cookie."""
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _set_refresh_cookie(response, create_refresh_token(session, user))
    return create_access_token(user)


@router.post("/refresh")
def refresh(
    session: SessionDep, response: Response, refresh_token: RefreshCookie = None
) -> Token:
    """Get a new access token with the refresh token cookie.

    The cookie is replaced with a new refresh token, since each works once.
    """
    rotated = rotate_refresh_token(session, refresh_token) if refresh_token else None
    if rotated is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token"
        )
    user, new_refresh_token = rotated
    _set_refresh_cookie(response, new_refresh_token)
    return create_access_token(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    session: SessionDep, response: Response, refresh_token: RefreshCookie = None
) -> None:
    """Revoke the refresh token cookie, and delete it.

    Access tokens already issued still work until they expire.
    """
    if refresh_token:
        revoke_refresh_token(session, refresh_token)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


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
    doesn't reveal which addresses have one. It's also the same when no email
    is sent because one was sent within PASSWORD_RESET_EMAIL_INTERVAL_MINUTES.
    """
    user = session.exec(select(User).where(User.email == request.email)).first()
    # Accounts without a password, such as the assistant bots, can't log in.
    if user is None or user.hashed_password is None:
        return
    # The token sent a moment ago still works.
    if reset_recently_requested(session, user):
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
