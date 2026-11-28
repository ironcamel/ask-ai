from fastapi import APIRouter, BackgroundTasks, status
from sqlmodel import select

from ask_ai.assistants import AssistantsDep, check_mention, schedule_reply
from ask_ai.database import EngineDep, SessionDep
from ask_ai.dependencies import CommentDep, OwnCommentDep, PaginationDep, ensure_exists
from ask_ai.models import (
    Comment,
    CommentCreate,
    CommentPublic,
    CommentUpdate,
    Post,
)
from ask_ai.security import CurrentUserDep

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
def create_comment(
    comment_in: CommentCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
    engine: EngineDep,
    assistants: AssistantsDep,
    background_tasks: BackgroundTasks,
):
    ensure_exists(session, Post, comment_in.post_id)
    name = check_mention(session, assistants, current_user, comment_in.body)
    comment = Comment.model_validate(comment_in, update={"user_id": current_user.id})
    session.add(comment)
    session.commit()
    session.refresh(comment)
    schedule_reply(
        background_tasks, engine, assistants, name, comment.post_id, comment.body
    )
    return comment


@router.get("/{comment_id}", response_model=CommentPublic)
def read_comment(comment: CommentDep):
    return comment


@router.patch("/{comment_id}", response_model=CommentPublic)
def update_comment(
    comment: OwnCommentDep, comment_in: CommentUpdate, session: SessionDep
):
    comment.sqlmodel_update(comment_in.model_dump(exclude_unset=True))
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment: OwnCommentDep, session: SessionDep) -> None:
    session.delete(comment)
    session.commit()
