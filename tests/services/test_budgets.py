import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Account, BudgetLine
from budget.domain.enums import CategoryKind
from budget.domain.errors import InvalidError, NotFoundError
from budget.services import budgets as bud
from budget.services import categories
from budget.services import transactions as tx
from budget.services.budgets import Budget, BudgetRow, RowKind
from budget.services.transactions import TransactionData, TransferData

D = dt.date
EXPENSE, INCOME = CategoryKind.EXPENSE, CategoryKind.INCOME


class Cats:
    """Un petit arbre de catégories : Revenus > Salaire ; Alimentation > Courses, Restaurant ;
    Loisirs (sans sous-catégorie)."""

    def __init__(self, session: Session) -> None:
        revenus = categories.create_category(session, "Revenus", kind=INCOME)
        self.revenus = revenus.id
        self.salaire = categories.create_category(session, "Salaire", parent_id=revenus.id).id
        alimentation = categories.create_category(session, "Alimentation")
        self.alimentation = alimentation.id
        self.courses = categories.create_category(session, "Courses", parent_id=alimentation.id).id
        self.restaurant = categories.create_category(
            session, "Restaurant", parent_id=alimentation.id
        ).id
        self.loisirs = categories.create_category(session, "Loisirs").id


@pytest.fixture
def cats(session: Session) -> Cats:
    return Cats(session)


def spend(
    session: Session, account: Account, day: dt.date, cents: int, category_id: int | None
) -> None:
    """Ajoute une opération (cents < 0 : dépense ; > 0 : recette)."""
    tx.add_transaction(
        session,
        TransactionData(
            account_id=account.id, date=day, amount_cents=cents, category_id=category_id
        ),
    )


def row(budget: Budget, label: str, kind: RowKind | None = None) -> BudgetRow:
    matches = [r for r in budget.rows if r.label == label and (kind is None or r.kind is kind)]
    assert len(matches) == 1, (
        f"{label!r} : {len(matches)} ligne(s) dans {[r.label for r in budget.rows]}"
    )
    return matches[0]


def count_lines(session: Session) -> int:
    return int(session.scalar(select(func.count(BudgetLine.id))) or 0)


# --- Saisie des montants prévus -------------------------------------------------------------


def test_set_planned_creates_updates_and_deletes(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 3, 5_000)
    assert count_lines(session) == 1
    assert row(bud.build_budget(session, 2026), "Loisirs").planned[2] == 5_000  # mars

    bud.set_planned(session, cats.loisirs, 2026, 3, 7_500)  # modification : pas de doublon
    assert count_lines(session) == 1
    assert row(bud.build_budget(session, 2026), "Loisirs").planned[2] == 7_500

    bud.set_planned(session, cats.loisirs, 2026, 3, 0)  # zéro : la ligne disparaît
    assert count_lines(session) == 0


def test_setting_zero_where_nothing_exists_is_harmless(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 3, 0)
    assert count_lines(session) == 0


@pytest.mark.parametrize(
    ("year", "month", "amount", "message"),
    [
        (2026, 3, -100, "négatif"),
        (2026, 0, 100, "mois"),
        (2026, 13, 100, "mois"),
        (1999, 3, 100, "année"),
        (2101, 3, 100, "année"),
    ],
)
def test_set_planned_validation(
    session: Session, cats: Cats, year: int, month: int, amount: int, message: str
) -> None:
    with pytest.raises(InvalidError, match=message):
        bud.set_planned(session, cats.loisirs, year, month, amount)
    assert count_lines(session) == 0


def test_set_planned_unknown_category(session: Session) -> None:
    with pytest.raises(NotFoundError):
        bud.set_planned(session, 999, 2026, 1, 100)


def test_fill_planned_to_the_right(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 1, 1_000)
    bud.fill_planned(session, cats.loisirs, 2026, from_month=4, amount_cents=2_500)

    planned = row(bud.build_budget(session, 2026), "Loisirs").planned
    assert planned == (1_000, 0, 0, *([2_500] * 9))
    with pytest.raises(InvalidError):
        bud.fill_planned(session, cats.loisirs, 2026, from_month=13, amount_cents=1)


def test_fill_with_zero_clears_the_right_part(session: Session, cats: Cats) -> None:
    bud.fill_planned(session, cats.loisirs, 2026, from_month=1, amount_cents=100)
    bud.fill_planned(session, cats.loisirs, 2026, from_month=7, amount_cents=0)
    assert row(bud.build_budget(session, 2026), "Loisirs").planned == (*([100] * 6), *([0] * 6))


