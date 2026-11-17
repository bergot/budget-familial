"""échéances : table des échéances récurrentes, lien opération -> échéance

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "monthly", "quarterly", "yearly", name="frequency", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("generated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payee_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("payment_method_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("transfer_account_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["payee_id"],
            ["payees.id"],
        ),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_methods.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transfer_account_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
        # Nommée (sinon le downgrade ne peut pas la supprimer) ; ON DELETE SET NULL : supprimer une
        # échéance conserve les opérations déjà générées.
        batch_op.create_foreign_key(
            "fk_transactions_schedule_id", "schedules", ["schedule_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_transactions_schedule_id", type_="foreignkey")
        batch_op.drop_column("schedule_id")

    op.drop_table("schedules")
