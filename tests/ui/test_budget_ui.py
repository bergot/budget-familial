"""Tests de la grille du budget : modèle Qt, fenêtre, saisie à la façon d'un tableur."""

import datetime as dt

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemDelegate, QDialog, QLineEdit
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import unit_of_work
from budget.domain.enums import CategoryKind
from budget.domain.money import NBSP
from budget.services import accounts, categories
from budget.services import budgets as bud
from budget.services import transactions as tx
from budget.services.budgets import Budget
from budget.services.transactions import TransactionData
from budget.ui.dialogs import budget_dialog, common
from budget.ui.dialogs.budget_dialog import BudgetDialog
from budget.ui.main_window import MainWindow
from budget.ui.models.budget_model import (
    COL_LABEL,
    COL_TOTAL,
    HEADERS,
    BudgetTableModel,
    ViewMode,
)
from tests.ui.conftest import TODAY  # 15 mars 2026
from tests.ui.helpers import answer_next_dialog

Factory = sessionmaker[Session]
EDIT, DISPLAY = Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole
EUR = NBSP  # sans objet ici : les montants de la grille s'affichent sans symbole


class Ids:
    """Identifiants des catégories de test."""

    salaire: int
    courses: int
    restaurant: int
    alimentation: int
    loisirs: int


@pytest.fixture
def ids(factory: Factory) -> Ids:
    ids = Ids()
    with unit_of_work(factory) as session:
        revenus = categories.create_category(session, "Revenus", kind=CategoryKind.INCOME)
        ids.salaire = categories.create_category(session, "Salaire", parent_id=revenus.id).id
        alimentation = categories.create_category(session, "Alimentation")
        ids.alimentation = alimentation.id
        ids.courses = categories.create_category(session, "Courses", parent_id=alimentation.id).id
        ids.restaurant = categories.create_category(
            session, "Restaurant", parent_id=alimentation.id
        ).id
        ids.loisirs = categories.create_category(session, "Loisirs").id
    return ids


def add_operation(factory: Factory, day: dt.date, cents: int, category_id: int | None) -> None:
    with unit_of_work(factory) as session:
        account = accounts.list_accounts(session)
        account_id = account[0].id if account else accounts.create_account(session, "SG").id
        tx.add_transaction(
            session,
            TransactionData(
                account_id=account_id, date=day, amount_cents=cents, category_id=category_id
            ),
        )


def planned_in_db(factory: Factory, category_id: int, year: int = 2026) -> tuple[int, ...]:
    with factory() as session:
        budget = bud.build_budget(session, year, hide_empty_direct=False)
    row = next(r for r in budget.rows if r.category_id == category_id and r.editable)
    return row.planned


# --- Modèle ---------------------------------------------------------------------------------


def make_budget(factory: Factory, year: int = 2026) -> Budget:
    with factory() as session:
        return bud.build_budget(session, year)


def make_model(
    factory: Factory, calls: list | None = None, accept: bool = True
) -> BudgetTableModel:  # type: ignore[type-arg]
    def on_edit(category_id: int, month: int, text: str) -> bool:
        if calls is not None:
            calls.append((category_id, month, text))
        return accept

    model = BudgetTableModel(on_edit)
    model.set_budget(make_budget(factory))
    return model


def cell(model: BudgetTableModel, label: str, column: int, role=DISPLAY):  # type: ignore[no-untyped-def]
    row = next(r for r in range(model.rowCount()) if model.row_at(r).label == label)
    return model.data(model.index(row, column), role)


def test_model_shape_and_headers(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory)
    assert model.columnCount() == 14 == len(HEADERS)
    assert [model.headerData(c, Qt.Orientation.Horizontal) for c in (0, 1, 12, 13)] == [
        "Catégorie",
        "Janv.",
        "Déc.",
        "Total",
    ]
    assert [model.row_at(r).label for r in range(model.rowCount())] == [
        "Recettes",
        "Revenus",
        "Salaire",
        "Total recettes",
        "Dépenses",
        "Alimentation",
        "Courses",
        "Restaurant",
        "Loisirs",
        "Total dépenses",
        "Solde (recettes - dépenses)",
    ]


