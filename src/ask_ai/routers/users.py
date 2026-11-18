from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ask_ai.database import SessionDep
from ask_ai.dependencies import PaginationDep, UserDep
from ask_ai.models import (
    Comment,
    CommentPublic,
    Post,
    PostCreate,
    PostPublic,
    User,
    UserCreate,
    UserPublic,
    UserUpdate,
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


@router.get("", response_model=list[UserPublic])
def list_users(session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(User).order_by(User.id).offset(pagination.offset).limit(pagination.limit)
    ).all()


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, session: SessionDep):
    return _commit_user(session, User.model_validate(user_in))


@router.get("/{user_id}", response_model=UserPublic)
def read_user(user: UserDep):
    return user


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(user: UserDep, user_in: UserUpdate, session: SessionDep):
    user.sqlmodel_update(user_in.model_dump(exclude_unset=True))
    return _commit_user(session, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user: UserDep, session: SessionDep) -> None:
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


@router.post(
    "/{user_id}/posts",
    response_model=PostPublic,
    status_code=status.HTTP_201_CREATED,
    tags=["posts"],
)
def create_user_post(user: UserDep, post_in: PostCreate, session: SessionDep):
    post = Post.model_validate(post_in, update={"user_id": user.id})
    session.add(post)
    session.commit()
    session.refresh(post)
    return post


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
