"""Régénère les captures d'écran du README avec des données de démonstration fixes.

    uv run python packaging/make_screenshots.py

Les captures sont écrites dans `docs/`. Les données sont fictives et la date est fixée, pour que
les images soient identiques d'une exécution à l'autre.
"""

import datetime as dt
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from budget.db.base import create_db_engine, make_session_factory, unit_of_work  # noqa: E402
from budget.db.migrate import upgrade_to_head  # noqa: E402
from budget.domain.enums import CategoryKind, Frequency  # noqa: E402
from budget.services import accounts, categories, lookups  # noqa: E402
from budget.services import budgets as bud  # noqa: E402
from budget.services import reconciliation as rec  # noqa: E402
from budget.services import schedules as sch  # noqa: E402
from budget.services import transactions as tx  # noqa: E402
from budget.services.transactions import TransactionData, TransferData  # noqa: E402
from budget.settings import Settings  # noqa: E402
from budget.ui.dialogs.budget_dialog import BudgetDialog  # noqa: E402
from budget.ui.dialogs.preferences_dialog import PreferencesDialog  # noqa: E402
from budget.ui.dialogs.reconciliation_dialog import ReconciliationDialog  # noqa: E402
from budget.ui.dialogs.schedules_dialog import SchedulesDialog  # noqa: E402
from budget.ui.i18n import install_french  # noqa: E402
from budget.ui.icons import load_app_icon  # noqa: E402
from budget.ui.main_window import MainWindow  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"
TODAY = dt.date(2026, 7, 14)
D = dt.date


