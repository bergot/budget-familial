import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from budget.db.models import Account, Schedule, Transaction
from budget.domain.enums import Frequency
from budget.domain.errors import InvalidError, NotFoundError
from budget.services import accounts, categories, lookups
from budget.services import schedules as sch
from budget.services import transactions as tx
from budget.services.schedules import ScheduleData
from budget.services.transactions import TransactionData

D = dt.date
TODAY = D(2026, 3, 15)  # horizon par défaut : 15 juin 2026


def rent(account: Account, **overrides) -> ScheduleData:  # type: ignore[no-untyped-def]
    values = {
        "account_id": account.id,
        "amount_cents": -65_000,
        "frequency": Frequency.MONTHLY,
        "start_date": D(2026, 3, 5),
    }
    values.update(overrides)
    return ScheduleData(**values)  # type: ignore[arg-type]


def transfer(source: Account, target: Account, **overrides) -> ScheduleData:  # type: ignore[no-untyped-def]
    values = {
        "account_id": source.id,
        "transfer_account_id": target.id,
        "amount_cents": 30_000,
        "frequency": Frequency.MONTHLY,
        "start_date": D(2026, 3, 1),
    }
    values.update(overrides)
    return ScheduleData(**values)  # type: ignore[arg-type]


def dates_of(session: Session, account: Account) -> list[dt.date]:
    return [t.date for t in tx.list_transactions(session, account.id)]


def count_transactions(session: Session) -> int:
    return int(session.scalar(select(func.count(Transaction.id))) or 0)


# --- Création et validation -----------------------------------------------------------------


def test_create_schedule_generates_nothing_by_itself(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    assert schedule.id is not None
    assert schedule.generated_count == 0
    assert count_transactions(session) == 0


def test_create_with_all_fields(session: Session, sg: Account) -> None:
    payee = lookups.get_or_create_payee(session, "Agence")
    category = categories.create_category(session, "Loyer")
    method = lookups.get_or_create_payment_method(session, "Prélèvement")
    schedule = sch.create_schedule(
        session,
        rent(
            sg,
            payee_id=payee.id,
            category_id=category.id,
            payment_method_id=method.id,
            notes="Loyer",
            end_date=D(2027, 3, 5),
        ),
    )
    assert (schedule.payee, schedule.category, schedule.payment_method) == (payee, category, method)
    assert schedule.end_date == D(2027, 3, 5)
    assert schedule.notes == "Loyer"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"amount_cents": 0}, "nul"),
        ({"end_date": D(2026, 3, 1)}, "fin"),
        ({"payee_id": 999}, "Tiers"),
        ({"category_id": 999}, "Catégorie"),
        ({"payment_method_id": 999}, "Moyen"),
    ],
)
def test_create_rejects_invalid_data(
    session: Session,
    sg: Account,
    overrides: dict,
    message: str,  # type: ignore[type-arg]
) -> None:
    with pytest.raises((InvalidError, NotFoundError), match=message):
        sch.create_schedule(session, rent(sg, **overrides))


def test_create_rejects_unknown_or_closed_account(session: Session, sg: Account) -> None:
    with pytest.raises(NotFoundError):
        sch.create_schedule(session, ScheduleData(999, -100, Frequency.MONTHLY, D(2026, 1, 1)))
    accounts.set_account_closed(session, sg.id, closed=True)
    with pytest.raises(InvalidError, match="clôturé"):
        sch.create_schedule(session, rent(sg))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"amount_cents": -100}, "positif"),
        ({"amount_cents": 0}, "positif"),
        ({"payee_id": -1}, "ni tiers"),
    ],
)
def test_transfer_rules(
    session: Session,
    sg: Account,
    bourso: Account,
    overrides: dict,
    message: str,  # type: ignore[type-arg]
) -> None:
    if overrides.get("payee_id") == -1:
        overrides = {"payee_id": lookups.get_or_create_payee(session, "X").id}
    with pytest.raises(InvalidError, match=message):
        sch.create_schedule(session, transfer(sg, bourso, **overrides))


def test_transfer_needs_two_different_open_accounts(
    session: Session, sg: Account, bourso: Account
) -> None:
    with pytest.raises(InvalidError, match="différents"):
        sch.create_schedule(session, transfer(sg, sg))
    accounts.set_account_closed(session, bourso.id, closed=True)
    with pytest.raises(InvalidError, match="clôturé"):
        sch.create_schedule(session, transfer(sg, bourso))


# --- Génération -----------------------------------------------------------------------------


