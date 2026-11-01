"""add comment table

Revision ID: ad29012dd9fa
Revises: 82a0a416548d
Create Date: 2026-10-31 20:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ad29012dd9fa"
down_revision = "82a0a416548d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment",
        sa.Column("comment_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "complaint_id",
            sa.Integer(),
            sa.ForeignKey("complaint.complaint_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("comment_id", name="comment_pkey"),
    )


def downgrade() -> None:
    op.drop_table("comment")