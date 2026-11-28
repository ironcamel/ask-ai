from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, EmailStr, StringConstraints
from sqlalchemy import event
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


# The longest post or comment a user can write. The assistants' answers can be
# longer, so the limit applies to what users send, not to the column.
MAX_BODY_LENGTH = 10_000


# Users


# A username chosen by a user: ASCII word characters, stored lowercase. The
# pattern is spelled out because \w would also match non-ASCII letters, and it
# is checked before lowercasing, which can turn some of those (such as the
# Kelvin sign) into ASCII ones.
Username = Annotated[
    str,
    StringConstraints(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$"),
    AfterValidator(str.lower),
]


class UserBase(SQLModel):
    username: str = Field(min_length=1, max_length=50, index=True, unique=True)
    email: EmailStr = Field(index=True, unique=True)


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    modified_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"onupdate": _utcnow}
    )
    # None for accounts that can't log in, such as the assistant bots.
    hashed_password: str | None = None

    posts: list[Post] = Relationship(back_populates="author", cascade_delete=True)
    comments: list[Comment] = Relationship(back_populates="author", cascade_delete=True)


class UserCreate(UserBase):
    username: Username
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(SQLModel):
    username: Username | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    # Required to change the email or password, so that a stolen access token
    # can't be used to take the account over.
    current_password: str | None = None


class UserPublic(SQLModel):
    """A user as anyone can see them: without their email address."""

    id: int
    username: str
    created_at: datetime
    modified_at: datetime


class UserPrivate(UserPublic):
    """A user as they see themselves."""

    email: EmailStr


# Password resets


class PasswordResetToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # A SHA-256 hash of the token. The token itself is only in the email, so a
    # leaked database can't be used to reset passwords.
    token_hash: str = Field(index=True, unique=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime


# Refresh tokens


class RefreshToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # A SHA-256 hash of the token, like PasswordResetToken's.
    token_hash: str = Field(index=True, unique=True)
    # The tokens descended from one login. Each refresh uses up a token and
    # adds its replacement to the family.
    family_id: str = Field(index=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime
    # Set when the token is used. Used tokens are kept until they expire, so
    # that one used again, which means it was stolen, can be recognized.
    used_at: datetime | None = None


class PasswordResetRequest(SQLModel):
    email: EmailStr


class PasswordReset(SQLModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


# Assistant queries


class AssistantQuery(SQLModel, table=True):
    """A question a user asked an assistant, counted against the hourly quotas.

    Kept for an hour, which is as far back as the quotas look.
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)


# Posts


class PostBase(SQLModel):
    body: str


class Post(PostBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    modified_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"onupdate": _utcnow}
    )
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)

    author: User = Relationship(back_populates="posts")
    comments: list[Comment] = Relationship(back_populates="post", cascade_delete=True)


class PostCreate(PostBase):
    body: str = Field(max_length=MAX_BODY_LENGTH)


class PostUpdate(SQLModel):
    body: str | None = Field(default=None, max_length=MAX_BODY_LENGTH)


class PostPublic(PostBase):
    id: int
    user_id: int
    created_at: datetime
    modified_at: datetime


# Comments


class CommentBase(SQLModel):
    body: str = Field(min_length=1)


class Comment(CommentBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    modified_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"onupdate": _utcnow}
    )
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE", index=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)

    post: Post = Relationship(back_populates="comments")
    author: User = Relationship(back_populates="comments")


class CommentCreate(CommentBase):
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
    post_id: int = Field(ge=1)


class CommentUpdate(SQLModel):
    body: str | None = Field(default=None, min_length=1, max_length=MAX_BODY_LENGTH)


class CommentPublic(CommentBase):
    id: int
    post_id: int
    user_id: int
    created_at: datetime
    modified_at: datetime


@event.listens_for(User, "before_insert")
@event.listens_for(Post, "before_insert")
@event.listens_for(Comment, "before_insert")
def _start_unmodified(_mapper, _connection, target: User | Post | Comment) -> None:
    # The two defaults are a moment apart, so make them equal: a row whose
    # modified_at is its created_at has never been changed.
    target.modified_at = target.created_at
