# ask-ai

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
`migrations/versions/ce7e5d5988d6_add_assistant_bot_users.py` for an example.

A database created before migrations were added already has the tables, so mark
it as being at the first migration, then upgrade:

```sh
uv run alembic stamp 0bb83c773dd2
uv run alembic upgrade head
```