def test_generation_fills_up_to_the_horizon(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))  # 5 mars, mensuel

    result = sch.generate_due_transactions(session, today=TODAY)

    assert result == sch.GenerationResult(created=4, skipped=())
    assert dates_of(session, sg) == [D(2026, 3, 5), D(2026, 4, 5), D(2026, 5, 5), D(2026, 6, 5)]
    assert schedule.generated_count == 4
    first = tx.list_transactions(session, sg.id)[0]
    assert (first.amount_cents, first.schedule_id) == (-65_000, schedule.id)


def test_generated_operations_copy_the_template(session: Session, sg: Account) -> None:
    payee = lookups.get_or_create_payee(session, "Agence")
    category = categories.create_category(session, "Loyer")
    method = lookups.get_or_create_payment_method(session, "Prélèvement")
    sch.create_schedule(
        session,
        rent(
            sg, payee_id=payee.id, category_id=category.id, payment_method_id=method.id, notes="N"
        ),
    )
    sch.generate_due_transactions(session, today=TODAY)

    (line, *_) = tx.register_lines(session, sg.id)
    assert (line.payee_name, line.category_name, line.payment_method_name, line.notes) == (
        "Agence",
        "Loyer",
        "Prélèvement",
        "N",
    )
    assert line.schedule_id is not None


