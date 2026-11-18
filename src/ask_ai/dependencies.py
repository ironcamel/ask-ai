from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from ask_ai.database import SessionDep
from ask_ai.models import Comment, Post, User


class Pagination(BaseModel):
    offset: int = 0
    limit: int = 100


def get_pagination(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Pagination:
    return Pagination(offset=offset, limit=limit)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]


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
