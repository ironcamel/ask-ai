from fastapi import APIRouter, status
from sqlmodel import select

from ask_ai.database import SessionDep
from ask_ai.dependencies import CommentDep, PaginationDep, ensure_exists
from ask_ai.models import (
    Comment,
    CommentCreate,
    CommentPublic,
    CommentUpdate,
    Post,
    User,
)

router = APIRouter(prefix="/comments", tags=["comments"])


@router.get("", response_model=list[CommentPublic])
def list_comments(session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(Comment)
        .order_by(Comment.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()


@router.post("", response_model=CommentPublic, status_code=status.HTTP_201_CREATED)
def create_comment(comment_in: CommentCreate, session: SessionDep):
    ensure_exists(session, Post, comment_in.post_id)
    ensure_exists(session, User, comment_in.user_id)
    comment = Comment.model_validate(comment_in)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.get("/{comment_id}", response_model=CommentPublic)
def read_comment(comment: CommentDep):
    return comment


@router.patch("/{comment_id}", response_model=CommentPublic)
def update_comment(comment: CommentDep, comment_in: CommentUpdate, session: SessionDep):
    comment.sqlmodel_update(comment_in.model_dump(exclude_unset=True))
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment: CommentDep, session: SessionDep) -> None:
    session.delete(comment)
    session.commit()
