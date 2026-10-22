"""Initial empty migration.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-28 14:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Initial empty baseline migration."""
    pass


def downgrade() -> None:
    """Downgrade baseline migration."""
    pass
