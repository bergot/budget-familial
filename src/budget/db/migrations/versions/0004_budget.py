"""budget : montants prévus par catégorie et par mois, type dépense/recette des catégories

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _infer_income_categories(connection: sa.Connection) -> None:
    """Pour les catégories déjà utilisées : celles dont les opérations sont globalement
    positives deviennent des recettes (sinon toutes seraient classées en dépenses).

    Le total se calcule pour la catégorie et ses sous-catégories ensemble, virements exclus.
    """
    totals = connection.execute(
        sa.text(
            "SELECT COALESCE(c.parent_id, c.id), SUM(t.amount_cents) "
            "FROM transactions t JOIN categories c ON c.id = t.category_id "
            "WHERE t.transfer_peer_id IS NULL "
            "GROUP BY COALESCE(c.parent_id, c.id)"
        )
    ).fetchall()
    for root_id, net in totals:
        if net > 0:
            connection.execute(
                sa.text("UPDATE categories SET kind = 'income' WHERE id = :r OR parent_id = :r"),
                {"r": root_id},
            )


def upgrade() -> None:
    op.create_table(
        "budget_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("planned_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "year", "month", name="uq_budget_lines_category_month"),
    )
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.Enum("expense", "income", name="categorykind", native_enum=False, length=20),
                server_default="expense",  # les catégories existantes : des dépenses...
                nullable=False,
            )
        )
    _infer_income_categories(op.get_bind())  # ... sauf celles qui ressemblent à des recettes


def downgrade() -> None:
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_column("kind")
    op.drop_table("budget_lines")