def test_copy_planned_to_the_next_year(session: Session, cats: Cats) -> None:
    bud.fill_planned(session, cats.loisirs, 2026, from_month=1, amount_cents=100)
    bud.set_planned(session, cats.courses, 2026, 6, 40_000)

    written = bud.copy_planned(session, 2026, 2027)

    assert written == 13
    budget = bud.build_budget(session, 2027)
    assert row(budget, "Loisirs").planned == (100,) * 12
    assert row(budget, "Courses").planned[5] == 40_000
    assert row(bud.build_budget(session, 2026), "Loisirs").planned == (100,) * 12  # source intacte


def test_copy_does_not_overwrite_by_default(session: Session, cats: Cats) -> None:
    bud.fill_planned(session, cats.loisirs, 2026, from_month=1, amount_cents=100)
    bud.set_planned(session, cats.loisirs, 2027, 2, 999)  # déjà saisi dans l'année cible

    assert bud.copy_planned(session, 2026, 2027) == 11
    assert row(bud.build_budget(session, 2027), "Loisirs").planned[1] == 999  # conservé

    assert bud.copy_planned(session, 2026, 2027, overwrite=True) == 12
    assert row(bud.build_budget(session, 2027), "Loisirs").planned[1] == 100


def test_copy_needs_two_different_years(session: Session) -> None:
    with pytest.raises(InvalidError):
        bud.copy_planned(session, 2026, 2026)


# --- Structure de la grille -----------------------------------------------------------------


def test_empty_budget_has_only_the_skeleton(session: Session) -> None:
    budget = bud.build_budget(session, 2026)
    assert [(r.kind, r.label) for r in budget.rows] == [
        (RowKind.HEADER, "Recettes"),
        (RowKind.SECTION_TOTAL, "Total recettes"),
        (RowKind.HEADER, "Dépenses"),
        (RowKind.SECTION_TOTAL, "Total dépenses"),
        (RowKind.BALANCE, "Solde (recettes - dépenses)"),
    ]
    assert budget.year == 2026


def test_grid_layout_with_categories(session: Session, cats: Cats) -> None:
    budget = bud.build_budget(session, 2026)
    assert [(r.kind, r.label) for r in budget.rows] == [
        (RowKind.HEADER, "Recettes"),
        (RowKind.PARENT_TOTAL, "Revenus"),
        (RowKind.CHILD, "Salaire"),
        (RowKind.SECTION_TOTAL, "Total recettes"),
        (RowKind.HEADER, "Dépenses"),
        (RowKind.PARENT_TOTAL, "Alimentation"),
        (RowKind.CHILD, "Courses"),
        (RowKind.CHILD, "Restaurant"),
        (RowKind.CATEGORY, "Loisirs"),  # triées par nom : Alimentation avant Loisirs
        (RowKind.SECTION_TOTAL, "Total dépenses"),
        (RowKind.BALANCE, "Solde (recettes - dépenses)"),
    ]


def test_editable_rows_and_depth(session: Session, cats: Cats) -> None:
    bud.set_planned(
        session, cats.alimentation, 2026, 1, 100
    )  # donne une ligne « sans sous-catégorie »
    budget = bud.build_budget(session, 2026)
    editable = {r.label for r in budget.rows if r.editable}
    assert editable == {"Salaire", "Courses", "Restaurant", "Loisirs", "(sans sous-catégorie)"}
    assert row(budget, "Courses").depth == 1 and row(budget, "Loisirs").depth == 0
    assert row(budget, "Alimentation").depth == 0 and not row(budget, "Alimentation").editable


def test_each_editable_row_knows_which_category_to_edit(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.alimentation, 2026, 1, 100)
    budget = bud.build_budget(session, 2026)
    assert row(budget, "Courses").category_id == cats.courses
    assert row(budget, "Loisirs").category_id == cats.loisirs
    assert row(budget, "(sans sous-catégorie)").category_id == cats.alimentation
    assert row(budget, "Total dépenses").category_id is None


def test_empty_direct_row_is_hidden_unless_requested(session: Session, cats: Cats) -> None:
    assert "(sans sous-catégorie)" not in [r.label for r in bud.build_budget(session, 2026).rows]
    shown = bud.build_budget(session, 2026, hide_empty_direct=False)
    labels = [r.label for r in shown.rows]
    assert labels.count("(sans sous-catégorie)") == 2  # Revenus et Alimentation


