from datetime import UTC, datetime

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Users


class UserBase(SQLModel):
    username: str = Field(min_length=1, max_length=50, index=True, unique=True)
    email: EmailStr = Field(index=True, unique=True)


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    # None for accounts that can't log in, such as the assistant bots.
    hashed_password: str | None = None

    posts: list[Post] = Relationship(back_populates="author", cascade_delete=True)
    comments: list[Comment] = Relationship(back_populates="author", cascade_delete=True)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(SQLModel):
    username: str | None = Field(default=None, min_length=1, max_length=50)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserPublic(UserBase):
    id: int
    created_at: datetime


# Posts


class PostBase(SQLModel):
    body: str


class Post(PostBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)

    author: User = Relationship(back_populates="posts")
    comments: list[Comment] = Relationship(back_populates="post", cascade_delete=True)


class PostCreate(PostBase):
    pass


class PostUpdate(SQLModel):
    body: str | None = None


class PostPublic(PostBase):
    id: int
    user_id: int
    created_at: datetime


# Comments


class CommentBase(SQLModel):
    body: str = Field(min_length=1)


class Comment(CommentBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE", index=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", index=True)

    post: Post = Relationship(back_populates="comments")
    author: User = Relationship(back_populates="comments")


class CommentCreate(CommentBase):
    post_id: int = Field(ge=1)


class CommentUpdate(SQLModel):
    body: str | None = Field(default=None, min_length=1)


class CommentPublic(CommentBase):
    id: int
    post_id: int
    user_id: int
    created_at: datetime