def test_model_display_indents_children_and_blanks_zeros(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.courses, 2026, 3, 40_050)
    model = make_model(factory)

    assert cell(model, "Courses", COL_LABEL).startswith("   ")  # sous-catégorie en retrait
    assert not cell(model, "Loisirs", COL_LABEL).startswith(" ")
    assert cell(model, "Courses", 3) == "400,50"  # mars
    assert cell(model, "Courses", 4) == ""  # zéro : case vide, comme dans un tableur
    assert cell(model, "Courses", COL_TOTAL) == "400,50"
    assert cell(model, "Recettes", 3) is None  # un titre de section n'a pas de montants


def test_model_modes(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 1, 10_000)
    add_operation(factory, dt.date(2026, 1, 9), -12_500, ids.loisirs)
    model = make_model(factory)

    assert cell(model, "Loisirs", 1) == "100,00"  # prévu
    model.set_mode(ViewMode.ACTUAL)
    assert cell(model, "Loisirs", 1) == "125,00"  # réalisé : une dépense compte positivement
    model.set_mode(ViewMode.VARIANCE)
    assert cell(model, "Loisirs", 1) == "-25,00"  # prévu - réalisé : 25 € de trop


def test_variance_is_blank_for_months_to_come(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.fill_planned(session, ids.loisirs, 2026, from_month=1, amount_cents=10_000)
    model = make_model(factory)
    model.set_mode(ViewMode.VARIANCE)
    model.set_comparable_months(3)  # nous sommes en mars

    assert [cell(model, "Loisirs", c) for c in (1, 2, 3)] == ["100,00"] * 3  # rien dépensé
    assert [cell(model, "Loisirs", c) for c in (4, 5, 12)] == ["", "", ""]  # avril... : vide
    assert cell(model, "Loisirs", COL_TOTAL) == "300,00"  # total limité aux 3 mois écoulés

    model.set_comparable_months(0)  # année à venir : aucun écart
    assert cell(model, "Loisirs", COL_TOTAL) == ""
    model.set_comparable_months(12)
    assert cell(model, "Loisirs", COL_TOTAL) == "1 200,00".replace(" ", "\u202f")


def test_model_editability(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory)
    row_of = {model.row_at(r).label: r for r in range(model.rowCount())}

    def editable(label: str, column: int) -> bool:
        flags = model.flags(model.index(row_of[label], column))
        return bool(flags & Qt.ItemFlag.ItemIsEditable)

    assert editable("Courses", 3) and editable("Salaire", 1) and editable("Loisirs", 12)
    assert not editable("Courses", COL_LABEL)  # le nom n'est pas modifiable
    assert not editable("Courses", COL_TOTAL)  # ni le total
    assert not editable("Alimentation", 3)  # catégorie parente : total calculé
    assert not editable("Total dépenses", 3) and not editable("Recettes", 3)

    model.set_mode(ViewMode.ACTUAL)
    assert not editable("Courses", 3)  # seul le prévu se saisit
    model.set_mode(ViewMode.VARIANCE)
    assert not editable("Courses", 3)


def test_model_edit_text_and_set_data(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 2, 7_550)
    calls: list = []  # type: ignore[type-arg]
    model = make_model(factory, calls)
    row = next(r for r in range(model.rowCount()) if model.row_at(r).label == "Loisirs")

    assert model.data(model.index(row, 2), EDIT) == "75,50"  # texte proposé à l'édition
    assert model.data(model.index(row, 1), EDIT) == ""  # case vide
    assert model.setData(model.index(row, 5), " 120 ", EDIT) is True
    assert calls == [(ids.loisirs, 5, " 120 ")]  # le modèle transmet tel quel, la fenêtre analyse

    assert model.setData(model.index(row, COL_LABEL), "x", EDIT) is False  # colonne du nom
    assert model.setData(model.index(row, 5), "x", Qt.ItemDataRole.DisplayRole) is False
    parent_row = next(r for r in range(model.rowCount()) if model.row_at(r).label == "Alimentation")
    assert model.setData(model.index(parent_row, 5), "1", EDIT) is False  # ligne calculée
    assert len(calls) == 1


def test_a_refused_edit_is_reported_to_qt(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory, accept=False)
    row = next(r for r in range(model.rowCount()) if model.row_at(r).label == "Loisirs")
    assert model.setData(model.index(row, 1), "10", EDIT) is False


def test_set_budget_updates_values_without_resetting(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory)
    resets: list[int] = []
    changes: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))
    model.dataChanged.connect(lambda *_: changes.append(1))

    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 1, 500)
    model.set_budget(make_budget(factory))

    assert resets == [] and changes  # même structure : mise à jour sur place
    assert cell(model, "Loisirs", 1) == "5,00"


