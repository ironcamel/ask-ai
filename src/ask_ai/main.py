from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ask_ai.database import create_db_and_tables
from ask_ai.routers import comments, posts, users


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


app = FastAPI(title="ask-ai", lifespan=lifespan)

app.include_router(users.router)
app.include_router(posts.router)
app.include_router(comments.router)
