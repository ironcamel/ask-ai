"""Add modified_at to all tables

Revision ID: 4a14c8185895
Revises: ce7e5d5988d6
Create Date: 2026-11-22 02:44:21.055189

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a14c8185895"
down_revision: str | Sequence[str] | None = "ce7e5d5988d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["user", "post", "comment"]


def upgrade() -> None:
    """Upgrade schema."""
    for name in TABLES:
        # Existing rows have no value yet, so the column starts out nullable.
        with op.batch_alter_table(name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "modified_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True
                )
            )

        # They haven't been tracked, so count them as unmodified since creation.
        table = sa.table(name, sa.column("created_at"), sa.column("modified_at"))
        op.execute(table.update().values(modified_at=table.c.created_at))

        with op.batch_alter_table(name) as batch_op:
            batch_op.alter_column(
                "modified_at",
                existing_type=sqlmodel.sql.sqltypes.UTCDateTime(),
                nullable=False,
            )


def downgrade() -> None:
    """Downgrade schema."""
    for name in reversed(TABLES):
        with op.batch_alter_table(name) as batch_op:
            batch_op.drop_column("modified_at")
