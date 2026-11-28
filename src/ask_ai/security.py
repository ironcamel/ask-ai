"""Password hashing, JWT access tokens and password reset tokens."""

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
from ask_ai.models import PasswordResetToken, User

ALGORITHM = "HS256"

password_hash = PasswordHash.recommended()
# Verified against when the username doesn't exist, so a login takes about as
# long either way and response times don't reveal which usernames exist.
DUMMY_HASH = password_hash.hash("dummypassword")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class Token(BaseModel):
    access_token: str
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
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user.id), "exp": expire}
    return Token(access_token=jwt.encode(payload, _secret_key(), algorithm=ALGORITHM))


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


# Password reset tokens are random strings rather than JWTs, so that they can
# be used only once: each is a database row, deleted when it's used.


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
            token_hash=_hash_reset_token(token), user_id=user.id, expires_at=expires
        )
    )
    session.commit()
    return token


def reset_password(session: Session, token: str, password: str) -> User | None:
    """Set a new password with a reset token, or return None if it's invalid."""
    # Locked, so that two requests at once can't both use the token.
    reset_token = session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _hash_reset_token(token))
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
    session.commit()
    return user
