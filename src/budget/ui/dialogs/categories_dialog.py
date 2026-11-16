"""Gestion des catégories et sous-catégories."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget.db.base import unit_of_work
from budget.domain.errors import BudgetError
from budget.services import categories
from budget.ui.dialogs.common import confirm, show_error

_ID_ROLE = Qt.ItemDataRole.UserRole


class CategoriesDialog(QDialog):
    """Arbre des catégories, avec ajout, renommage et suppression.

    Contrairement aux autres dialogues, celui-ci agit directement sur la base : chaque
    bouton valide aussitôt son changement (il n'y a pas de bouton « Enregistrer »).
    """

    def __init__(self, session_factory: sessionmaker[Session], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Catégories")
        self.resize(520, 480)
        self._factory = session_factory

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemSelectionChanged.connect(self._update_buttons)

        self._add_root = QPushButton("Ajouter une catégorie…")
        self._add_child = QPushButton("Ajouter une sous-catégorie…")
        self._rename = QPushButton("Renommer…")
        self._delete = QPushButton("Supprimer")
        close = QPushButton("Fermer")
        self._add_root.clicked.connect(self._on_add_root)
        self._add_child.clicked.connect(self._on_add_child)
        self._rename.clicked.connect(self._on_rename)
        self._delete.clicked.connect(self._on_delete)
        close.clicked.connect(self.accept)

        side = QVBoxLayout()
        for button in (self._add_root, self._add_child, self._rename, self._delete):
            side.addWidget(button)
        side.addStretch()
        side.addWidget(close)

        layout = QHBoxLayout(self)
        layout.addWidget(self._tree, stretch=1)
        layout.addLayout(side)

        self._reload()

    # --- Affichage ---------------------------------------------------------------------

    def _reload(self, select_id: int | None = None) -> None:
        self._tree.clear()
        selected: QTreeWidgetItem | None = None
        with self._factory() as session:
            for root in categories.list_root_categories(session):
                root_item = QTreeWidgetItem([root.name])
                root_item.setData(0, _ID_ROLE, root.id)
                self._tree.addTopLevelItem(root_item)
                if root.id == select_id:
                    selected = root_item
                for child in root.children:
                    child_item = QTreeWidgetItem([child.name])
                    child_item.setData(0, _ID_ROLE, child.id)
                    root_item.addChild(child_item)
                    if child.id == select_id:
                        selected = child_item
        self._tree.expandAll()
        if selected is not None:
            self._tree.setCurrentItem(selected)
        self._update_buttons()

    def _selected(self) -> QTreeWidgetItem | None:
        items = self._tree.selectedItems()
        return items[0] if items else None

    def _update_buttons(self) -> None:
        item = self._selected()
        self._add_child.setEnabled(item is not None and item.parent() is None)
        self._rename.setEnabled(item is not None)
        self._delete.setEnabled(item is not None)

    # --- Actions -----------------------------------------------------------------------

    def _ask_name(self, title: str, label: str, current: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, label, text=current)
        return text if ok else None

    def _run(self, action: Callable[[Session], int | None]) -> None:
        """Exécute une action dans une transaction ; affiche l'erreur métier éventuelle.

        L'action peut renvoyer l'identifiant de la catégorie à sélectionner ensuite.
        """
        try:
            with unit_of_work(self._factory) as session:
                result = action(session)
        except BudgetError as error:
            show_error(self, error)
            return
        self._reload(select_id=result)

    def _on_add_root(self) -> None:
        name = self._ask_name("Nouvelle catégorie", "Nom de la catégorie :")
        if name is not None:
            self._run(lambda session: categories.create_category(session, name).id)

    def _on_add_child(self) -> None:
        item = self._selected()
        if item is None or item.parent() is not None:
            return
        parent_id = item.data(0, _ID_ROLE)
        name = self._ask_name("Nouvelle sous-catégorie", f"Sous-catégorie de « {item.text(0)} » :")
        if name is not None:
            self._run(
                lambda session: categories.create_category(session, name, parent_id=parent_id).id
            )

    def _on_rename(self) -> None:
        item = self._selected()
        if item is None:
            return
        category_id = item.data(0, _ID_ROLE)
        name = self._ask_name("Renommer", "Nouveau nom :", item.text(0))
        if name is not None:
            self._run(lambda session: categories.rename_category(session, category_id, name).id)

    def _on_delete(self) -> None:
        item = self._selected()
        if item is None:
            return
        category_id = item.data(0, _ID_ROLE)
        if confirm(self, "Supprimer", f"Supprimer « {item.text(0)} » ?", "Supprimer"):
            self._run(lambda session: categories.delete_category(session, category_id))