def test_generation_twice_creates_no_duplicates(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    again = sch.generate_due_transactions(session, today=TODAY)  # « redémarrage »

    assert again.created == 0
    assert len(dates_of(session, sg)) == 4


def test_a_later_launch_generates_only_the_new_occurrences(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    later = sch.generate_due_transactions(session, today=D(2026, 4, 20))  # horizon : 20 juillet

    assert later.created == 1
    assert dates_of(session, sg)[-1] == D(2026, 7, 5)
    assert len(dates_of(session, sg)) == 5


def test_a_long_absence_is_caught_up(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)  # jusqu'au 5 juin

    # L'application n'a pas été ouverte pendant des mois. Horizon : 1er février 2027.
    result = sch.generate_due_transactions(session, today=D(2026, 11, 1))

    assert result.created == 7  # juillet 2026 à janvier 2027
    assert dates_of(session, sg)[4] == D(2026, 7, 5)
    assert dates_of(session, sg)[-1] == D(2027, 1, 5)
    assert len(dates_of(session, sg)) == 11  # aucun trou, aucun doublon


def test_a_deleted_generated_operation_is_never_recreated(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)
    april = tx.list_transactions(session, sg.id)[1]
    tx.delete_transaction(session, april.id)

    sch.generate_due_transactions(session, today=TODAY)

    assert dates_of(session, sg) == [D(2026, 3, 5), D(2026, 5, 5), D(2026, 6, 5)]


def test_end_date_stops_the_generation(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg, end_date=D(2026, 4, 5)))
    sch.generate_due_transactions(session, today=TODAY)
    assert dates_of(session, sg) == [D(2026, 3, 5), D(2026, 4, 5)]  # fin incluse

    sch.generate_due_transactions(session, today=D(2027, 1, 1))
    assert len(dates_of(session, sg)) == 2


def test_start_in_the_past_is_back_filled_with_the_right_dates(
    session: Session, sg: Account
) -> None:
    sch.create_schedule(session, rent(sg, start_date=D(2026, 1, 31)))
    sch.generate_due_transactions(session, today=TODAY)
    assert dates_of(session, sg) == [
        D(2026, 1, 31),
        D(2026, 2, 28),
        D(2026, 3, 31),  # le 31 revient, pas de dérive
        D(2026, 4, 30),
        D(2026, 5, 31),
    ]


def test_start_in_the_future_beyond_the_horizon_generates_nothing(
    session: Session, sg: Account
) -> None:
    schedule = sch.create_schedule(session, rent(sg, start_date=D(2026, 9, 1)))
    assert sch.generate_due_transactions(session, today=TODAY).created == 0
    assert schedule.generated_count == 0


def test_yearly_and_quarterly(session: Session, sg: Account) -> None:
    sch.create_schedule(
        session,
        rent(sg, frequency=Frequency.YEARLY, start_date=D(2026, 4, 10), amount_cents=-90_000),
    )
    sch.create_schedule(
        session,
        rent(sg, frequency=Frequency.QUARTERLY, start_date=D(2026, 2, 28), amount_cents=-100),
    )
    sch.generate_due_transactions(session, today=TODAY)

    by_amount = {
        amount: [t.date for t in tx.list_transactions(session, sg.id) if t.amount_cents == amount]
        for amount in (-90_000, -100)
    }
    assert by_amount[-90_000] == [D(2026, 4, 10)]  # la suivante est en 2027
    assert by_amount[-100] == [D(2026, 2, 28), D(2026, 5, 28)]


@pytest.mark.parametrize(("months", "expected"), [(0, 1), (1, 2), (12, 13)])
def test_horizon_is_a_parameter(session: Session, sg: Account, months: int, expected: int) -> None:
    sch.create_schedule(session, rent(sg, start_date=D(2026, 3, 1)))
    sch.generate_due_transactions(session, today=TODAY, horizon_months=months)
    assert len(dates_of(session, sg)) == expected


def test_generated_operations_count_in_the_forecast_but_not_the_current_balance(
    session: Session, sg: Account
) -> None:
    sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    assert accounts.current_balance(session, sg.id, today=TODAY) == 100_000 - 65_000  # 5 mars
    assert accounts.forecast_balance(session, sg.id) == 100_000 - 4 * 65_000


# --- Virements planifiés --------------------------------------------------------------------


def test_scheduled_transfer_creates_both_legs(
    session: Session, sg: Account, bourso: Account
) -> None:
    schedule = sch.create_schedule(session, transfer(sg, bourso))

    result = sch.generate_due_transactions(session, today=TODAY)

    assert result.created == 4  # 4 occurrences (mars à juin) : 8 opérations, une par compte
    assert count_transactions(session) == 8
    outgoing, incoming = (
        tx.list_transactions(session, sg.id)[0],
        tx.list_transactions(session, bourso.id)[0],
    )
    assert (outgoing.amount_cents, incoming.amount_cents) == (-30_000, 30_000)
    assert outgoing.transfer_peer_id == incoming.id and incoming.transfer_peer_id == outgoing.id
    assert outgoing.schedule_id == incoming.schedule_id == schedule.id
    assert accounts.forecast_balance(session, bourso.id) == 4 * 30_000


# --- Échéances ignorées ---------------------------------------------------------------------


def test_closed_account_schedule_is_skipped_then_resumed(session: Session, sg: Account) -> None:
    payee = lookups.get_or_create_payee(session, "Agence")
    schedule = sch.create_schedule(session, rent(sg, payee_id=payee.id))
    accounts.set_account_closed(session, sg.id, closed=True)

    result = sch.generate_due_transactions(session, today=TODAY)

    assert result.created == 0
    (skipped,) = result.skipped
    assert skipped.schedule_id == schedule.id
    assert "Agence" in skipped.description and "SG courant" in skipped.description
    assert "clôturé" in skipped.reason
    assert schedule.generated_count == 0  # rien n'est perdu

    accounts.set_account_closed(session, sg.id, closed=False)
    assert sch.generate_due_transactions(session, today=TODAY).created == 4  # rattrapage complet


def test_a_skipped_schedule_does_not_block_the_others(
    session: Session, sg: Account, bourso: Account
) -> None:
    sch.create_schedule(session, rent(bourso))
    sch.create_schedule(session, rent(sg, amount_cents=-100))
    accounts.set_account_closed(session, bourso.id, closed=True)

    result = sch.generate_due_transactions(session, today=TODAY)

    assert result.created == 4
    assert len(result.skipped) == 1
    assert len(dates_of(session, sg)) == 4


def test_skipped_transfer_is_described_with_both_accounts(
    session: Session, sg: Account, bourso: Account
) -> None:
    sch.create_schedule(session, transfer(sg, bourso))
    accounts.set_account_closed(session, bourso.id, closed=True)
    (skipped,) = sch.generate_due_transactions(session, today=TODAY).skipped
    assert skipped.description == "Virement SG courant → Boursorama"
    assert count_transactions(session) == 0  # aucune moitié orpheline


# --- Indépendance des opérations générées ---------------------------------------------------


def test_generated_operations_can_be_edited_without_touching_the_schedule(
    session: Session, sg: Account
) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)
    april = tx.list_transactions(session, sg.id)[1]

    tx.update_transaction(
        session,
        april.id,
        TransactionData(account_id=sg.id, date=D(2026, 4, 9), amount_cents=-70_000, notes="révisé"),
    )

    assert schedule.amount_cents == -65_000
    assert schedule.generated_count == 4
    assert april.schedule_id == schedule.id  # le lien d'origine est conservé
    assert (april.date, april.amount_cents) == (D(2026, 4, 9), -70_000)


