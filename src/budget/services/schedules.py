"""Échéances récurrentes : modèles d'opérations et génération automatique.

Principe : une `Schedule` décrit une opération (ou un virement) qui se répète. Au lancement
de l'application, `generate_due_transactions` crée les vraies opérations jusqu'à un
**horizon** (quelques mois devant soi), pour qu'elles apparaissent dans le solde
prévisionnel.

Garanties :
- **Pas de doublon** : le compteur `generated_count` de l'échéance avance dans la même
  transaction que la création des opérations. Relancer la génération ne recrée rien.
- **Indépendance** : une opération générée est une opération comme une autre. La modifier ou
  la supprimer ne touche pas l'échéance, et une opération supprimée n'est jamais recréée.
- **Pas de dérive des dates** : voir `domain/recurrence.py`.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from budget.db.models import Account, Category, Payee, PaymentMethod, Schedule
from budget.domain.enums import Frequency
from budget.domain.errors import InvalidError, NotFoundError
from budget.domain.recurrence import occurrence, occurrences, shift_months
from budget.services import transactions as tx
from budget.services._common import require
from budget.services.transactions import TransactionData, TransferData

DEFAULT_HORIZON_MONTHS = 3


@dataclass(frozen=True, slots=True)
class ScheduleData:
    """Contenu d'une échéance, tel que saisi dans le formulaire."""

    account_id: int  # compte de l'opération ; pour un virement, le compte qui envoie
    amount_cents: int  # opération : signé (< 0 dépense) ; virement : strictement positif
    frequency: Frequency
    start_date: dt.date
    end_date: dt.date | None = None
    payee_id: int | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    notes: str = ""
    transfer_account_id: int | None = None  # renseigné => virement vers ce compte


@dataclass(frozen=True, slots=True)
class ScheduleLine:
    """Une échéance sous forme de valeurs simples, prête pour l'interface."""

    id: int
    account_id: int
    account_name: str
    label: str  # nom du tiers, ou « Virement vers X »
    signed_amount_cents: int  # du point de vue du compte : < 0 pour une sortie
    frequency: Frequency
    start_date: dt.date
    end_date: dt.date | None
    generated_count: int
    next_date: dt.date | None  # prochaine occurrence à générer ; None si l'échéance est terminée
    amount_cents: int
    payee_id: int | None
    payee_name: str
    category_id: int | None
    category_name: str
    payment_method_id: int | None
    payment_method_name: str
    notes: str
    transfer_account_id: int | None

    @property
    def is_transfer(self) -> bool:
        return self.transfer_account_id is not None


@dataclass(frozen=True, slots=True)
class SkippedSchedule:
    """Une échéance qui n'a pas pu être générée (par exemple, compte clôturé)."""

    schedule_id: int
    description: str
    reason: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    created: int  # nombre d'occurrences générées (un virement compte pour une)
    skipped: tuple[SkippedSchedule, ...] = ()


# --- Validation -----------------------------------------------------------------------------


def _validate(session: Session, data: ScheduleData) -> None:
    account = require(session, Account, data.account_id, "Compte")
    if account.closed:
        raise InvalidError(f"Le compte « {account.name} » est clôturé")

    if data.end_date is not None and data.end_date < data.start_date:
        raise InvalidError("La date de fin ne peut pas précéder la date de début")

    if data.transfer_account_id is not None:
        target = require(session, Account, data.transfer_account_id, "Compte de destination")
        if target.closed:
            raise InvalidError(f"Le compte « {target.name} » est clôturé")
        if data.transfer_account_id == data.account_id:
            raise InvalidError("Un virement doit relier deux comptes différents")
        if data.amount_cents <= 0:
            raise InvalidError("Le montant d'un virement doit être positif")
        if data.payee_id is not None or data.category_id is not None:
            raise InvalidError("Un virement n'a ni tiers ni catégorie")
    elif data.amount_cents == 0:
        raise InvalidError("Le montant ne peut pas être nul")

    if data.payee_id is not None:
        require(session, Payee, data.payee_id, "Tiers")
    if data.category_id is not None:
        require(session, Category, data.category_id, "Catégorie")
    if data.payment_method_id is not None:
        require(session, PaymentMethod, data.payment_method_id, "Moyen de paiement")


def _apply(schedule: Schedule, data: ScheduleData) -> None:
    schedule.account_id = data.account_id
    schedule.amount_cents = data.amount_cents
    schedule.frequency = data.frequency
    schedule.start_date = data.start_date
    schedule.end_date = data.end_date
    schedule.payee_id = data.payee_id
    schedule.category_id = data.category_id
    schedule.payment_method_id = data.payment_method_id
    schedule.notes = data.notes
    schedule.transfer_account_id = data.transfer_account_id


# --- Gestion des échéances ------------------------------------------------------------------


def get_schedule(session: Session, schedule_id: int) -> Schedule:
    return require(session, Schedule, schedule_id, "Échéance")


def create_schedule(session: Session, data: ScheduleData) -> Schedule:
    """Crée une échéance. Les opérations ne sont générées que par `generate_due_transactions`."""
    _validate(session, data)
    schedule = Schedule(generated_count=0)
    _apply(schedule, data)
    session.add(schedule)
    session.flush()
    return schedule


