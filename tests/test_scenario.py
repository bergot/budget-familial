"""Scénario de bout en bout, sur un vrai fichier SQLite, avec validation (commit)."""

import datetime as dt
from pathlib import Path

import pytest

from budget.db.base import create_db_engine, init_schema, make_session_factory
from budget.domain.errors import InvalidError
from budget.services import accounts, categories, lookups
from budget.services import transactions as tx
from budget.services.transactions import TransactionData, TransferData


def test_data_survives_commit_and_reopening(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite"
    engine = create_db_engine(path)
    init_schema(engine)
    factory = make_session_factory(engine)

    day = dt.date(2026, 3, 1)
    with factory() as session, session.begin():  # validé à la sortie du bloc
        lookups.ensure_default_payment_methods(session)
        sg = accounts.create_account(session, "SG", initial_balance_cents=200_000)
        bourso = accounts.create_account(session, "Boursorama")
        courses = categories.create_category(session, "Courses")
        carrefour = lookups.get_or_create_payee(session, "Carrefour")
        card = lookups.get_or_create_payment_method(session, "Carte")

        # Alimentation mensuelle du compte Boursorama depuis la SG.
        tx.create_transfer(
            session,
            TransferData(
                from_account_id=sg.id, to_account_id=bourso.id, date=day, amount_cents=50_000
            ),
        )
        # Achats par carte, saisis à leur date d'achat sur le compte Boursorama.
        for offset, cents in enumerate([-4_250, -1_890]):
            tx.add_transaction(
                session,
                TransactionData(
                    account_id=bourso.id,
                    date=day + dt.timedelta(days=offset + 1),
                    amount_cents=cents,
                    payee_id=carrefour.id,
                    category_id=courses.id,
                    payment_method_id=card.id,
                ),
            )

    # Nouvelle connexion, nouvelle session : on relit depuis le fichier.
    engine.dispose()
    reopened = make_session_factory(create_db_engine(path))
    with reopened() as session:
        balances = {
            b.name: b for b in accounts.account_balances(session, today=dt.date(2026, 3, 31))
        }
        assert balances["SG"].current_cents == 150_000
        assert balances["Boursorama"].current_cents == 50_000 - 4_250 - 1_890

        bourso_id = next(a.id for a in accounts.list_accounts(session) if a.name == "Boursorama")
        rows = tx.register(session, bourso_id)
        assert [r.balance_cents for r in rows] == [50_000, 45_750, 43_860]
        assert rows[1].transaction.payee.name == "Carrefour"


def test_rollback_cancels_everything(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "budget.sqlite")
    init_schema(engine)
    factory = make_session_factory(engine)

    with pytest.raises(InvalidError), factory() as session, session.begin():
        accounts.create_account(session, "SG")
        accounts.create_account(session, "")  # lève InvalidError : tout est annulé

    with factory() as session:
        assert accounts.list_accounts(session, include_closed=True) == []