def test_direct_row_appears_when_operations_go_straight_to_the_parent(
    session: Session, cats: Cats, sg: Account
) -> None:
    spend(session, sg, D(2026, 2, 3), -1_500, cats.alimentation)
    budget = bud.build_budget(session, 2026)
    direct = row(budget, "(sans sous-catégorie)")
    assert direct.actual[1] == 1_500
    assert row(budget, "Alimentation").actual[1] == 1_500  # le total du parent l'inclut


# --- Prévu : totaux -------------------------------------------------------------------------


def test_parent_and_section_totals_add_up(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.courses, 2026, 1, 40_000)
    bud.set_planned(session, cats.restaurant, 2026, 1, 10_000)
    bud.set_planned(session, cats.alimentation, 2026, 1, 2_000)  # budget propre du parent
    bud.set_planned(session, cats.loisirs, 2026, 1, 5_000)
    bud.set_planned(session, cats.salaire, 2026, 1, 250_000)
    budget = bud.build_budget(session, 2026)

    assert row(budget, "Alimentation").planned[0] == 52_000
    assert row(budget, "Total dépenses").planned[0] == 57_000
    assert row(budget, "Total recettes").planned[0] == 250_000
    assert row(budget, "Solde (recettes - dépenses)").planned[0] == 250_000 - 57_000
    assert row(budget, "Total dépenses").planned_total == 57_000


def test_planned_values_land_in_the_right_month(session: Session, cats: Cats) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 12, 900)
    bud.set_planned(session, cats.loisirs, 2027, 1, 111)  # une autre année : ignorée
    planned = row(bud.build_budget(session, 2026), "Loisirs").planned
    assert planned[11] == 900 and sum(planned) == 900


# --- Réalisé --------------------------------------------------------------------------------


def test_actual_expense_is_positive_and_income_is_positive(
    session: Session, cats: Cats, sg: Account
) -> None:
    spend(session, sg, D(2026, 3, 5), -4_250, cats.courses)
    spend(session, sg, D(2026, 3, 1), 250_000, cats.salaire)
    budget = bud.build_budget(session, 2026)
    assert row(budget, "Courses").actual[2] == 4_250
    assert row(budget, "Salaire").actual[2] == 250_000
    assert row(budget, "Solde (recettes - dépenses)").actual[2] == 250_000 - 4_250


def test_a_refund_reduces_the_expense(session: Session, cats: Cats, sg: Account) -> None:
    spend(session, sg, D(2026, 3, 5), -10_000, cats.courses)
    spend(session, sg, D(2026, 3, 9), 2_500, cats.courses)  # remboursement
    assert row(bud.build_budget(session, 2026), "Courses").actual[2] == 7_500


def test_actual_is_spread_over_the_months_of_the_year(
    session: Session, cats: Cats, sg: Account
) -> None:
    spend(session, sg, D(2026, 1, 31), -100, cats.loisirs)
    spend(session, sg, D(2026, 2, 1), -200, cats.loisirs)
    spend(session, sg, D(2026, 12, 31), -300, cats.loisirs)
    spend(session, sg, D(2025, 12, 31), -9_999, cats.loisirs)  # autres années : ignorées
    spend(session, sg, D(2027, 1, 1), -9_999, cats.loisirs)
    actual = row(bud.build_budget(session, 2026), "Loisirs").actual
    assert actual == (100, 200, 0, 0, 0, 0, 0, 0, 0, 0, 0, 300)


def test_future_operations_count_as_actual(session: Session, cats: Cats, sg: Account) -> None:
    """Y compris celles générées par les échéances : c'est le « prévisionnel contre réel »."""
    spend(session, sg, D(2099, 6, 1), -700, cats.loisirs)
    assert row(bud.build_budget(session, 2099), "Loisirs").actual[5] == 700


def test_transfers_are_not_budget(
    session: Session, cats: Cats, sg: Account, bourso: Account
) -> None:
    tx.create_transfer(
        session,
        TransferData(
            from_account_id=sg.id, to_account_id=bourso.id, date=D(2026, 3, 1), amount_cents=30_000
        ),
    )
    budget = bud.build_budget(session, 2026)
    assert row(budget, "Total dépenses").actual_total == 0
    assert row(budget, "Total recettes").actual_total == 0
    assert "Non catégorisé" not in [r.label for r in budget.rows]


