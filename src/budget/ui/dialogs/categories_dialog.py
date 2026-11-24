"""Gestion des catégories et sous-catégories."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from budget.domain.enums import CategoryKind
from budget.services import categories
from budget.settings import SettingsStore
from budget.ui.dialogs.category_edit_dialog import CategoryEditDialog
from budget.ui.dialogs.common import confirm, run_action
from budget.ui.geometry import RememberedSizeDialog

_ID_ROLE = Qt.ItemDataRole.UserRole
_KIND_ROLE = Qt.ItemDataRole.UserRole + 1


class CategoriesDialog(RememberedSizeDialog):
    """Arbre des catégories, avec ajout, modification et suppression.

    Contrairement aux autres dialogues, celui-ci agit directement sur la base : chaque
    bouton valide aussitôt son changement (il n'y a pas de bouton « Enregistrer »).
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        parent: QWidget | None = None,
        *,
        store: SettingsStore | None = None,
    ) -> None:
        super().__init__(store, "categories", parent)
        self.setWindowTitle("Catégories")
        self.resize(580, 500)
        self._factory = session_factory

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Catégorie", "Type"])
        self._tree.itemSelectionChanged.connect(self._update_buttons)

        self._add_root = QPushButton("Ajouter une catégorie…")
        self._add_child = QPushButton("Ajouter une sous-catégorie…")
        self._rename = QPushButton("Modifier…")
        self._delete = QPushButton("Supprimer")
        close = QPushButton("Fermer")
        self._add_root.clicked.connect(self._on_add_root)
        self._add_child.clicked.connect(self._on_add_child)
        self._rename.clicked.connect(self._on_edit)
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
        self.restore_saved_size()

    # --- Affichage ---------------------------------------------------------------------

    def _make_item(self, name: str, category_id: int, kind: CategoryKind) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, kind.label])
        item.setData(0, _ID_ROLE, category_id)
        item.setData(0, _KIND_ROLE, kind.value)
        return item

    def _reload(self, select_id: int | None = None) -> None:
        self._tree.clear()
        selected: QTreeWidgetItem | None = None
        with self._factory() as session:
            for root in categories.list_root_categories(session):
                root_item = self._make_item(root.name, root.id, root.kind)
                self._tree.addTopLevelItem(root_item)
                if root.id == select_id:
                    selected = root_item
                for child in root.children:
                    child_item = self._make_item(child.name, child.id, child.kind)
                    root_item.addChild(child_item)
                    if child.id == select_id:
                        selected = child_item
        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)
        if selected is not None:
            self._tree.setCurrentItem(selected)
        self._update_buttons()

    def _selected(self) -> QTreeWidgetItem | None:
        items = self._tree.selectedItems()
        return items[0] if items else None

    @staticmethod
    def _kind_of(item: QTreeWidgetItem) -> CategoryKind:
        return CategoryKind(item.data(0, _KIND_ROLE))

    def _update_buttons(self) -> None:
        item = self._selected()
        self._add_child.setEnabled(item is not None and item.parent() is None)
        self._rename.setEnabled(item is not None)
        self._delete.setEnabled(item is not None)

    # --- Actions -----------------------------------------------------------------------

    def _run(self, action: Callable[[Session], int | None]) -> None:
        """Exécute une action dans une transaction ; affiche l'erreur métier éventuelle.

        L'action peut renvoyer l'identifiant de la catégorie à sélectionner ensuite.
        """
        # On enveloppe le résultat dans un tuple pour distinguer « échec » (None) d'une action
        # réussie qui ne renvoie rien (la suppression).
        outcome = run_action(self, self._factory, lambda session: (action(session),))
        if outcome is not None:
            self._reload(select_id=outcome[0])

    def _on_add_root(self) -> None:
        dialog = CategoryEditDialog("Nouvelle catégorie", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        self._run(lambda session: categories.create_category(session, data.name, kind=data.kind).id)

    def _on_add_child(self) -> None:
        item = self._selected()
        if item is None or item.parent() is not None:
            return
        parent_id = item.data(0, _ID_ROLE)
        dialog = CategoryEditDialog(
            f"Nouvelle sous-catégorie de « {item.text(0)} »",
            kind=self._kind_of(item),
            kind_editable=False,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        self._run(
            lambda session: categories.create_category(session, data.name, parent_id=parent_id).id
        )

    def _on_edit(self) -> None:
        item = self._selected()
        if item is None:
            return
        category_id = item.data(0, _ID_ROLE)
        dialog = CategoryEditDialog(
            "Modifier la catégorie",
            name=item.text(0),
            kind=self._kind_of(item),
            kind_editable=item.parent() is None,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        self._run(
            lambda session: (
                categories.update_category(session, category_id, name=data.name, kind=data.kind).id
            )
        )

    def _on_delete(self) -> None:
        item = self._selected()
        if item is None:
            return
        category_id = item.data(0, _ID_ROLE)
        if confirm(self, "Supprimer", f"Supprimer « {item.text(0)} » ?", "Supprimer"):
            self._run(lambda session: categories.delete_category(session, category_id))