def test_set_budget_resets_when_the_structure_changes(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory)
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))
    with unit_of_work(factory) as session:
        categories.create_category(session, "Voyages")
    model.set_budget(make_budget(factory))
    assert resets == [1]


def test_model_colors(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 1, 10_000)
        bud.set_planned(session, ids.loisirs, 2026, 2, 10_000)
    add_operation(factory, dt.date(2026, 1, 5), -15_000, ids.loisirs)  # dépassement
    add_operation(factory, dt.date(2026, 2, 5), -5_000, ids.loisirs)  # économie
    model = make_model(factory)
    model.set_mode(ViewMode.VARIANCE)

    red = cell(model, "Loisirs", 1, Qt.ItemDataRole.ForegroundRole)
    green = cell(model, "Loisirs", 2, Qt.ItemDataRole.ForegroundRole)
    assert red is not None and green is not None and red != green
    assert cell(model, "Loisirs", 3, Qt.ItemDataRole.ForegroundRole) is None  # écart nul

    model.set_mode(ViewMode.PLANNED)
    assert (
        cell(model, "Solde (recettes - dépenses)", 1, Qt.ItemDataRole.ForegroundRole) is not None
    )  # solde < 0
    assert cell(model, "Loisirs", 1, Qt.ItemDataRole.ForegroundRole) is None


