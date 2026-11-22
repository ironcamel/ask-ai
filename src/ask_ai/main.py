from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ask_ai.config import settings
from ask_ai.routers import auth, comments, posts, users


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if settings.jwt_secret_key is None:
        raise RuntimeError(
            "Set JWT_SECRET_KEY in .env (generate one with: openssl rand -hex 32)"
        )
    yield


app = FastAPI(title="ask-ai", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(posts.router)
app.include_router(comments.router)
