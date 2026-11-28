"""Password hashing, JWT access tokens, refresh tokens and password reset tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel
from sqlmodel import Session, col, delete, select

from ask_ai.config import settings
from ask_ai.database import SessionDep
from ask_ai.models import PasswordResetToken, RefreshToken, User

ALGORITHM = "HS256"

password_hash = PasswordHash.recommended()
# Verified against when the username doesn't exist, so a login takes about as
# long either way and response times don't reveal which usernames exist.
DUMMY_HASH = password_hash.hash("dummypassword")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class Token(BaseModel):
    access_token: str
    # Seconds until the access token expires.
    expires_in: int
    token_type: str = "bearer"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def _secret_key() -> str:
    if settings.jwt_secret_key is None:
        raise RuntimeError("JWT_SECRET_KEY is not set")
    return settings.jwt_secret_key.get_secret_value()


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.hashed_password is None:
        password_hash.verify(password, DUMMY_HASH)
        return None
    if not password_hash.verify(password, user.hashed_password):
        return None
    return user


def create_access_token(user: User) -> Token:
    minutes = settings.access_token_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"sub": str(user.id), "exp": expire}
    return Token(
        access_token=jwt.encode(payload, _secret_key(), algorithm=ALGORITHM),
        expires_in=minutes * 60,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    credentials_exception = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            _secret_key(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
    except InvalidTokenError, ValueError:
        raise credentials_exception
    # The user may have been deleted since the token was issued.
    user = session.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Refresh tokens are random strings rather than JWTs, so that they can be
# revoked: each is a database row. Each works once, and is replaced by a new
# one when it's used.


def _find_refresh_token(session: Session, token: str) -> RefreshToken | None:
    # Locked, so that two requests at once can't both use the token.
    return session.exec(
        select(RefreshToken)
        .where(RefreshToken.token_hash == _hash_token(token))
        .with_for_update()
    ).first()


def _add_refresh_token(session: Session, user_id: int, family_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    session.add(
        RefreshToken(
            token_hash=_hash_token(token),
            family_id=family_id,
            user_id=user_id,
            expires_at=expires,
        )
    )
    return token


def _revoke_family(session: Session, family_id: str) -> None:
    session.exec(delete(RefreshToken).where(col(RefreshToken.family_id) == family_id))


def create_refresh_token(session: Session, user: User) -> str:
    """Return a refresh token for a new login, the first of a new family."""
    # Clear out everyone's expired tokens.
    session.exec(
        delete(RefreshToken).where(col(RefreshToken.expires_at) <= datetime.now(UTC))
    )
    token = _add_refresh_token(session, user.id, secrets.token_hex(16))
    session.commit()
    return token


def rotate_refresh_token(session: Session, token: str) -> tuple[User, str] | None:
    """Use up a refresh token, and return its user and the token replacing it.

    Return None if the token is invalid. A token that was already used means
    someone else has a copy of it, so its whole family is revoked: whoever
    holds the latest token, the user or the thief, has to log in again.
    """
    now = datetime.now(UTC)
    refresh_token = _find_refresh_token(session, token)
    if refresh_token is None or refresh_token.expires_at <= now:
        return None
    if refresh_token.used_at is not None:
        _revoke_family(session, refresh_token.family_id)
        session.commit()
        return None
    user = session.get(User, refresh_token.user_id)
    if user is None:
        return None
    refresh_token.used_at = now
    session.add(refresh_token)
    new_token = _add_refresh_token(session, user.id, refresh_token.family_id)
    session.commit()
    return user, new_token


def revoke_refresh_token(session: Session, token: str) -> None:
    """Log out: revoke the token's family, if there is such a token."""
    refresh_token = _find_refresh_token(session, token)
    if refresh_token is not None:
        _revoke_family(session, refresh_token.family_id)
        session.commit()


def revoke_user_refresh_tokens(session: Session, user: User) -> None:
    """Log the user out everywhere. The caller commits."""
    session.exec(delete(RefreshToken).where(col(RefreshToken.user_id) == user.id))


# Password reset tokens are random strings rather than JWTs too, so that they
# can be used only once: each is a database row, deleted when it's used.


def create_password_reset_token(session: Session, user: User) -> str:
    """Return a new reset token for the user, replacing any earlier ones."""
    now = datetime.now(UTC)
    # Clear out the user's earlier tokens, and everyone's expired ones.
    session.exec(
        delete(PasswordResetToken).where(
            (col(PasswordResetToken.user_id) == user.id)
            | (col(PasswordResetToken.expires_at) <= now)
        )
    )
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(minutes=settings.password_reset_token_expire_minutes)
    session.add(
        PasswordResetToken(
            token_hash=_hash_token(token), user_id=user.id, expires_at=expires
        )
    )
    session.commit()
    return token


def reset_password(session: Session, token: str, password: str) -> User | None:
    """Set a new password with a reset token, or return None if it's invalid."""
    # Locked, so that two requests at once can't both use the token.
    reset_token = session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _hash_token(token))
        .with_for_update()
    ).first()
    if reset_token is None or reset_token.expires_at <= datetime.now(UTC):
        return None
    user = session.get(User, reset_token.user_id)
    if user is None:
        return None
    user.hashed_password = hash_password(password)
    session.add(user)
    # The token is used up, and so is any other the user was sent.
    session.exec(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user.id)
    )
    # Whoever knew the old password may be logged in, so log everyone out.
    revoke_user_refresh_tokens(session, user)
    session.commit()
    return user