def test_model_fonts_and_background(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    model = make_model(factory)
    font = lambda label, col=1: cell(model, label, col, Qt.ItemDataRole.FontRole)  # noqa: E731
    background = lambda label: cell(model, label, 1, Qt.ItemDataRole.BackgroundRole)  # noqa: E731
    assert font("Alimentation").bold() and font("Total dépenses").bold()
    assert font("Courses") is None and font("Courses", COL_TOTAL).bold()
    assert background("Total dépenses") is not None and background("Courses") is None


# --- Fenêtre --------------------------------------------------------------------------------


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    record = lambda _parent, error, title="Erreur": messages.append(str(error))  # noqa: E731
    monkeypatch.setattr(budget_dialog, "show_error", record)
    monkeypatch.setattr(common, "show_error", record)
    return messages


def row_values(dialog: BudgetDialog, label: str, role=DISPLAY) -> list[str]:  # type: ignore[no-untyped-def]
    row = dialog.row_of(label)
    return [dialog._model.data(dialog._model.index(row, c), role) for c in range(1, 14)]


def test_dialog_opens_on_the_current_year(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    assert dialog.year() == 2026
    assert dialog._model.rowCount() > 0
    assert dialog._mode.currentText() == "Prévu (saisie)"
    assert dialog._hide_empty.isChecked()
    # Les titres de section occupent toute la largeur.
    assert dialog._view.columnSpan(dialog.row_of("Recettes"), 0) == 14


def test_typing_an_amount_saves_it_and_updates_the_totals(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Courses")

    assert dialog._model.setData(dialog._model.index(row, 3), "400,50", EDIT) is True

    assert planned_in_db(factory, ids.courses)[2] == 40_050
    assert row_values(dialog, "Courses")[2] == "400,50"
    # Le total du parent et celui de la section se mettent à jour tout de suite.
    assert row_values(dialog, "Alimentation")[2] == "400,50"
    assert row_values(dialog, "Total dépenses")[2] == "400,50"
    assert row_values(dialog, "Solde (recettes - dépenses)")[2] == "-400,50"
    assert row_values(dialog, "Courses")[12] == "400,50"  # colonne Total


def test_clearing_a_cell_removes_the_amount(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 3, 9_000)
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Loisirs")

    assert dialog._model.setData(dialog._model.index(row, 3), "   ", EDIT) is True

    assert planned_in_db(factory, ids.loisirs)[2] == 0
    assert row_values(dialog, "Loisirs")[2] == ""


def test_invalid_text_is_refused_with_a_message(
    qapp, factory: Factory, ids: Ids, errors: list[str]
) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Loisirs")
    for text in ("abc", "12,345", "1,2,3"):
        assert dialog._model.setData(dialog._model.index(row, 1), text, EDIT) is False
    assert len(errors) == 3 and "pas valide" in errors[0]
    assert planned_in_db(factory, ids.loisirs) == (0,) * 12


def test_negative_amount_is_refused_by_the_service(
    qapp, factory: Factory, ids: Ids, errors: list[str]
) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Loisirs")
    assert dialog._model.setData(dialog._model.index(row, 1), "-50", EDIT) is False
    assert "négatif" in errors[0]
    assert planned_in_db(factory, ids.loisirs) == (0,) * 12


def test_changing_the_year(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2027, 6, 3_000)
    dialog = BudgetDialog(factory, today=TODAY)
    assert row_values(dialog, "Loisirs")[5] == ""

    dialog._year.setValue(2027)

    assert dialog.year() == 2027
    assert row_values(dialog, "Loisirs")[5] == "30,00"
    assert (dialog._year.minimum(), dialog._year.maximum()) == (2000, 2100)


def test_actual_mode_shows_operations_and_disables_filling(
    qapp, factory: Factory, ids: Ids
) -> None:  # type: ignore[no-untyped-def]
    add_operation(factory, dt.date(2026, 2, 3), -4_250, ids.courses)
    add_operation(factory, dt.date(2026, 2, 1), 250_000, ids.salaire)
    dialog = BudgetDialog(factory, today=TODAY)
    dialog.select_cell(dialog.row_of("Courses"), 2)
    assert dialog._fill_right.isEnabled()

    dialog._mode.setCurrentIndex(1)  # Réalisé

    assert dialog._model.mode is ViewMode.ACTUAL
    assert row_values(dialog, "Courses")[1] == "42,50"
    assert row_values(dialog, "Salaire")[1].replace("\u202f", " ") == "2 500,00"
    assert not dialog._fill_right.isEnabled() and not dialog._copy_previous.isEnabled()


def test_variance_mode_leaves_the_months_to_come_empty(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.fill_planned(session, ids.loisirs, 2026, from_month=1, amount_cents=10_000)
    dialog = BudgetDialog(factory, today=TODAY)  # mars 2026

    dialog._mode.setCurrentIndex(2)

    values = row_values(dialog, "Loisirs")
    assert values[:3] == ["100,00"] * 3 and set(values[3:12]) == {""}  # avril à décembre : vides
    dialog._year.setValue(2025)  # année passée : les 12 mois sont comparés (prévu nul : écart nul)
    assert dialog._model._comparable == 12
    dialog._year.setValue(2027)  # année à venir : aucun écart
    assert set(row_values(dialog, "Loisirs")) == {""}


def test_fill_to_the_right(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.loisirs, 2026, 4, 15_000)
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Loisirs")
    assert not dialog._fill_right.isEnabled()  # rien de sélectionné

    dialog.select_cell(row, 4)  # avril
    assert dialog._fill_right.isEnabled()
    dialog._fill_right.click()

    assert planned_in_db(factory, ids.loisirs) == (0, 0, 0, *([15_000] * 9))
    assert row_values(dialog, "Loisirs")[11] == "150,00"
    assert "Avr." in dialog._status.text() and "décembre" in dialog._status.text()


def test_fill_right_is_unavailable_on_calculated_rows(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    dialog.select_cell(dialog.row_of("Alimentation"), 3)
    assert not dialog._fill_right.isEnabled()
    dialog.select_cell(dialog.row_of("Total dépenses"), 3)
    assert not dialog._fill_right.isEnabled()


def test_copy_the_previous_year(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    with unit_of_work(factory) as session:
        bud.fill_planned(session, ids.loisirs, 2025, from_month=1, amount_cents=8_000)
        bud.set_planned(session, ids.loisirs, 2026, 2, 999)  # déjà saisi : sera conservé
    dialog = BudgetDialog(factory, today=TODAY)

    dialog._copy_previous.click()

    planned = planned_in_db(factory, ids.loisirs)
    assert planned[1] == 999 and planned[0] == planned[2] == 8_000
    assert dialog._status.text() == "11 montants repris de 2025."
    assert row_values(dialog, "Loisirs")[0] == "80,00"


def test_copy_with_nothing_to_copy(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    dialog._copy_previous.click()
    assert dialog._status.text() == "0 montant repris de 2025."


def test_copy_before_the_first_supported_year_shows_an_error(
    qapp, factory: Factory, ids: Ids, errors: list[str]
) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=dt.date(2000, 6, 1))
    dialog._copy_previous.click()
    assert errors and "année" in errors[0]


def test_empty_direct_rows_can_be_shown_and_hidden(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    labels = lambda: [  # noqa: E731
        dialog._model.row_at(r).label for r in range(dialog._model.rowCount())
    ]
    assert "(sans sous-catégorie)" not in labels()

    dialog._hide_empty.setChecked(False)
    assert labels().count("(sans sous-catégorie)") == 2

    dialog._hide_empty.setChecked(True)
    assert "(sans sous-catégorie)" not in labels()


def test_a_row_that_becomes_empty_disappears_after_the_edit(
    qapp, factory: Factory, ids: Ids
) -> None:  # type: ignore[no-untyped-def]
    """Effacer le seul montant d'une ligne « sans sous-catégorie » la masque, mais pas en plein
    milieu de la validation de la cellule : la remise à jour est différée."""
    with unit_of_work(factory) as session:
        bud.set_planned(session, ids.alimentation, 2026, 1, 5_000)
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("(sans sous-catégorie)")

    assert dialog._model.setData(dialog._model.index(row, 1), "0", EDIT) is True
    assert dialog._model.row_at(row).label == "(sans sous-catégorie)"  # encore là, vidée
    qapp.processEvents()  # Qt a fini de valider : la remise à jour différée s'exécute

    with pytest.raises(KeyError):
        dialog.row_of("(sans sous-catégorie)")


def test_enter_moves_down_like_a_spreadsheet(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    row = dialog.row_of("Courses")
    dialog.select_cell(row, 3)

    dialog._view.closeEditor(QLineEdit(), QAbstractItemDelegate.EndEditHint.NoHint)  # Entrée
    assert dialog.current_cell().row() == row + 1 and dialog.current_cell().column() == 3

    dialog._view.closeEditor(
        QLineEdit(), QAbstractItemDelegate.EndEditHint.RevertModelCache
    )  # Échap
    assert dialog.current_cell().row() == row + 1  # inchangé


def test_enter_on_the_last_row_stays_put(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    last = dialog._model.rowCount() - 1
    dialog.select_cell(last, 3)
    dialog._view.closeEditor(QLineEdit(), QAbstractItemDelegate.EndEditHint.NoHint)
    assert dialog.current_cell().row() == last


def test_reload_keeps_the_selected_cell(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    dialog = BudgetDialog(factory, today=TODAY)
    dialog.select_cell(dialog.row_of("Courses"), 7)
    dialog._hide_empty.setChecked(False)  # remise à zéro complète du modèle
    assert dialog.current_cell().column() == 7


# --- Fenêtre principale ---------------------------------------------------------------------


def test_budget_menu_opens_the_grid(qapp, factory: Factory, ids: Ids) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(factory, today=lambda: TODAY)
    window.show()
    seen: list[int] = []

    def inspect(dialog: QDialog) -> None:
        assert isinstance(dialog, BudgetDialog)
        seen.append(dialog.year())
        dialog.accept()

    answer_next_dialog(inspect)
    window.act_budget.trigger()

    assert seen == [2026]
    assert window.act_budget.shortcut().toString() == "Ctrl+B"
    window.close()
