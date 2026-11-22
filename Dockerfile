# The app image. The same image serves the API (the default command) and runs
# the database migrations (`alembic upgrade head`), e.g. as a one-off ECS task.

FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv

# Compile bytecode at build time for faster startup, and copy packages into the
# venv rather than hard-linking them from the cache mount, which isn't kept.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install the dependencies first, in their own layer, so that code changes
# don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

RUN useradd --system --no-create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["fastapi", "run", "--port", "8000"]
