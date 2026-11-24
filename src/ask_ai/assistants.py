"""Answer posts and comments that mention an LLM, e.g. "@claude what is ...?"."""

import logging
import re
from collections.abc import Callable
from typing import Annotated

from fastapi import BackgroundTasks, Depends
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ask_ai.llm import ask_claude, ask_gemini
from ask_ai.models import Comment, Post, User

logger = logging.getLogger(__name__)

Assistant = Callable[[str], str]

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
    post_id: int,
    body: str,
) -> None:
    """Have the assistant mentioned in a new post or comment answer it.

    The whole body is the query, and the answer is added as a comment on the
    post. It arrives after the response, since LLM calls can be slow.
    """
    if name := find_mention(body, list(assistants)):
        background_tasks.add_task(
            reply_to_post, engine, post_id, name, assistants[name], body.strip()
        )


def reply_to_post(
    engine: Engine, post_id: int, name: str, ask: Assistant, query: str
) -> None:
    """Ask the assistant the query and post its answer as a comment.

    Runs as a background task after the post or comment has been created, so it
    opens its own session and logs failures rather than raising them.
    """
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