def build_demo(factory) -> dict[str, int]:  # type: ignore[no-untyped-def]
    random.seed(3)
    ids: dict[str, int] = {}
    with unit_of_work(factory) as s:
        lookups.ensure_default_payment_methods(s)
        card = lookups.get_or_create_payment_method(s, "Carte").id
        direct_debit = lookups.get_or_create_payment_method(s, "Prélèvement").id
        transfer_method = lookups.get_or_create_payment_method(s, "Virement").id
        sg = accounts.create_account(
            s, "SG courant", bank="Société Générale", initial_balance_cents=300_000
        ).id
        bourso = accounts.create_account(
            s, "Boursorama", bank="Boursorama", initial_balance_cents=20_000
        ).id
        accounts.create_account(
            s, "Livret A", bank="Société Générale", initial_balance_cents=1_200_000
        )
        ids.update(sg=sg, bourso=bourso)

        def category(name: str, kind=CategoryKind.EXPENSE, parent=None) -> int:  # type: ignore[no-untyped-def]
            return categories.create_category(s, name, parent_id=parent, kind=kind).id

        revenus = category("Revenus", CategoryKind.INCOME)
        salaire, allocations = (
            category("Salaire", parent=revenus),
            category("Allocations", parent=revenus),
        )
        logement = category("Logement")
        loyer, electricite = (
            category("Loyer", parent=logement),
            category("Électricité", parent=logement),
        )
        alimentation = category("Alimentation")
        courses, restaurant = (
            category("Courses", parent=alimentation),
            category("Restaurant", parent=alimentation),
        )
        loisirs, transport = category("Loisirs"), category("Transport")

        planned = {
            salaire: 245_000,
            allocations: 18_000,
            loyer: 65_000,
            electricite: 8_000,
            courses: 45_000,
            restaurant: 12_000,
            loisirs: 15_000,
            transport: 9_000,
        }
        for category_id, amount in planned.items():
            bud.fill_planned(s, category_id, 2026, from_month=1, amount_cents=amount)
        bud.set_planned(s, loisirs, 2026, 7, 40_000)
        bud.set_planned(s, loisirs, 2026, 8, 40_000)

        def operation(account, day, cents, payee, category_id, method):  # type: ignore[no-untyped-def]
            payee_id = lookups.get_or_create_payee(s, payee).id if payee else None
            tx.add_transaction(
                s,
                TransactionData(
                    account_id=account,
                    date=day,
                    amount_cents=cents,
                    payee_id=payee_id,
                    category_id=category_id,
                    payment_method_id=method,
                ),
            )

        for month in range(1, 8):
            operation(sg, D(2026, month, 2), 245_000, "Employeur", salaire, transfer_method)
            operation(sg, D(2026, month, 5), -65_000, "Agence Dupont", loyer, direct_debit)
            operation(
                sg, D(2026, month, 8), -random.randint(6500, 9500), "EDF", electricite, direct_debit
            )
            tx.create_transfer(
                s,
                TransferData(
                    from_account_id=sg,
                    to_account_id=bourso,
                    date=D(2026, month, 3),
                    amount_cents=40_000,
                    payment_method_id=transfer_method,
                    notes="Alimentation mensuelle",
                ),
            )
            for day in (6, 13, 20, 27):
                operation(
                    bourso,
                    D(2026, month, day),
                    -random.randint(6000, 12000),
                    "Carrefour",
                    courses,
                    card,
                )
            operation(
                bourso,
                D(2026, month, 15),
                -random.randint(3000, 8000),
                "Restaurant Le Quai",
                restaurant,
                card,
            )
        operation(bourso, D(2026, 7, 20), -5_500, "Pizzeria Roma", restaurant, card)  # à venir

        # Un rapprochement validé (juin) et un en cours (juillet).
        june = [line for line in rec.pointable_lines(s, bourso) if line.date <= D(2026, 6, 30)]
        for line in june:
            rec.set_pointed(s, line.transaction_id, pointed=True)
        state = rec.reconciliation_state(s, bourso)
        rec.complete_reconciliation(
            s,
            bourso,
            statement_date=D(2026, 6, 30),
            statement_balance_cents=state.reconciled_balance_cents + state.pointed_total_cents,
        )
        recent = [line for line in rec.pointable_lines(s, bourso) if line.date <= D(2026, 7, 10)]
        for line in recent[:3]:
            rec.set_pointed(s, line.transaction_id, pointed=True)

        sch.create_schedule(
            s,
            sch.ScheduleData(
                sg,
                -65_000,
                Frequency.MONTHLY,
                D(2026, 8, 5),
                payee_id=lookups.get_or_create_payee(s, "Agence Dupont").id,
                category_id=loyer,
                payment_method_id=direct_debit,
                notes="Loyer",
            ),
        )
        sch.create_schedule(
            s,
            sch.ScheduleData(
                sg,
                40_000,
                Frequency.MONTHLY,
                D(2026, 8, 3),
                transfer_account_id=bourso,
                payment_method_id=transfer_method,
                notes="Alimentation Boursorama",
            ),
        )
        sch.create_schedule(
            s,
            sch.ScheduleData(
                sg,
                -48_000,
                Frequency.YEARLY,
                D(2026, 12, 10),
                payee_id=lookups.get_or_create_payee(s, "MAIF").id,
                category_id=category("Assurances"),
                payment_method_id=direct_debit,
                notes="Assurance habitation",
            ),
        )
        sch.generate_due_transactions(s, today=TODAY)
    return ids


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "demo.sqlite"
        engine = create_db_engine(database)
        upgrade_to_head(engine)
        factory = make_session_factory(engine)
        ids = build_demo(factory)

        app = QApplication(sys.argv)
        app.setWindowIcon(load_app_icon())
        install_french(app)

        window = MainWindow(factory, today=lambda: TODAY, database=database)
        window.resize(1250, 640)
        window.show()
        app.processEvents()
        window.refresh(select_account_id=ids["bourso"])
        app.processEvents()
        window.grab().save(str(DOCS / "capture-registre.png"))

        dialog = ReconciliationDialog(factory, ids["bourso"], today=D(2026, 7, 10))
        dialog.show()
        dialog._balance.setText("")
        app.processEvents()
        dialog.grab().save(str(DOCS / "capture-rapprochement.png"))

        schedules = SchedulesDialog(factory, today=TODAY)
        schedules.resize(960, 330)
        schedules.show()
        app.processEvents()
        schedules.grab().save(str(DOCS / "capture-echeances.png"))

        budget = BudgetDialog(factory, today=TODAY)
        budget.show()
        app.processEvents()
        budget.select_cell(budget.row_of("Courses"), 8)
        budget.grab().save(str(DOCS / "capture-budget.png"))

        # Un chemin d'exemple : on ne veut pas d'un dossier temporaire dans une capture publique.
        example = Path("/home/utilisateur/.local/share/budget-familial/budget.sqlite")
        preferences = PreferencesDialog(Settings(), database=example)
        preferences.show()
        app.processEvents()
        preferences.grab().save(str(DOCS / "capture-preferences.png"))

        engine.dispose()
    print(f"Captures écrites dans {DOCS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
