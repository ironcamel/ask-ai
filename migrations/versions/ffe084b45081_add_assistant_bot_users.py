"""Add assistant bot users

Revision ID: ffe084b45081
Revises: ddffc426bce0
Create Date: 2026-11-22 03:40:11.481225

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlmodel.sql.sqltypes import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "ffe084b45081"
down_revision: str | Sequence[str] | None = "ddffc426bce0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The table as it is at this revision. Data migrations don't import the app's
# models, which keep changing after this migration is written.
user = sa.table(
    "user",
    sa.column("username", sa.String),
    sa.column("email", sa.String),
    sa.column("created_at", UTCDateTime),
    sa.column("modified_at", UTCDateTime),
    sa.column("hashed_password", sa.String),
)

# The accounts that author the assistants' replies. They have no password, so
# no one can log in as them.
USERS = [
    {"username": "claude", "email": "claude@bots.example.com"},
    {"username": "gemini", "email": "gemini@bots.example.com"},
]


def upgrade() -> None:
    now = datetime.now(UTC)
    op.bulk_insert(
        user,
        [
            {**u, "created_at": now, "modified_at": now, "hashed_password": None}
            for u in USERS
        ],
    )


def downgrade() -> None:
    """Delete the users. Their posts and comments go with them, by cascade."""
    op.execute(user.delete().where(user.c.username.in_([u["username"] for u in USERS])))
