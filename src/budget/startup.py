"""Préparation de la base au lancement (sans Qt, donc testable sans interface).

Dans l'ordre : migrations du schéma, valeurs par défaut, **sauvegarde du jour**, puis génération
des opérations des échéances. La sauvegarde passe avant la génération pour capturer les données
telles que l'utilisateur les a laissées.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from budget.backup import BackupOutcome, run_automatic_backup
from budget.db.base import create_db_engine, make_session_factory, unit_of_work
from budget.db.migrate import upgrade_to_head
from budget.paths import database_file
from budget.services.lookups import ensure_default_payment_methods
from budget.services.schedules import GenerationResult, generate_due_transactions
from budget.settings import Settings


@dataclass(frozen=True, slots=True)
class StartupReport:
    """Ce qui s'est passé au lancement, à signaler à l'utilisateur."""

    generation: GenerationResult
    backup: BackupOutcome


def open_database(
    database: Path | None = None,
    *,
    settings: Settings | None = None,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
) -> tuple[sessionmaker[Session], StartupReport]:
    """Ouvre (et au besoin crée ou met à jour) la base ; retourne ses sessions et le rapport.

    `today` et `now` ne servent qu'aux tests : par défaut, la date et l'heure réelles.
    """
    settings = settings or Settings()
    path = database or database_file()
    if now is None:
        now = dt.datetime.combine(today, dt.time(12)) if today else dt.datetime.now()
    today = today or now.date()

    engine = create_db_engine(path)
    upgrade_to_head(engine)  # crée la base au premier lancement, la met à jour ensuite
    factory = make_session_factory(engine)
    with unit_of_work(factory) as session:
        ensure_default_payment_methods(session)

    backup = run_automatic_backup(path, settings, now=now)  # jamais bloquante

    with unit_of_work(factory) as session:
        # Crée les opérations des échéances (rattrape aussi les lancements manqués).
        generation = generate_due_transactions(
            session, today=today, horizon_months=settings.schedule_horizon_months
        )
    return factory, StartupReport(generation=generation, backup=backup)
