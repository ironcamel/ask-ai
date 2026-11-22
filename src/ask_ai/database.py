from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from ask_ai.config import settings

engine = create_engine(settings.database_url)


def get_engine() -> Engine:
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]


def get_session(engine: EngineDep) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
