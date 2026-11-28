from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ask_ai.assistants import AssistantsDep
from ask_ai.database import SessionDep
from ask_ai.dependencies import OwnUserDep, PaginationDep, UserDep
from ask_ai.models import (
    Comment,
    CommentPublic,
    Post,
    PostPublic,
    User,
    UserCreate,
    UserPrivate,
    UserPublic,
    UserUpdate,
)
from ask_ai.security import (
    CurrentUserDep,
    hash_password,
    revoke_user_refresh_tokens,
    verify_password,
)

router = APIRouter(prefix="/users", tags=["users"])


def _commit_user(session: Session, user: User) -> User:
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Username or email already in use"
        )
    session.refresh(user)
    return user


def _reject_reserved_username(username: str | None, assistants: AssistantsDep):
    # Assistant names belong to the bot accounts that author their replies.
    if username in assistants:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Username is reserved"
        )


@router.get("", response_model=list[UserPublic])
def list_users(session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(User).order_by(User.id).offset(pagination.offset).limit(pagination.limit)
    ).all()


@router.post("", response_model=UserPrivate, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, session: SessionDep, assistants: AssistantsDep):
    _reject_reserved_username(user_in.username, assistants)
    user = User.model_validate(
        user_in, update={"hashed_password": hash_password(user_in.password)}
    )
    return _commit_user(session, user)


@router.get("/me", response_model=UserPrivate)
def read_current_user(current_user: CurrentUserDep):
    return current_user


@router.get("/{user_id}", response_model=UserPublic)
def read_user(user: UserDep):
    return user


@router.patch("/{user_id}", response_model=UserPrivate)
def update_user(
    user: OwnUserDep,
    user_in: UserUpdate,
    session: SessionDep,
    assistants: AssistantsDep,
):
    _reject_reserved_username(user_in.username, assistants)
    data = user_in.model_dump(exclude_unset=True)
    current_password = data.pop("current_password", None)
    if ("email" in data or "password" in data) and not verify_password(
        user, current_password
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Changing the email or password needs the current password",
        )
    if password := data.pop("password", None):
        data["hashed_password"] = hash_password(password)
        # Log out everywhere, in case the old password was compromised.
        revoke_user_refresh_tokens(session, user)
    user.sqlmodel_update(data)
    return _commit_user(session, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user: OwnUserDep, session: SessionDep) -> None:
    session.delete(user)
    session.commit()


@router.get("/{user_id}/posts", response_model=list[PostPublic], tags=["posts"])
def list_user_posts(user: UserDep, session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(Post)
        .where(Post.user_id == user.id)
        .order_by(Post.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()


@router.get(
    "/{user_id}/comments", response_model=list[CommentPublic], tags=["comments"]
)
def list_user_comments(user: UserDep, session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(Comment)
        .where(Comment.user_id == user.id)
        .order_by(Comment.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
