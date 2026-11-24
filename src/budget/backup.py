"""Sauvegardes du fichier de données (une copie horodatée par jour, avec rotation).

Complète la copie « avant migration » faite par `db/migrate.py` : celle-ci protège d'une
migration qui tourne mal, les sauvegardes régulières protègent de tout le reste (fichier effacé
par erreur, disque défaillant, mauvaise manipulation).

Choix techniques :
- on utilise l'**API de sauvegarde de SQLite** (`Connection.backup`) plutôt qu'une copie de
  fichier : elle donne une copie cohérente même si la base est ouverte ailleurs ;
- la copie est écrite sous un nom provisoire puis renommée : une coupure en plein milieu ne
  laisse jamais un fichier tronqué qui aurait l'air d'une vraie sauvegarde ;
- chaque copie est **vérifiée** (`PRAGMA integrity_check`) avant d'être conservée : une
  sauvegarde illisible est pire que pas de sauvegarde, car elle rassure à tort ;
- la date vient du **nom** du fichier, pas de sa date de modification (qui change quand on
  copie ou restaure un fichier).
"""

import datetime as dt
import re
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path

from budget.settings import Settings

_NAME_RE = re.compile(r"^budget-(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})\.sqlite$")


class BackupError(Exception):
    """La sauvegarde n'a pas pu être faite ou n'est pas fiable."""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    moment: dt.datetime
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    """Résultat de la sauvegarde automatique du lancement."""

    path: Path | None = None  # copie créée
    skipped_reason: str | None = None  # pourquoi rien n'a été fait (normal)
    error: str | None = None  # échec : à signaler à l'utilisateur
    removed: tuple[Path, ...] = ()  # anciennes sauvegardes supprimées par la rotation


def default_backup_dir(database: Path) -> Path:
    """Dossier « sauvegardes » à côté du fichier de données."""
    return database.parent / "sauvegardes"


def backup_dir_for(database: Path, configured: str) -> Path:
    """Dossier choisi dans les préférences, ou celui par défaut s'il est vide."""
    return Path(configured).expanduser() if configured.strip() else default_backup_dir(database)


def backup_file_name(moment: dt.datetime) -> str:
    return f"budget-{moment:%Y-%m-%d-%H%M%S}.sqlite"


def _parse_name(name: str) -> dt.datetime | None:
    match = _NAME_RE.match(name)
    if match is None:
        return None
    try:
        return dt.datetime(*(int(part) for part in match.groups()))  # type: ignore[arg-type]
    except ValueError:  # un nom qui ressemble à une sauvegarde mais avec une date impossible
        return None


def list_backups(directory: Path) -> list[BackupInfo]:
    """Sauvegardes du dossier, de la plus récente à la plus ancienne ; le reste est ignoré."""
    if not directory.is_dir():
        return []
    found: list[BackupInfo] = []
    for path in directory.iterdir():
        moment = _parse_name(path.name)
        if moment is not None and path.is_file():
            found.append(BackupInfo(path, moment, path.stat().st_size))
    return sorted(found, key=lambda info: info.moment, reverse=True)


def backup_is_due(directory: Path, today: dt.date) -> bool:
    """Vrai s'il n'existe pas encore de sauvegarde datée d'aujourd'hui."""
    return not any(info.moment.date() == today for info in list_backups(directory))


def has_data(database: Path) -> bool:
    """La base contient-elle au moins un compte ? (inutile de sauvegarder une base vide)"""
    if not database.is_file():
        return False
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            return bool(connection.execute("SELECT EXISTS(SELECT 1 FROM accounts)").fetchone()[0])
    except sqlite3.Error:
        return False


def _integrity_ok(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(path)) as connection:
            return tuple(connection.execute("PRAGMA integrity_check").fetchone()) == ("ok",)
    except sqlite3.Error:
        return False


def create_backup(database: Path, directory: Path, *, moment: dt.datetime) -> Path:
    """Copie la base dans `directory`, sous un nom horodaté. Retourne le chemin de la copie."""
    if not database.is_file():
        raise BackupError(f"Fichier de données introuvable : {database}")
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / backup_file_name(moment)
    while target.exists():  # deux sauvegardes dans la même seconde : on ne l'écrase pas
        moment += dt.timedelta(seconds=1)
        target = directory / backup_file_name(moment)

    partial = target.with_name(target.name + ".partiel")
    try:
        with (
            closing(sqlite3.connect(database)) as source,
            closing(sqlite3.connect(partial)) as copy,
        ):
            source.backup(copy)
        if not _integrity_ok(partial):
            raise BackupError("La copie n'a pas passé la vérification d'intégrité : abandonnée.")
        partial.replace(target)
    except BaseException:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise
    return target


def prune_backups(directory: Path, keep: int) -> tuple[Path, ...]:
    """Ne garde que les `keep` sauvegardes les plus récentes ; retourne celles supprimées."""
    removed: list[Path] = []
    for info in list_backups(directory)[max(keep, 1) :]:
        try:
            info.path.unlink()
        except OSError:
            continue  # on réessaiera au prochain lancement
        removed.append(info.path)
    return tuple(removed)


def backup_now(
    database: Path, settings: Settings, *, now: dt.datetime
) -> tuple[Path, tuple[Path, ...]]:
    """Sauvegarde immédiate (demandée par l'utilisateur), suivie de la rotation.

    Retourne la copie créée et les anciennes copies supprimées. Peut lever `BackupError` ou
    `OSError` : l'appelant affiche le message.
    """
    directory = backup_dir_for(database, settings.backup_dir)
    path = create_backup(database, directory, moment=now)
    return path, prune_backups(directory, settings.backup_keep)


def run_automatic_backup(database: Path, settings: Settings, *, now: dt.datetime) -> BackupOutcome:
    """Sauvegarde du lancement : une par jour au plus, jamais bloquante.

    Ne lève jamais d'exception : un échec est rapporté dans le résultat, pour que l'application
    démarre quand même (et que l'utilisateur soit prévenu).
    """
    if not settings.backup_enabled:
        return BackupOutcome(skipped_reason="sauvegarde automatique désactivée")
    if not has_data(database):
        return BackupOutcome(skipped_reason="base vide ou absente")
    directory = backup_dir_for(database, settings.backup_dir)
    try:
        if not backup_is_due(directory, now.date()):
            return BackupOutcome(skipped_reason="déjà faite aujourd'hui")
        path, removed = backup_now(database, settings, now=now)
    except (OSError, sqlite3.Error, BackupError) as error:
        return BackupOutcome(error=str(error))
    return BackupOutcome(path=path, removed=removed)
