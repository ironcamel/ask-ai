"""Add assistant bot users

Revision ID: ce7e5d5988d6
Revises: 0bb83c773dd2
Create Date: 2026-11-22 02:12:04.047637

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlmodel.sql.sqltypes import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "ce7e5d5988d6"
down_revision: str | Sequence[str] | None = "0bb83c773dd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables as they are at this revision. Data migrations don't import the app's
# models, which keep changing after this migration is written.
user = sa.table(
    "user",
    sa.column("id", sa.Integer),
    sa.column("username", sa.String),
    sa.column("email", sa.String),
    sa.column("created_at", UTCDateTime),
    sa.column("hashed_password", sa.String),
)
post = sa.table("post", sa.column("user_id", sa.Integer))
comment = sa.table("comment", sa.column("user_id", sa.Integer))

# The accounts that author the assistants' replies. They have no password, so
# no one can log in as them.
USERS = [
    {"username": "claude", "email": "claude@bots.example.com"},
    {"username": "gemini", "email": "gemini@bots.example.com"},
]


def upgrade() -> None:
    """Add the users that don't exist yet."""
    conn = op.get_bind()
    taken = set(conn.scalars(sa.select(user.c.username))) | set(
        conn.scalars(sa.select(user.c.email))
    )
    now = datetime.now(UTC)
    new_users = [
        {**u, "created_at": now, "hashed_password": None}
        for u in USERS
        if u["username"] not in taken and u["email"] not in taken
    ]
    if new_users:
        op.bulk_insert(user, new_users)


def downgrade() -> None:
    """Delete the users, along with their posts and comments."""
    # Deleted explicitly, since SQLite only cascades with foreign keys enabled.
    user_ids = sa.select(user.c.id).where(
        user.c.username.in_([u["username"] for u in USERS])
    )
    op.execute(comment.delete().where(comment.c.user_id.in_(user_ids)))
    op.execute(post.delete().where(post.c.user_id.in_(user_ids)))
    op.execute(user.delete().where(user.c.id.in_(user_ids)))
