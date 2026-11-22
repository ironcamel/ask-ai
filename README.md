# ask-ai

A discussion forum REST API where you can ask an AI a question just by mentioning
it. Users write posts, and other users comment on them. When a new post or
comment mentions an AI assistant, the text is sent to that assistant's model, and
its answer is added as a comment on the same post, written by the assistant's bot
account. The assistants currently available are `@claude` and `@gemini`.

Built with [FastAPI](https://fastapi.tiangolo.com/) and
[SQLModel](https://sqlmodel.tiangolo.com/), on PostgreSQL.

## How mentions work

- A mention can appear anywhere in the text: `@claude why is the sky blue?`,
  `What do you think, @gemini?`. It must stand on its own, so `@claudette` and
  `bob@claude.com` don't count. Mentions are case-sensitive.
- The whole post or comment, mention included, is sent as the query.
- If several assistants are mentioned, only the first one answers.
- Text with nothing but mentions in it, such as `@claude`, isn't sent.
- Only new posts and comments are answered, not edits.
- The answer arrives shortly after the post or comment is created, since the
  model is called in the background. If the call fails, the error is logged and
  no answer is posted.

## Setup

Install [uv](https://docs.astral.sh/uv/) and [PostgreSQL](https://www.postgresql.org/),
then create your local config file:

```sh
cp .env.example .env
```

Fill in `.env`. It holds secrets and is ignored by git.

| Setting | Description |
| --- | --- |
| `JWT_SECRET_KEY` | Required. Signs login tokens. Generate one with `openssl rand -hex 32`. |
| `ANTHROPIC_API_KEY` | API key for `@claude`, from the [Claude Console](https://console.anthropic.com/). |
| `GEMINI_API_KEY` | API key for `@gemini`, from [Google AI Studio](https://aistudio.google.com/). |
| `DATABASE_URL` | The PostgreSQL database, e.g. `postgresql+psycopg://user:password@localhost/ask_ai`. Defaults to `postgresql+psycopg://localhost/ask_ai`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | How long a login token lasts. Defaults to 30. |
| `CLAUDE_MODEL`, `GEMINI_MODEL` | The models that answer mentions. |

Environment variables take precedence over `.env`.

Create the database tables (see [Database migrations](#database-migrations)):

```sh
uv run alembic upgrade head
```

## Running

```sh
uv run fastapi dev
```

The API is served at <http://127.0.0.1:8000>, with interactive docs at
<http://127.0.0.1:8000/docs>. Use the **Authorize** button there to log in.

## Authentication

Reading is public. Creating anything requires a login token, and only a
resource's author can change or delete it.

```sh
# Sign up
curl -X POST localhost:8000/users -H 'Content-Type: application/json' \
  -d '{"username": "alice", "email": "alice@example.com", "password": "correct-horse"}'

# Log in to get a token
curl -X POST localhost:8000/auth/token -d 'username=alice&password=correct-horse'

# Ask a question
curl -X POST localhost:8000/posts -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"body": "@claude why is the sky blue?"}'
```

The usernames `claude` and `gemini` are reserved for the bot accounts.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/token` | Log in and get a token |
| `GET` | `/users` | List users |
| `POST` | `/users` | Sign up |
| `GET` | `/users/me` | The logged-in user |
| `GET` | `/users/{id}` | Get a user |
| `PATCH` | `/users/{id}` | Update your account |
| `DELETE` | `/users/{id}` | Delete your account, with its posts and comments |
| `GET` | `/users/{id}/posts` | A user's posts |
| `GET` | `/users/{id}/comments` | A user's comments |
| `GET` | `/posts` | List posts |
| `POST` | `/posts` | Create a post: `{"body": "..."}` |
| `GET` | `/posts/{id}` | Get a post |
| `PATCH` | `/posts/{id}` | Edit your post |
| `DELETE` | `/posts/{id}` | Delete your post, with its comments |
| `GET` | `/posts/{id}/comments` | A post's comments |
| `GET` | `/comments` | List comments |
| `POST` | `/comments` | Comment on a post: `{"post_id": 1, "body": "..."}` |
| `GET` | `/comments/{id}` | Get a comment |
| `PATCH` | `/comments/{id}` | Edit your comment |
| `DELETE` | `/comments/{id}` | Delete your comment |

Lists are paginated with `?offset=0&limit=100` (the limit is at most 100).

## Tests

```sh
uv run pytest
```

The tests use fake assistants, so they need no API keys and make no calls to
the models. They do need PostgreSQL: they create throwaway databases on the
server in `DATABASE_URL`, named after its database (`ask_ai_test` and
`ask_ai_test_migrations` for `ask_ai`), and drop them when they finish. The
`DATABASE_URL` user needs permission to create databases.

## Database migrations

The schema and seed data are managed with [Alembic](https://alembic.sqlalchemy.org/),
against the database in `DATABASE_URL`. The app doesn't create tables itself, so
bring the database up to date before starting it:

```sh
uv run alembic upgrade head
```

After changing the models in `src/ask_ai/models.py`, generate a migration and
review it before committing:

```sh
uv run alembic revision --autogenerate -m "Describe the change"
```

For data changes, such as adding users, create an empty migration with
`uv run alembic revision -m "..."` and write the inserts yourself. See
`migrations/versions/ffe084b45081_add_assistant_bot_users.py` for an example.
