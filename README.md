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
- The assistants answer at most `ASSISTANT_QUERIES_PER_USER_PER_HOUR` questions
  an hour from each user, and `ASSISTANT_QUERIES_PER_HOUR` from everyone
  together, which caps what the model APIs cost. A post or comment with a
  question beyond either quota is rejected with `429 Too Many Requests` and
  isn't created; one without a question is never limited.

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
| `ACCESS_TOKEN_EXPIRE_MINUTES` | How long an access token lasts. Defaults to 30. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | How long a login lasts unused, before you have to log in again. Each refresh restarts it. Defaults to 14. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | The mail server that sends password reset emails. The port defaults to 587. When `SMTP_HOST` is unset, emails are logged instead of sent. |
| `SMTP_STARTTLS` | Whether to switch the SMTP connection to TLS. Defaults to `true`; set it to `false` for a local test server such as [Mailpit](https://mailpit.axllent.org/). |
| `EMAIL_FROM` | The sender of the emails, e.g. `ask-ai <noreply@example.com>`. |
| `PASSWORD_RESET_URL` | The page where users choose a new password. The reset email links to it with `?token=...` added. When unset, the email contains just the token. |
| `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | How long a password reset token lasts. Defaults to 60. |
| `PASSWORD_RESET_EMAIL_INTERVAL_MINUTES` | How long after a reset email another can be sent to the same account. Defaults to 5. |
| `ASSISTANT_QUERIES_PER_USER_PER_HOUR` | How many questions the assistants answer from each user in an hour. Defaults to 20. |
| `ASSISTANT_QUERIES_PER_HOUR` | How many questions the assistants answer from everyone together in an hour. Defaults to 200. |
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

### With Docker

`compose.yaml` runs the app in a container with its own PostgreSQL. It reads
settings from `.env`, except `DATABASE_URL`, which points at the compose
database. The migrations run before the app starts.

```sh
docker compose up --build
```

The API is served at <http://127.0.0.1:8000>. The database is kept in the
`db-data` volume; `docker compose down -v` deletes it.

The `Dockerfile` builds the image used for deployment. The image serves the
API by default, and `alembic upgrade head` as its command runs the migrations.
It contains no secrets, so pass the settings as environment variables.

## Authentication

Reading is public. Creating anything requires an access token, and only a
resource's author can change or delete it. Email addresses aren't public: a
user's own appears only in their sign-up response, `/users/me`, and the response
to updating their account.

```sh
# Sign up
curl -X POST localhost:8000/users -H 'Content-Type: application/json' \
  -d '{"username": "alice", "email": "alice@example.com", "password": "correct-horse"}'

# Log in to get an access token, and a refresh token cookie
curl -X POST localhost:8000/auth/token -c cookies.txt \
  -d 'username=alice&password=correct-horse'

# Ask a question
curl -X POST localhost:8000/posts -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"body": "@claude why is the sky blue?"}'
```

The usernames `claude` and `gemini` are reserved for the bot accounts.

Changing your email or password needs your current password too, so that
someone with a stolen access token can't take the account over:

```sh
curl -X PATCH localhost:8000/users/1 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"password": "new-password", "current_password": "correct-horse"}'
```

### Staying logged in

An access token lasts only `ACCESS_TOKEN_EXPIRE_MINUTES`, but logging in also
sets a `refresh_token` cookie, which gets a new access token without the
password:

```sh
curl -X POST localhost:8000/auth/refresh -b cookies.txt -c cookies.txt
```

The response is the same as a login's, and its `expires_in` says how many
seconds the access token lasts. A refresh token works once, so each refresh
replaces the cookie with a new one. If a used refresh token is sent again,
someone has a copy of it, so that login ends and has to be made again.

The cookie is `HttpOnly`, so page scripts can't read it, and `Secure` and
`SameSite=Strict`, so browsers send it only over HTTPS (or to localhost) and
only from this site's own pages. Its path is `/auth`, so it isn't sent with
other requests.

Log out to end the login:

```sh
curl -X POST localhost:8000/auth/logout -b cookies.txt -c cookies.txt
```

Changing or resetting your password ends all your logins. Access tokens
already issued keep working until they expire.

### Resetting a forgotten password

Ask for a reset token, which is emailed to the account's address. The response
is the same whether or not the address has an account.

```sh
curl -X POST localhost:8000/auth/password-reset -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com"}'
```

Then set a new password with the token from the email:

```sh
curl -X POST localhost:8000/auth/password-reset/confirm -H 'Content-Type: application/json' \
  -d '{"token": "...", "password": "new-password"}'
```

A token works once, and only until it expires. Asking again replaces any
earlier token, but only after `PASSWORD_RESET_EMAIL_INTERVAL_MINUTES`: until
then, no new email is sent, though the response is the same. The reset ends all your logins, but access tokens issued before
it keep working until they expire.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/token` | Log in and get an access token and a refresh token cookie |
| `POST` | `/auth/refresh` | Get a new access token with the refresh token cookie |
| `POST` | `/auth/logout` | End the refresh token cookie's login |
| `POST` | `/auth/password-reset` | Email a password reset token: `{"email": "..."}` |
| `POST` | `/auth/password-reset/confirm` | Set a new password: `{"token": "...", "password": "..."}` |
| `GET` | `/users` | List users |
| `POST` | `/users` | Sign up |
| `GET` | `/users/me` | The logged-in user, with their email address |
| `GET` | `/users/{id}` | Get a user |
| `PATCH` | `/users/{id}` | Update your account; changing the email or password needs `current_password` |
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
Posts and comments are at most 10,000 characters long.

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
