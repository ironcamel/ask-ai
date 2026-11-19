from fastapi import APIRouter, BackgroundTasks, status
from sqlmodel import select

from ask_ai.assistants import AssistantsDep, parse_mention, reply_to_post
from ask_ai.database import EngineDep, SessionDep
from ask_ai.dependencies import OwnPostDep, PaginationDep, PostDep
from ask_ai.models import (
    Comment,
    CommentPublic,
    Post,
    PostCreate,
    PostPublic,
    PostUpdate,
)
from ask_ai.security import CurrentUserDep

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=list[PostPublic])
def list_posts(session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(Post).order_by(Post.id).offset(pagination.offset).limit(pagination.limit)
    ).all()


@router.post("", response_model=PostPublic, status_code=status.HTTP_201_CREATED)
def create_post(
    post_in: PostCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
    engine: EngineDep,
    assistants: AssistantsDep,
    background_tasks: BackgroundTasks,
):
    post = Post.model_validate(post_in, update={"user_id": current_user.id})
    session.add(post)
    session.commit()
    session.refresh(post)
    # A post starting with "@claude" or "@gemini" gets the LLM's answer as a
    # comment. It arrives after the response, since LLM calls can be slow.
    if mention := parse_mention(post.body, list(assistants)):
        name, query = mention
        background_tasks.add_task(
            reply_to_post, engine, post.id, name, assistants[name], query
        )
    return post


@router.get("/{post_id}", response_model=PostPublic)
def read_post(post: PostDep):
    return post


@router.patch("/{post_id}", response_model=PostPublic)
def update_post(post: OwnPostDep, post_in: PostUpdate, session: SessionDep):
    post.sqlmodel_update(post_in.model_dump(exclude_unset=True))
    session.add(post)
    session.commit()
    session.refresh(post)
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post: OwnPostDep, session: SessionDep) -> None:
    session.delete(post)
    session.commit()


@router.get(
    "/{post_id}/comments", response_model=list[CommentPublic], tags=["comments"]
)
def list_post_comments(post: PostDep, session: SessionDep, pagination: PaginationDep):
    return session.exec(
        select(Comment)
        .where(Comment.post_id == post.id)
        .order_by(Comment.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
