"""Answer posts and comments that mention an LLM, e.g. "@claude what is ...?"."""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import anyio
from fastapi import BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, func, select

from ask_ai.config import settings
from ask_ai.llm import ask_claude, ask_gemini
from ask_ai.models import AssistantQuery, Comment, Post, User

logger = logging.getLogger(__name__)

Assistant = Callable[[str], str]

# LLM calls can take minutes, so they run in threads of their own, at most this
# many at once. Otherwise they'd take up the default thread pool that the
# endpoints, which are all sync, run in, and a burst of questions could stall
# every request. Questions beyond the limit wait their turn.
LLM_THREADS = anyio.CapacityLimiter(8)

# Each assistant's name is both its @mention and the username of the bot
# account that authors its replies.
ASSISTANTS: dict[str, Assistant] = {"claude": ask_claude, "gemini": ask_gemini}


def get_assistants() -> dict[str, Assistant]:
    return ASSISTANTS


AssistantsDep = Annotated[dict[str, Assistant], Depends(get_assistants)]


def find_mention(body: str, names: list[str]) -> str | None:
    """Return the first assistant mentioned anywhere in the body.

    "@claude" must stand alone: "@claudette" and "bob@claude.com" don't count.
    A body with nothing but mentions in it has no question, so mentions nothing.
    """
    names_re = "|".join(names)
    pattern = re.compile(rf"(?<!\w)@({names_re})\b")
    match = pattern.search(body)
    if not match:
        return None
    body = re.sub(names_re, "", body)
    if not re.search(r"\w", body):
        return None
    return match.group(1)


def _count_queries(
    session: Session, since: datetime, user_id: int | None = None
) -> int:
    query = select(func.count()).where(col(AssistantQuery.created_at) > since)
    if user_id is not None:
        query = query.where(AssistantQuery.user_id == user_id)
    return session.exec(query).one()


def check_mention(
    session: Session, assistants: dict[str, Assistant], user: User, body: str
) -> str | None:
    """Return the assistant a new post or comment mentions, if any.

    The question is counted against the hourly quotas, and rejected if the user
    or everyone together has used theirs up. The caller commits, along with the
    post or comment, so a rejected one isn't created at all.
    """
    name = find_mention(body, list(assistants))
    if name is None:
        return None
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    # Clear out queries the quotas no longer count.
    session.exec(
        delete(AssistantQuery).where(col(AssistantQuery.created_at) <= hour_ago)
    )
    if (
        _count_queries(session, hour_ago, user.id)
        >= settings.assistant_queries_per_user_per_hour
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You've asked the assistants too many questions this hour",
        )
    if _count_queries(session, hour_ago) >= settings.assistant_queries_per_hour:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "The assistants have answered too many questions this hour",
        )
    session.add(AssistantQuery(user_id=user.id))
    return name


def _get_or_create_bot(session: Session, name: str) -> User:
    bot = session.exec(select(User).where(User.username == name)).first()
    if bot is not None:
        return bot
    bot = User(username=name, email=f"{name}@bots.example.com")
    session.add(bot)
    try:
        session.commit()
    except IntegrityError:
        # Another request created the bot first.
        session.rollback()
        return session.exec(select(User).where(User.username == name)).one()
    session.refresh(bot)
    return bot


def schedule_reply(
    background_tasks: BackgroundTasks,
    engine: Engine,
    assistants: dict[str, Assistant],
    name: str | None,
    post_id: int,
    body: str,
) -> None:
    """Have the assistant that check_mention found answer a new post or comment.

    The whole body is the query, and the answer is added as a comment on the
    post. It arrives after the response, since LLM calls can be slow.
    """
    if name is not None:
        background_tasks.add_task(
            reply_to_post, engine, post_id, name, assistants[name], body.strip()
        )


async def reply_to_post(
    engine: Engine, post_id: int, name: str, ask: Assistant, query: str
) -> None:
    """Ask the assistant the query and post its answer as a comment.

    Runs as a background task after the post or comment has been created, so it
    opens its own session and logs failures rather than raising them.
    """
    await anyio.to_thread.run_sync(
        _reply_to_post, engine, post_id, name, ask, query, limiter=LLM_THREADS
    )


def _reply_to_post(
    engine: Engine, post_id: int, name: str, ask: Assistant, query: str
) -> None:
    try:
        answer = ask(query)
    except Exception:
        logger.exception("@%s failed to answer post %s", name, post_id)
        return

    with Session(engine) as session:
        if session.get(Post, post_id) is None:
            return  # The post was deleted while waiting for the answer.
        bot = _get_or_create_bot(session, name)
        session.add(Comment(body=answer, post_id=post_id, user_id=bot.id))
        session.commit()
