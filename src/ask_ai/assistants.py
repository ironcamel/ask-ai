"""Reply to posts that mention an LLM assistant, e.g. "@claude what is ...?"."""

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
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


def parse_mention(body: str, names: list[str]) -> tuple[str, str] | None:
    """Return (assistant name, query) if the body starts with "@<name> <query>".

    A comma may follow the name, as in "@<name>, <query>".
    """
    for name in names:
        prefix = f"@{name}"
        if not body.startswith(prefix):
            continue
        rest = body.removeprefix(prefix)
        if rest.startswith(","):
            rest = rest.removeprefix(",")
        # "@claudette" is not a mention of "@claude".
        elif rest and not rest[0].isspace():
            continue
        query = rest.strip()
        return (name, query) if query else None
    return None


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


def reply_to_post(
    engine: Engine, post_id: int, name: str, ask: Assistant, query: str
) -> None:
    """Ask the assistant the query and post its answer as a comment.

    Runs as a background task after the post has been created, so it opens its
    own session and logs failures rather than raising them.
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
