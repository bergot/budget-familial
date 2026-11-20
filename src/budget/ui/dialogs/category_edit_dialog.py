"""Formulaire d'une catégorie : son nom et son type (dépense ou recette)."""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from budget.domain.enums import CategoryKind
from budget.ui.dialogs.common import make_button_box, show_error


@dataclass(frozen=True, slots=True)
class CategoryInput:
    name: str
    kind: CategoryKind


class CategoryEditDialog(QDialog):
    """Nom et type d'une catégorie.

    `kind_editable=False` pour une sous-catégorie : elle suit toujours le type de sa
    catégorie parente, qu'on affiche mais qu'on ne peut pas changer ici.
    """

    def __init__(
        self,
        title: str,
        *,
        name: str = "",
        kind: CategoryKind = CategoryKind.EXPENSE,
        kind_editable: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self._input: CategoryInput | None = None

        self._name = QLineEdit(name)
        self._expense = QRadioButton(CategoryKind.EXPENSE.label)
        self._income = QRadioButton(CategoryKind.INCOME.label)
        (self._income if kind is CategoryKind.INCOME else self._expense).setChecked(True)
        for radio in (self._expense, self._income):
            radio.setEnabled(kind_editable)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self._expense)
        kind_row.addWidget(self._income)
        kind_row.addStretch()

        form = QFormLayout()
        form.addRow("Nom :", self._name)
        form.addRow("Type :", kind_row)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        if not kind_editable:
            note = QLabel("Une sous-catégorie a le type de sa catégorie parente.")
            note.setStyleSheet("color: gray;")
            layout.addWidget(note)
        layout.addWidget(buttons)
        self._name.setFocus()

    def accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            show_error(self, "Le nom de la catégorie est obligatoire.")
            return
        kind = CategoryKind.INCOME if self._income.isChecked() else CategoryKind.EXPENSE
        self._input = CategoryInput(name, kind)
        super().accept()

    def values(self) -> CategoryInput:
        assert self._input is not None, "values() n'est valable qu'après validation du dialogue"
        return self._input
