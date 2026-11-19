from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlmodel import Session, SQLModel

from ask_ai.database import SessionDep
from ask_ai.models import Comment, Post, User
from ask_ai.security import CurrentUserDep


class Pagination(BaseModel):
    offset: int = 0
    limit: int = 100


def get_pagination(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Pagination:
    return Pagination(offset=offset, limit=limit)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]


def ensure_exists(session: Session, model: type[SQLModel], id: int) -> None:
    """Reject a request body that references a row that doesn't exist."""
    if session.get(model, id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{model.__name__} not found"
        )


def get_user(user_id: Annotated[int, Path(ge=1)], session: SessionDep) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def get_post(post_id: Annotated[int, Path(ge=1)], session: SessionDep) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return post


def get_comment(comment_id: Annotated[int, Path(ge=1)], session: SessionDep) -> Comment:
    comment = session.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    return comment


UserDep = Annotated[User, Depends(get_user)]
PostDep = Annotated[Post, Depends(get_post)]
CommentDep = Annotated[Comment, Depends(get_comment)]


# Only the owner may change or delete a resource.


def _ensure_owner(owner_id: int | None, current_user: User) -> None:
    if owner_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


def get_own_user(user: UserDep, current_user: CurrentUserDep) -> User:
    _ensure_owner(user.id, current_user)
    return user


def get_own_post(post: PostDep, current_user: CurrentUserDep) -> Post:
    _ensure_owner(post.user_id, current_user)
    return post


def get_own_comment(comment: CommentDep, current_user: CurrentUserDep) -> Comment:
    _ensure_owner(comment.user_id, current_user)
    return comment


OwnUserDep = Annotated[User, Depends(get_own_user)]
OwnPostDep = Annotated[Post, Depends(get_own_post)]
OwnCommentDep = Annotated[Comment, Depends(get_own_comment)]
