import datetime as dt

from PySide6.QtCore import QModelIndex, Qt

from budget.domain.money import NBSP
from budget.services.accounts import AccountBalance
from budget.services.transactions import RegisterLine
from budget.ui.models.account_model import AccountTableModel
from budget.ui.models.register_model import (
    COL_BALANCE,
    COL_CATEGORY,
    COL_CREDIT,
    COL_DATE,
    COL_DEBIT,
    COL_PAYEE,
    RegisterTableModel,
)

TODAY = dt.date(2026, 3, 15)


def _text(model, row: int, column: int) -> str:  # type: ignore[no-untyped-def]
    return model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole)


def make_line(**overrides) -> RegisterLine:  # type: ignore[no-untyped-def]
    values = {
        "transaction_id": 1,
        "account_id": 1,
        "date": dt.date(2026, 3, 1),
        "amount_cents": -1250,
        "balance_cents": 10_000,
        "payee_name": "Carrefour",
        "category_id": None,
        "category_name": "Alimentation : Courses",
        "payment_method_id": None,
        "payment_method_name": "Carte",
        "notes": "",
        "transfer_account_id": None,
        "transfer_account_name": "",
    }
    values.update(overrides)
    return RegisterLine(**values)  # type: ignore[arg-type]


# --- Modèle des comptes ---------------------------------------------------------------------


def test_account_model_shape_and_text(qapp) -> None:  # type: ignore[no-untyped-def]
    model = AccountTableModel()
    model.set_balances(
        [
            AccountBalance(1, "SG", 123_456, 100_000),
            AccountBalance(2, "Vieux", 0, 0, closed=True),
        ]
    )
    assert model.rowCount() == 2
    assert model.columnCount() == 3
    assert _text(model, 0, 0) == "SG"
    assert _text(model, 0, 1).endswith(f",56{NBSP}€")
    assert _text(model, 1, 0) == "Vieux (clôturé)"
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Compte"


def test_account_model_row_lookup(qapp) -> None:  # type: ignore[no-untyped-def]
    model = AccountTableModel()
    model.set_balances([AccountBalance(7, "A", 0, 0), AccountBalance(9, "B", 0, 0)])
    assert model.row_of_account(9) == 1
    assert model.row_of_account(123) is None


def test_account_model_flat_table_has_no_children(qapp) -> None:  # type: ignore[no-untyped-def]
    model = AccountTableModel()
    model.set_balances([AccountBalance(1, "SG", 0, 0)])
    assert model.rowCount(model.index(0, 0)) == 0


def test_negative_balance_is_red(qapp) -> None:  # type: ignore[no-untyped-def]
    model = AccountTableModel()
    model.set_balances([AccountBalance(1, "SG", -500, 100)])
    red = model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole)
    normal = model.data(model.index(0, 2), Qt.ItemDataRole.ForegroundRole)
    assert red is not None
    assert normal is None


# --- Modèle du registre ---------------------------------------------------------------------


def test_register_debit_and_credit_columns(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    model.set_lines(
        [make_line(amount_cents=-1250), make_line(transaction_id=2, amount_cents=40_000)], TODAY
    )
    assert _text(model, 0, COL_DEBIT) == "12,50"
    assert _text(model, 0, COL_CREDIT) == ""
    assert _text(model, 1, COL_DEBIT) == ""
    assert _text(model, 1, COL_CREDIT) == "400,00"
    assert _text(model, 0, COL_DATE) == "01/03/2026"
    assert _text(model, 0, COL_CATEGORY) == "Alimentation : Courses"
    assert _text(model, 0, COL_BALANCE) == f"100,00{NBSP}€"


def test_register_labels_transfers_with_direction(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    model.set_lines(
        [
            make_line(amount_cents=-500, transfer_account_id=2, transfer_account_name="Bourso"),
            make_line(
                transaction_id=2,
                amount_cents=500,
                transfer_account_id=3,
                transfer_account_name="Livret",
            ),
        ],
        TODAY,
    )
    assert _text(model, 0, COL_PAYEE) == "Virement vers Bourso"
    assert _text(model, 1, COL_PAYEE) == "Virement depuis Livret"


def test_register_future_rows_are_greyed_and_italic(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    model.set_lines(
        [make_line(date=TODAY), make_line(transaction_id=2, date=TODAY.replace(day=16))], TODAY
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.FontRole) is None  # aujourd'hui : normal
    assert model.data(model.index(1, 0), Qt.ItemDataRole.FontRole).italic()
    assert model.data(model.index(1, 0), Qt.ItemDataRole.ForegroundRole) is not None


def test_register_lookups(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    lines = [
        make_line(transaction_id=10, date=dt.date(2026, 3, 1)),
        make_line(transaction_id=11, date=dt.date(2026, 3, 15)),
        make_line(transaction_id=12, date=dt.date(2026, 4, 1)),
    ]
    model.set_lines(lines, TODAY)
    assert model.row_of_transaction(11) == 1
    assert model.row_of_transaction(999) is None
    assert model.last_past_row() == 1  # la ligne du 15 mars est « aujourd'hui »
    assert model.line_at(2).transaction_id == 12


def test_register_all_in_the_future_has_no_past_row(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    model.set_lines([make_line(date=dt.date(2027, 1, 1))], TODAY)
    assert model.last_past_row() is None


def test_register_empty(qapp) -> None:  # type: ignore[no-untyped-def]
    model = RegisterTableModel()
    model.set_lines([], TODAY)
    assert model.rowCount() == 0
    assert model.data(QModelIndex()) is None