def test_editing_a_schedule_changes_only_future_operations(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    sch.update_schedule(session, schedule.id, rent(sg, amount_cents=-70_000, notes="nouveau loyer"))
    sch.generate_due_transactions(session, today=D(2026, 4, 20))  # génère juillet

    amounts = [t.amount_cents for t in tx.list_transactions(session, sg.id)]
    assert amounts == [-65_000] * 4 + [-70_000]  # les anciennes ne bougent pas


def test_start_and_frequency_are_free_before_any_generation(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    sch.update_schedule(
        session, schedule.id, rent(sg, start_date=D(2026, 4, 1), frequency=Frequency.QUARTERLY)
    )
    assert (schedule.start_date, schedule.frequency) == (D(2026, 4, 1), Frequency.QUARTERLY)


def test_start_and_frequency_are_locked_after_generation(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    with pytest.raises(InvalidError, match="déjà été générées"):
        sch.update_schedule(session, schedule.id, rent(sg, frequency=Frequency.YEARLY))
    with pytest.raises(InvalidError, match="déjà été générées"):
        sch.update_schedule(session, schedule.id, rent(sg, start_date=D(2026, 3, 6)))

    # Terminer l'échéance reste possible : on fixe une date de fin.
    sch.update_schedule(session, schedule.id, rent(sg, end_date=D(2026, 4, 30)))
    assert schedule.end_date == D(2026, 4, 30)


def test_update_unknown_schedule(session: Session, sg: Account) -> None:
    with pytest.raises(NotFoundError):
        sch.update_schedule(session, 999, rent(sg))


def test_delete_schedule_keeps_the_generated_operations(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg))
    sch.generate_due_transactions(session, today=TODAY)

    sch.delete_schedule(session, schedule.id)
    session.expire_all()  # relit l'état réel de la base (le lien a été mis à NULL par la base)

    assert session.scalar(select(func.count(Schedule.id))) == 0
    operations = tx.list_transactions(session, sg.id)
    assert len(operations) == 4
    assert {t.schedule_id for t in operations} == {None}
    assert sch.generate_due_transactions(session, today=D(2027, 1, 1)).created == 0


# --- Consultation ---------------------------------------------------------------------------


def test_schedule_lines(session: Session, sg: Account, bourso: Account) -> None:
    payee = lookups.get_or_create_payee(session, "Agence")
    category = categories.create_category(session, "Loyer")
    sch.create_schedule(
        session, rent(sg, payee_id=payee.id, category_id=category.id, start_date=D(2026, 5, 5))
    )
    sch.create_schedule(session, transfer(sg, bourso, start_date=D(2026, 4, 1)))
    ended = sch.create_schedule(session, rent(sg, amount_cents=-1, end_date=D(2026, 3, 10)))
    # Génère seulement l'occurrence du 5 mars de l'échéance « terminée » (fin le 10 mars).
    sch.generate_due_transactions(session, today=D(2026, 3, 10), horizon_months=0)

    lines = sch.list_schedule_lines(session)

    # Triées par prochaine date ; l'échéance terminée est en dernier.
    assert [line.next_date for line in lines] == [D(2026, 4, 1), D(2026, 5, 5), None]
    assert lines[-1].id == ended.id

    virement, loyer, _ = lines
    assert virement.label == "Virement vers Boursorama"
    assert virement.is_transfer
    assert virement.signed_amount_cents == -30_000  # une sortie, du point de vue du compte
    assert virement.amount_cents == 30_000
    assert loyer.label == "Agence"
    assert loyer.category_name == "Loyer"
    assert loyer.account_name == "SG courant"
    assert loyer.signed_amount_cents == -65_000


def test_next_date_follows_the_generation_counter(session: Session, sg: Account) -> None:
    schedule = sch.create_schedule(session, rent(sg, start_date=D(2026, 1, 31)))
    assert sch.list_schedule_lines(session)[0].next_date == D(2026, 1, 31)
    sch.generate_due_transactions(session, today=D(2026, 1, 31), horizon_months=0)
    (line,) = sch.list_schedule_lines(session)
    assert line.generated_count == 1
    assert line.next_date == D(2026, 2, 28)
    assert schedule.generated_count == 1


# --- Protections ----------------------------------------------------------------------------


def test_account_used_by_a_schedule_cannot_be_deleted(
    session: Session, sg: Account, bourso: Account
) -> None:
    sch.create_schedule(session, transfer(sg, bourso))
    with pytest.raises(InvalidError, match="échéances"):
        accounts.delete_account(session, bourso.id)  # compte de destination
    with pytest.raises(InvalidError, match="échéances"):
        accounts.delete_account(session, sg.id)


def test_category_used_by_a_schedule_cannot_be_deleted(session: Session, sg: Account) -> None:
    category = categories.create_category(session, "Loyer")
    sch.create_schedule(session, rent(sg, category_id=category.id))
    with pytest.raises(InvalidError, match="échéances"):
        categories.delete_category(session, category.id)


def test_two_schedules_generate_in_a_stable_order(session: Session, sg: Account) -> None:
    sch.create_schedule(session, rent(sg, amount_cents=-100))
    sch.create_schedule(session, rent(sg, amount_cents=-200))
    result = sch.generate_due_transactions(session, today=TODAY)
    assert result.created == 8
    assert count_transactions(session) == 8
