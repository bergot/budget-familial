"""rapprochement : table des rapprochements, statut de pointage des opérations

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("statement_balance_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        # `server_default` : les opérations déjà en base reçoivent « none » (non pointées).
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum(
                    "none",
                    "pointed",
                    "reconciled",
                    name="reconciliationstatus",
                    native_enum=False,
                    length=20,
                ),
                server_default="none",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("reconciliation_id", sa.Integer(), nullable=True))
        # La contrainte est nommée : sans nom, le `downgrade` ne pourrait pas la supprimer.
        batch_op.create_foreign_key(
            "fk_transactions_reconciliation_id", "reconciliations", ["reconciliation_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_transactions_reconciliation_id", type_="foreignkey")
        batch_op.drop_column("reconciliation_id")
        batch_op.drop_column("status")

    op.drop_table("reconciliations")
