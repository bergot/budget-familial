"""Préférences : horizon des échéances et sauvegardes."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from budget.backup import backup_dir_for
from budget.settings import HORIZON_MAX, HORIZON_MIN, KEEP_MAX, KEEP_MIN, Settings
from budget.ui.dialogs.common import make_button_box


@dataclass(frozen=True, slots=True)
class PreferencesInput:
    schedule_horizon_months: int
    backup_enabled: bool
    backup_keep: int
    backup_dir: str  # vide : dossier par défaut


class PreferencesDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        *,
        database: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Préférences")
        self.setMinimumWidth(560)
        self._database = database
        self._input: PreferencesInput | None = None

        self._horizon = QSpinBox()
        self._horizon.setRange(HORIZON_MIN, HORIZON_MAX)
        self._horizon.setSuffix(" mois")
        self._horizon.setValue(settings.schedule_horizon_months)
        horizon_note = QLabel(
            "Jusqu'où les opérations des échéances sont créées à l'avance (elles apparaissent "
            "alors dans le solde prévisionnel). Réduire cette durée ne supprime rien."
        )
        horizon_note.setWordWrap(True)
        horizon_note.setStyleSheet("color: gray;")

        self._backup_enabled = QCheckBox("Sauvegarder automatiquement au lancement (une par jour)")
        self._backup_enabled.setChecked(settings.backup_enabled)
        self._keep = QSpinBox()
        self._keep.setRange(KEEP_MIN, KEEP_MAX)
        self._keep.setSuffix(" copies")
        self._keep.setValue(settings.backup_keep)
        self._folder = QLineEdit(settings.backup_dir)
        self._folder.setPlaceholderText("dossier par défaut")
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._on_browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder, stretch=1)
        folder_row.addWidget(browse)
        self._effective = QLabel()
        self._effective.setWordWrap(True)
        self._effective.setStyleSheet("color: gray;")

        form = QFormLayout()
        form.addRow("Échéances, générer jusqu'à :", self._horizon)
        form.addRow("", horizon_note)
        form.addRow("Sauvegardes :", self._backup_enabled)
        form.addRow("Copies conservées :", self._keep)
        form.addRow("Dossier des sauvegardes :", folder_row)
        form.addRow("", self._effective)

        buttons = make_button_box()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._folder.textChanged.connect(self._update_effective)
        self._backup_enabled.toggled.connect(self._update_enabled)
        self._update_effective()
        self._update_enabled()

    def _update_enabled(self) -> None:
        enabled = self._backup_enabled.isChecked()
        self._keep.setEnabled(enabled)
        # Le dossier reste modifiable : il sert aussi à « Sauvegarder maintenant ».

    def _update_effective(self) -> None:
        if self._database is None:
            self._effective.setText("")
            return
        folder = backup_dir_for(self._database, self._folder.text())
        self._effective.setText(f"Les sauvegardes seront écrites dans : {folder}")

    def _on_browse(self) -> None:
        start = self._folder.text().strip() or str(self._database.parent if self._database else "")
        chosen = QFileDialog.getExistingDirectory(self, "Dossier des sauvegardes", start)
        if chosen:
            self._folder.setText(chosen)

    def accept(self) -> None:
        self._input = PreferencesInput(
            schedule_horizon_months=self._horizon.value(),
            backup_enabled=self._backup_enabled.isChecked(),
            backup_keep=self._keep.value(),
            backup_dir=self._folder.text().strip(),
        )
        super().accept()

    def values(self) -> PreferencesInput:
        assert self._input is not None, "values() n'est valable qu'après validation du dialogue"
        return self._input
