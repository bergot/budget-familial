"""Fenêtre principale : liste des comptes à gauche, registre du compte choisi à droite."""

import datetime as dt
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget import __version__
from budget.db.base import unit_of_work
from budget.domain.enums import ReconciliationStatus
from budget.domain.errors import BudgetError
from budget.domain.money import format_cents
from budget.services import accounts, lookups
from budget.services import reconciliation as rec
from budget.services import transactions as tx
from budget.services.choices import load_choices
from budget.services.transactions import RegisterLine, TransactionData
from budget.ui.account_list import AccountList
from budget.ui.dialogs.account_dialog import AccountDialog, AccountInput
from budget.ui.dialogs.categories_dialog import CategoriesDialog
from budget.ui.dialogs.common import confirm, show_error
from budget.ui.dialogs.reconciliation_dialog import ReconciliationDialog
from budget.ui.dialogs.transaction_dialog import TransactionDialog, TransactionInput
from budget.ui.dialogs.transfer_dialog import TransferDialog
from budget.ui.register_view import RegisterView


class MainWindow(QMainWindow):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        super().__init__()
        self._factory = session_factory
        self._today = today  # injectable : les tests imposent une date fixe
        self._show_closed = False

        self.setWindowTitle("Budget familial")
        self.resize(1250, 700)

        self._accounts = AccountList()
        self._register = RegisterView()
        self._title = QLabel()
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.25)
        self._title.setFont(title_font)
        self._subtitle = QLabel()  # état du rapprochement du compte
        self._has_reconciliation = False

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(self._title)
        right_layout.addWidget(self._subtitle)
        right_layout.addWidget(self._register, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._accounts)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 830])
        self.setCentralWidget(splitter)

        self._create_actions()
        self._create_menus()

        self._accounts.selection_changed.connect(self._on_account_selected)
        self._register.selection_changed.connect(self._update_actions)
        self._register.activated.connect(self._on_edit_transaction)

        self.refresh()

    # --- Actions, menus -------------------------------------------------------------------

    def _make_action(
        self,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _create_actions(self) -> None:
        self.act_quit = self._make_action("&Quitter", self.close, QKeySequence.StandardKey.Quit)
        self.act_new_account = self._make_action("&Nouveau compte…", self._on_new_account)
        self.act_edit_account = self._make_action("&Modifier le compte…", self._on_edit_account)
        self.act_toggle_closed = self._make_action("&Clôturer le compte", self._on_toggle_closed)
        self.act_show_closed = QAction("Afficher les comptes c&lôturés", self)
        self.act_show_closed.setCheckable(True)
        self.act_show_closed.toggled.connect(self._on_show_closed)

        self.act_new_transaction = self._make_action(
            "&Nouvelle opération…", self._on_new_transaction, "Ctrl+N"
        )
        self.act_new_transfer = self._make_action(
            "Nouveau &virement…", self._on_new_transfer, "Ctrl+T"
        )
        self.act_edit_transaction = self._make_action(
            "&Modifier l'opération…", self._on_edit_transaction, "Ctrl+E"
        )
        self.act_delete_transaction = self._make_action(
            "&Supprimer l'opération…", self._on_delete_transaction, "Del"
        )

        self.act_reconcile = self._make_action(
            "&Rapprocher le compte…", self._on_reconcile, "Ctrl+R"
        )
        self.act_undo_reconcile = self._make_action(
            "&Annuler le dernier rapprochement…", self._on_undo_reconcile
        )

        self.act_categories = self._make_action("&Catégories…", self._on_categories)
        self.act_about = self._make_action("À &propos", self._on_about)

    def _create_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&Fichier")
        file_menu.addAction(self.act_quit)

        account_menu = bar.addMenu("&Comptes")
        account_menu.addAction(self.act_new_account)
        account_menu.addAction(self.act_edit_account)
        account_menu.addAction(self.act_toggle_closed)
        account_menu.addSeparator()
        account_menu.addAction(self.act_show_closed)

        operation_menu = bar.addMenu("&Opérations")
        operation_menu.addAction(self.act_new_transaction)
        operation_menu.addAction(self.act_new_transfer)
        operation_menu.addSeparator()
        operation_menu.addAction(self.act_edit_transaction)
        operation_menu.addAction(self.act_delete_transaction)

        reconcile_menu = bar.addMenu("&Rapprochement")
        reconcile_menu.addAction(self.act_reconcile)
        reconcile_menu.addAction(self.act_undo_reconcile)

        settings_menu = bar.addMenu("&Données")
        settings_menu.addAction(self.act_categories)

        help_menu = bar.addMenu("&Aide")
        help_menu.addAction(self.act_about)

        toolbar = self.addToolBar("Opérations")
        toolbar.setMovable(False)
        toolbar.addAction(self.act_new_transaction)
        toolbar.addAction(self.act_new_transfer)
        toolbar.addAction(self.act_edit_transaction)
        toolbar.addAction(self.act_delete_transaction)
        toolbar.addSeparator()
        toolbar.addAction(self.act_reconcile)

    def _update_actions(self) -> None:
        balance = self._accounts.selected_balance()
        line = self._register.selected_line()
        has_account = balance is not None
        is_closed = balance is not None and balance.closed
        can_edit = has_account and not is_closed
        # Une opération rapprochée est figée : on ne la modifie ni ne la supprime.
        line_is_free = line is not None and line.status is not ReconciliationStatus.RECONCILED

        self.act_edit_account.setEnabled(has_account)
        self.act_toggle_closed.setEnabled(has_account)
        self.act_toggle_closed.setText("&Rouvrir le compte" if is_closed else "&Clôturer le compte")
        self.act_new_transaction.setEnabled(can_edit)
        self.act_new_transfer.setEnabled(can_edit)
        self.act_edit_transaction.setEnabled(can_edit and line_is_free)
        self.act_delete_transaction.setEnabled(has_account and line_is_free)
        self.act_reconcile.setEnabled(has_account)
        self.act_undo_reconcile.setEnabled(has_account and self._has_reconciliation)

    # --- Chargement des données ---------------------------------------------------------

    def refresh(
        self,
        *,
        select_account_id: int | None = None,
        select_transaction_id: int | None = None,
    ) -> None:
        """Recharge la liste des comptes puis le registre du compte sélectionné."""
        keep = select_account_id or self._accounts.selected_account_id()
        with self._factory() as session:
            balances = accounts.account_balances(
                session, today=self._today(), include_closed=self._show_closed
            )
        self._accounts.set_balances(balances, keep)
        self._reload_register(select_transaction_id)

    def _reload_register(self, select_transaction_id: int | None = None) -> None:
        account_id = self._accounts.selected_account_id()
        if account_id is None:
            self._title.setText("Aucun compte : créez-en un via le menu Comptes")
            self._subtitle.setText("")
            self._has_reconciliation = False
            self._register.set_lines([], self._today())
        else:
            with self._factory() as session:
                account = accounts.get_account(session, account_id)
                has_other_bank = account.bank and account.bank != account.name
                title = account.name + (f"  ({account.bank})" if has_other_bank else "")
                lines = tx.register_lines(session, account_id)
                last = rec.last_reconciliation(session, account_id)
                state = rec.reconciliation_state(session, account_id)
            self._title.setText(title)
            self._has_reconciliation = last is not None
            self._subtitle.setText(self._reconciliation_text(last, state))
            self._register.set_lines(lines, self._today(), select_transaction_id)
        self._update_actions()

    @staticmethod
    def _reconciliation_text(
        last: rec.ReconciliationSummary | None, state: rec.ReconciliationState
    ) -> str:
        if last is None:
            text = "Jamais rapproché"
        else:
            text = (
                f"Rapproché au {last.statement_date.strftime('%d/%m/%Y')} : "
                f"{format_cents(last.statement_balance_cents)}"
            )
        if state.pointed_count:
            plural = "s" if state.pointed_count > 1 else ""
            text += f"  •  {state.pointed_count} opération{plural} pointée{plural} en cours"
        return text

    def _on_account_selected(self) -> None:
        self._reload_register()

    # --- Exécution protégée ---------------------------------------------------------------

    def _run[T](self, action: Callable[[Session], T]) -> T | None:
        """Exécute `action` dans une transaction ; affiche l'erreur métier le cas échéant."""
        try:
            with unit_of_work(self._factory) as session:
                return action(session)
        except BudgetError as error:
            show_error(self, error)
            return None

    def _run_void(self, action: Callable[[Session], object]) -> bool:
        def wrapper(session: Session) -> bool:
            action(session)
            return True

        return self._run(wrapper) is True

    # --- Comptes --------------------------------------------------------------------------

    def _on_new_account(self) -> None:
        dialog = AccountDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        account_id = self._run(
            lambda session: (
                accounts.create_account(
                    session,
                    data.name,
                    bank=data.bank,
                    initial_balance_cents=data.initial_balance_cents,
                ).id
            )
        )
        if account_id is not None:
            self.refresh(select_account_id=account_id)

    def _on_edit_account(self) -> None:
        account_id = self._accounts.selected_account_id()
        if account_id is None:
            return
        with self._factory() as session:
            account = accounts.get_account(session, account_id)
            initial = AccountInput(account.name, account.bank, account.initial_balance_cents)
        dialog = AccountDialog(initial=initial, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        if self._run_void(
            lambda session: accounts.update_account(
                session,
                account_id,
                name=data.name,
                bank=data.bank,
                initial_balance_cents=data.initial_balance_cents,
            )
        ):
            self.refresh(select_account_id=account_id)

    def _on_toggle_closed(self) -> None:
        balance = self._accounts.selected_balance()
        if balance is None:
            return
        if not balance.closed and not confirm(
            self,
            "Clôturer le compte",
            f"Clôturer « {balance.name} » ? Il n'acceptera plus de nouvelles opérations.",
            "Clôturer",
        ):
            return
        if self._run_void(
            lambda session: accounts.set_account_closed(
                session, balance.account_id, closed=not balance.closed
            )
        ):
            self.refresh(select_account_id=balance.account_id)

    def _on_show_closed(self, checked: bool) -> None:
        self._show_closed = checked
        self.refresh()

    # --- Opérations -----------------------------------------------------------------------

    @staticmethod
    def _save_transaction(
        session: Session, transaction_id: int | None, data: TransactionInput
    ) -> int:
        payee_id = (
            lookups.get_or_create_payee(session, data.payee_name).id if data.payee_name else None
        )
        transaction_data = TransactionData(
            account_id=data.account_id,
            date=data.date,
            amount_cents=data.amount_cents,
            payee_id=payee_id,
            category_id=data.category_id,
            payment_method_id=data.payment_method_id,
            notes=data.notes,
        )
        if transaction_id is None:
            return tx.add_transaction(session, transaction_data).id
        return tx.update_transaction(session, transaction_id, transaction_data).id

    def _on_new_transaction(self) -> None:
        with self._factory() as session:
            choices = load_choices(session)
        dialog = TransactionDialog(
            choices,
            account_id=self._accounts.selected_account_id(),
            today=self._today(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        transaction_id = self._run(lambda session: self._save_transaction(session, None, data))
        if transaction_id is not None:
            self.refresh(select_account_id=data.account_id, select_transaction_id=transaction_id)
            self.statusBar().showMessage("Opération enregistrée.", 4000)

    def _on_new_transfer(self) -> None:
        with self._factory() as session:
            choices = load_choices(session)
        dialog = TransferDialog(
            choices,
            from_account_id=self._accounts.selected_account_id(),
            today=self._today(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()

        def create(session: Session) -> dict[int, int]:
            outgoing, incoming = tx.create_transfer(session, data)
            return {outgoing.account_id: outgoing.id, incoming.account_id: incoming.id}

        legs = self._run(create)
        if legs is not None:
            current = self._accounts.selected_account_id()
            self.refresh(
                select_account_id=current,
                select_transaction_id=legs.get(current) if current is not None else None,
            )
            self.statusBar().showMessage("Virement enregistré.", 4000)

    def _on_edit_transaction(self) -> None:
        line = self._register.selected_line()
        if line is None:
            return
        if line.status is ReconciliationStatus.RECONCILED:
            show_error(
                self,
                "Cette opération est rapprochée : elle est figée. Pour la modifier, annulez "
                "d'abord le dernier rapprochement (menu Rapprochement).",
                "Opération rapprochée",
            )
            return
        # Un compte clôturé n'accepte plus de modification.
        balance = self._accounts.selected_balance()
        if balance is not None and balance.closed:
            return
        if line.is_transfer:
            self._edit_transfer(line)
        else:
            self._edit_ordinary(line)

    def _edit_ordinary(self, line: RegisterLine) -> None:
        with self._factory() as session:
            choices = load_choices(session)
        dialog = TransactionDialog(choices, initial=line, today=self._today(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        transaction_id = self._run(
            lambda session: self._save_transaction(session, line.transaction_id, data)
        )
        if transaction_id is not None:
            self.refresh(select_account_id=data.account_id, select_transaction_id=transaction_id)
            self.statusBar().showMessage("Opération modifiée.", 4000)

    def _edit_transfer(self, line: RegisterLine) -> None:
        with self._factory() as session:
            choices = load_choices(session)
        dialog = TransferDialog(choices, initial=line, today=self._today(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        if self._run_void(lambda session: tx.update_transfer(session, line.transaction_id, data)):
            self.refresh(
                select_account_id=line.account_id, select_transaction_id=line.transaction_id
            )
            self.statusBar().showMessage("Virement modifié.", 4000)

    def _on_delete_transaction(self) -> None:
        line = self._register.selected_line()
        if line is None:
            return
        if line.status is ReconciliationStatus.RECONCILED:
            show_error(
                self,
                "Cette opération est rapprochée : elle ne peut pas être supprimée.",
                "Opération rapprochée",
            )
            return
        text = (
            "Supprimer ce virement ? Les deux opérations (sur les deux comptes) seront supprimées."
            if line.is_transfer
            else "Supprimer cette opération ?"
        )
        if not confirm(self, "Supprimer", text, "Supprimer"):
            return
        if self._run_void(lambda session: tx.delete_transaction(session, line.transaction_id)):
            self.refresh(select_account_id=line.account_id)
            self.statusBar().showMessage("Opération supprimée.", 4000)

    # --- Rapprochement --------------------------------------------------------------------

    def _on_reconcile(self) -> None:
        account_id = self._accounts.selected_account_id()
        if account_id is None:
            return
        dialog = ReconciliationDialog(self._factory, account_id, today=self._today(), parent=self)
        validated = dialog.exec() == QDialog.DialogCode.Accepted
        # Même sans validation, des opérations ont pu être pointées : on rafraîchit toujours.
        self.refresh(select_account_id=account_id)
        if validated:
            self.statusBar().showMessage("Rapprochement validé.", 4000)

    def _on_undo_reconcile(self) -> None:
        account_id = self._accounts.selected_account_id()
        if account_id is None:
            return
        with self._factory() as session:
            last = rec.last_reconciliation(session, account_id)
        if last is None:
            return
        count = last.transaction_count
        if not confirm(
            self,
            "Annuler le rapprochement",
            f"Annuler le rapprochement du {last.statement_date.strftime('%d/%m/%Y')} "
            f"(solde {format_cents(last.statement_balance_cents)}, {count} "
            f"opération{'s' if count > 1 else ''}) ?\n\n"
            "Les opérations redeviendront modifiables et non pointées.",
            "Annuler le rapprochement",
        ):
            return
        if self._run_void(lambda session: rec.undo_last_reconciliation(session, account_id)):
            self.refresh(select_account_id=account_id)
            self.statusBar().showMessage("Rapprochement annulé.", 4000)

    # --- Divers ---------------------------------------------------------------------------

    def _on_categories(self) -> None:
        CategoriesDialog(self._factory, self).exec()
        self.refresh()  # les noms de catégorie du registre ont pu changer

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "À propos",
            f"<b>Budget familial</b> {__version__}<br>Licence MIT.",
        )
