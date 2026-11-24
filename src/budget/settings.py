"""Réglages de l'utilisateur : horizon des échéances, sauvegardes, taille des fenêtres.

Ils sont enregistrés dans un petit fichier JSON, lisible et modifiable à la main. Ce module
n'utilise pas Qt : les réglages doivent être connus au démarrage, avant toute fenêtre.

Principes :
- un fichier absent, illisible ou abîmé ne doit **jamais** empêcher l'application de démarrer :
  on retombe sur les valeurs par défaut (et on met le fichier abîmé de côté pour ne pas le perdre) ;
- chaque valeur est contrôlée une à une : une valeur invalide est remplacée par sa valeur par
  défaut sans toucher aux autres ;
- l'écriture est atomique (fichier temporaire puis remplacement) : une coupure en plein milieu
  ne laisse pas un fichier tronqué.
"""

import base64
import binascii
import contextlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HORIZON_MIN, HORIZON_MAX = 1, 24  # mois
KEEP_MIN, KEEP_MAX = 1, 365  # nombre de sauvegardes conservées


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    """Entier compris entre `low` et `high` ; `default` si ce n'est pas un entier."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


@dataclass
class Settings:
    schedule_horizon_months: int = 3  # jusqu'où générer les opérations des échéances
    backup_enabled: bool = True  # sauvegarde automatique au lancement (une par jour)
    backup_keep: int = 14  # nombre de sauvegardes conservées
    backup_dir: str = ""  # vide : dossier « sauvegardes » à côté du fichier de données
    geometries: dict[str, str] = field(default_factory=dict)  # taille des fenêtres (base64)

    def geometry(self, key: str) -> bytes | None:
        """Géométrie mémorisée d'une fenêtre, ou None."""
        encoded = self.geometries.get(key)
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded, validate=True)
        except binascii.Error, ValueError:
            return None

    def set_geometry(self, key: str, data: bytes) -> None:
        self.geometries[key] = base64.b64encode(data).decode("ascii")

    def to_json(self) -> dict[str, Any]:
        return {
            "schedule_horizon_months": self.schedule_horizon_months,
            "backup_enabled": self.backup_enabled,
            "backup_keep": self.backup_keep,
            "backup_dir": self.backup_dir,
            "geometries": dict(self.geometries),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Settings:
        """Construit les réglages en contrôlant chaque valeur ; les inconnues sont ignorées."""
        defaults = cls()
        enabled = raw.get("backup_enabled")
        directory = raw.get("backup_dir")
        geometries = raw.get("geometries")
        return cls(
            schedule_horizon_months=_clamp(
                raw.get("schedule_horizon_months"),
                HORIZON_MIN,
                HORIZON_MAX,
                defaults.schedule_horizon_months,
            ),
            backup_enabled=enabled if isinstance(enabled, bool) else defaults.backup_enabled,
            backup_keep=_clamp(raw.get("backup_keep"), KEEP_MIN, KEEP_MAX, defaults.backup_keep),
            backup_dir=directory if isinstance(directory, str) else defaults.backup_dir,
            geometries=(
                {k: v for k, v in geometries.items() if isinstance(k, str) and isinstance(v, str)}
                if isinstance(geometries, dict)
                else {}
            ),
        )


def load_settings(path: Path | None) -> Settings:
    """Lit les réglages. Ne lève jamais d'exception : au pire, valeurs par défaut."""
    if path is None or not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("le fichier ne contient pas un objet JSON")
    except OSError, ValueError:
        _set_aside(path)
        return Settings()
    return Settings.from_json(raw)


def _set_aside(path: Path) -> None:
    """Met un fichier abîmé de côté (…corrompu) pour ne pas l'écraser au prochain enregistrement."""
    # Impossible de le déplacer : on l'écrasera, ce n'est pas bloquant.
    with contextlib.suppress(OSError):
        path.replace(path.with_name(path.name + ".corrompu"))


def save_settings(settings: Settings, path: Path) -> None:
    """Enregistre les réglages de façon atomique. Peut lever `OSError`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(settings.to_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)  # atomique, y compris sous Windows


class SettingsStore:
    """Les réglages en cours et le fichier où les enregistrer.

    Sans fichier (`path=None`), rien n'est écrit : pratique pour les tests et les essais.
    """

    def __init__(self, settings: Settings | None = None, path: Path | None = None) -> None:
        self.settings = settings or Settings()
        self.path = path

    @classmethod
    def load(cls, path: Path | None) -> SettingsStore:
        return cls(load_settings(path), path)

    def save(self) -> bool:
        """Enregistre. Retourne False (sans lever d'exception) si l'écriture échoue."""
        if self.path is None:
            return True
        try:
            save_settings(self.settings, self.path)
        except OSError:
            return False
        return True