def update_schedule(session: Session, schedule_id: int, data: ScheduleData) -> Schedule:
    """Modifie une échéance. Les opérations déjà générées ne sont pas touchées.

    Une fois des opérations générées, la date de début et la fréquence sont verrouillées :
    les modifier rendrait incohérent le décompte des occurrences déjà créées. Pour changer
    de rythme, on termine l'échéance (date de fin) et on en crée une nouvelle.
    """
    schedule = get_schedule(session, schedule_id)
    if schedule.generated_count > 0 and (
        data.frequency != schedule.frequency or data.start_date != schedule.start_date
    ):
        raise InvalidError(
            "Des opérations ont déjà été générées : la date de début et la fréquence ne "
            "peuvent plus être modifiées. Terminez cette échéance (date de fin) et créez-en "
            "une nouvelle."
        )
    _validate(session, data)
    _apply(schedule, data)
    session.flush()
    return schedule


def delete_schedule(session: Session, schedule_id: int) -> None:
    """Supprime une échéance. Les opérations déjà générées sont conservées."""
    schedule = get_schedule(session, schedule_id)
    session.delete(schedule)
    session.flush()


# --- Consultation ---------------------------------------------------------------------------


def _next_date(schedule: Schedule) -> dt.date | None:
    day = occurrence(schedule.start_date, schedule.frequency, schedule.generated_count)
    return None if schedule.end_date is not None and day > schedule.end_date else day


def _line(schedule: Schedule) -> ScheduleLine:
    if schedule.transfer_account is not None:
        label = f"Virement vers {schedule.transfer_account.name}"
        signed = -schedule.amount_cents
    else:
        label = schedule.payee.name if schedule.payee else ""
        signed = schedule.amount_cents
    return ScheduleLine(
        id=schedule.id,
        account_id=schedule.account_id,
        account_name=schedule.account.name,
        label=label,
        signed_amount_cents=signed,
        frequency=schedule.frequency,
        start_date=schedule.start_date,
        end_date=schedule.end_date,
        generated_count=schedule.generated_count,
        next_date=_next_date(schedule),
        amount_cents=schedule.amount_cents,
        payee_id=schedule.payee_id,
        payee_name=schedule.payee.name if schedule.payee else "",
        category_id=schedule.category_id,
        category_name=schedule.category.full_name if schedule.category else "",
        payment_method_id=schedule.payment_method_id,
        payment_method_name=schedule.payment_method.name if schedule.payment_method else "",
        notes=schedule.notes,
        transfer_account_id=schedule.transfer_account_id,
    )


def list_schedule_lines(session: Session) -> list[ScheduleLine]:
    """Toutes les échéances, la prochaine à venir en premier ; les terminées à la fin."""
    lines = [_line(s) for s in session.scalars(select(Schedule).order_by(Schedule.id))]
    return sorted(
        lines, key=lambda line: (line.next_date is None, line.next_date or dt.date.max, line.id)
    )


# --- Génération -----------------------------------------------------------------------------


def _describe(schedule: Schedule) -> str:
    if schedule.transfer_account is not None:
        return f"Virement {schedule.account.name} → {schedule.transfer_account.name}"
    label = schedule.payee.name if schedule.payee else (schedule.notes or "Opération")
    return f"{label} ({schedule.account.name})"


def _generate_one(session: Session, schedule: Schedule, horizon: dt.date) -> int:
    created = 0
    for index, day in occurrences(
        schedule.start_date,
        schedule.frequency,
        first_index=schedule.generated_count,
        until=horizon,
        end=schedule.end_date,
    ):
        if schedule.transfer_account_id is not None:
            tx.create_transfer(
                session,
                TransferData(
                    from_account_id=schedule.account_id,
                    to_account_id=schedule.transfer_account_id,
                    date=day,
                    amount_cents=schedule.amount_cents,
                    payment_method_id=schedule.payment_method_id,
                    notes=schedule.notes,
                    schedule_id=schedule.id,
                ),
            )
        else:
            tx.add_transaction(
                session,
                TransactionData(
                    account_id=schedule.account_id,
                    date=day,
                    amount_cents=schedule.amount_cents,
                    payee_id=schedule.payee_id,
                    category_id=schedule.category_id,
                    payment_method_id=schedule.payment_method_id,
                    notes=schedule.notes,
                    schedule_id=schedule.id,
                ),
            )
        # Le compteur avance avec chaque création, dans la même transaction : pas de doublon.
        schedule.generated_count = index + 1
        created += 1
    session.flush()
    return created


def generate_due_transactions(
    session: Session,
    *,
    today: dt.date,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
) -> GenerationResult:
    """Crée les opérations des échéances, jusqu'à `today` + `horizon_months`.

    Rattrape aussi le retard : si l'application n'a pas été ouverte depuis longtemps, toutes
    les occurrences manquantes sont créées. Une échéance impossible à générer (compte clôturé,
    par exemple) est ignorée et signalée dans le résultat, sans bloquer les autres ; elle
    sera reprise telle quelle dès que la cause aura disparu.
    """
    horizon = shift_months(today, horizon_months)
    created = 0
    skipped: list[SkippedSchedule] = []
    for schedule in session.scalars(select(Schedule).order_by(Schedule.id)):
        try:
            created += _generate_one(session, schedule, horizon)
        except (InvalidError, NotFoundError) as error:
            skipped.append(SkippedSchedule(schedule.id, _describe(schedule), str(error)))
    return GenerationResult(created=created, skipped=tuple(skipped))
