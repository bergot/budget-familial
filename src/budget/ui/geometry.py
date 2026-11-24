"""Mémorisation de la taille et de la position des fenêtres entre deux lancements."""

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QDialog, QSplitter, QWidget

from budget.settings import SettingsStore


def restore_geometry(widget: QWidget, store: SettingsStore | None, key: str) -> bool:
    """Rétablit la géométrie mémorisée de `widget`. Retourne False s'il n'y en a pas.

    Qt vérifie lui-même que la fenêtre reste visible : si l'écran où elle se trouvait a
    disparu (portable débranché de son écran externe), elle est ramenée sur un écran existant.
    """
    if store is None:
        return False
    data = store.settings.geometry(key)
    if data is None:
        return False
    return widget.restoreGeometry(QByteArray(data))


def save_geometry(widget: QWidget, store: SettingsStore | None, key: str) -> None:
    """Mémorise la géométrie de `widget` (sans enregistrer le fichier)."""
    if store is not None:
        store.settings.set_geometry(key, bytes(widget.saveGeometry().data()))


def restore_splitter(splitter: QSplitter, store: SettingsStore | None, key: str) -> bool:
    if store is None:
        return False
    data = store.settings.geometry(key)
    if data is None:
        return False
    return splitter.restoreState(QByteArray(data))


def save_splitter(splitter: QSplitter, store: SettingsStore | None, key: str) -> None:
    if store is not None:
        store.settings.set_geometry(key, bytes(splitter.saveState().data()))


class RememberedSizeDialog(QDialog):
    """Boîte de dialogue qui se souvient de sa taille d'un lancement à l'autre.

    Les classes dérivées appellent `self.restore_saved_size()` **à la fin** de leur constructeur
    (après avoir fixé leur taille par défaut) ; la taille est mémorisée à la fermeture, quelle
    qu'en soit la manière (bouton, Échap, croix de la fenêtre).
    """

    def __init__(
        self, store: SettingsStore | None, key: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._size_store = store
        self._size_key = key

    def restore_saved_size(self) -> None:
        restore_geometry(self, self._size_store, self._size_key)

    def done(self, result: int) -> None:
        # `done` est appelée par accept(), reject() et la fermeture de la fenêtre.
        if self._size_store is not None:
            save_geometry(self, self._size_store, self._size_key)
            self._size_store.save()
        super().done(result)