def test_uncategorized_operations_are_shown_by_sign(
    session: Session, cats: Cats, sg: Account
) -> None:
    spend(session, sg, D(2026, 4, 2), -1_200, None)
    spend(session, sg, D(2026, 4, 3), -300, None)
    spend(session, sg, D(2026, 4, 4), 5_000, None)
    budget = bud.build_budget(session, 2026)

    labels = [
        (r.kind, r.section, r.actual[3]) for r in budget.rows if r.kind is RowKind.UNCATEGORIZED
    ]
    assert labels == [
        (RowKind.UNCATEGORIZED, INCOME, 5_000),
        (RowKind.UNCATEGORIZED, EXPENSE, 1_500),
    ]
    assert not any(r.editable for r in budget.rows if r.kind is RowKind.UNCATEGORIZED)
    assert row(budget, "Total dépenses").actual[3] == 1_500  # compté dans les totaux
    assert row(budget, "Total recettes").actual[3] == 5_000


def test_uncategorized_row_is_absent_when_everything_is_categorized(
    session: Session, cats: Cats, sg: Account
) -> None:
    spend(session, sg, D(2026, 4, 2), -1_200, cats.loisirs)
    assert "Non catégorisé" not in [r.label for r in bud.build_budget(session, 2026).rows]


# --- Écarts ---------------------------------------------------------------------------------


def test_variance_is_positive_when_it_is_good_news(
    session: Session, cats: Cats, sg: Account
) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 1, 40_000)
    spend(session, sg, D(2026, 1, 10), -45_000, cats.loisirs)  # 50 € de trop
    bud.set_planned(session, cats.salaire, 2026, 1, 250_000)
    spend(session, sg, D(2026, 1, 2), 260_000, cats.salaire)  # 100 € de plus que prévu
    budget = bud.build_budget(session, 2026)

    assert row(budget, "Loisirs").variance(0) == -5_000  # dépense : prévu - réalisé
    assert row(budget, "Salaire").variance(0) == 10_000  # recette : réalisé - prévu
    # Solde : +100 € de recettes en plus, mais 50 € de dépenses en trop : +50 € au total.
    assert row(budget, "Solde (recettes - dépenses)").variance(0) == 10_000 - 5_000
    assert row(budget, "Loisirs").variance_total == -5_000


# --- Types de catégorie ---------------------------------------------------------------------


def test_changing_the_kind_moves_the_category_and_flips_the_actual_sign(
    session: Session, cats: Cats, sg: Account
) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 1, 1_000)
    spend(session, sg, D(2026, 1, 5), 800, cats.loisirs)  # +800 : une entrée d'argent

    before = bud.build_budget(session, 2026)
    assert row(before, "Loisirs").section is EXPENSE
    assert row(before, "Loisirs").actual[0] == -800  # un remboursement qui dépasse les dépenses

    categories.set_category_kind(session, cats.loisirs, INCOME)
    after = bud.build_budget(session, 2026)
    assert row(after, "Loisirs").section is INCOME
    assert row(after, "Loisirs").actual[0] == 800
    assert row(after, "Loisirs").planned[0] == 1_000  # le prévu, positif, n'a pas changé


# --- Suppression d'une catégorie ------------------------------------------------------------


def test_deleting_a_category_removes_its_planned_amounts(session: Session, cats: Cats) -> None:
    bud.fill_planned(session, cats.loisirs, 2026, from_month=1, amount_cents=100)
    bud.set_planned(session, cats.courses, 2026, 1, 500)
    assert count_lines(session) == 13

    categories.delete_category(session, cats.loisirs)

    assert count_lines(session) == 1  # seule la ligne de « Courses » reste


def test_deleting_a_used_category_keeps_its_planned_amounts(
    session: Session, cats: Cats, sg: Account
) -> None:
    bud.set_planned(session, cats.loisirs, 2026, 1, 100)
    spend(session, sg, D(2026, 1, 5), -10, cats.loisirs)
    with pytest.raises(InvalidError):
        categories.delete_category(session, cats.loisirs)
    assert count_lines(session) == 1  # refusée : rien n'est effacé


def test_build_budget_validates_the_year(session: Session) -> None:
    with pytest.raises(InvalidError):
        bud.build_budget(session, 1990)
