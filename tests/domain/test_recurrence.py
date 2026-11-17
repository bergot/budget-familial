import datetime as dt

import pytest

from budget.domain.enums import Frequency
from budget.domain.recurrence import occurrence, occurrences, shift_months

D = dt.date


def test_monthly_on_the_31st_returns_to_the_31st_without_drifting() -> None:
    """Le cas piège : 31 janvier, puis 28 février, puis de nouveau le 31 mars."""
    start = D(2026, 1, 31)
    dates = [occurrence(start, Frequency.MONTHLY, n) for n in range(12)]
    assert dates == [
        D(2026, 1, 31),
        D(2026, 2, 28),
        D(2026, 3, 31),  # pas le 28 : aucune dérive
        D(2026, 4, 30),
        D(2026, 5, 31),
        D(2026, 6, 30),
        D(2026, 7, 31),
        D(2026, 8, 31),
        D(2026, 9, 30),
        D(2026, 10, 31),
        D(2026, 11, 30),
        D(2026, 12, 31),
    ]


def test_monthly_across_a_leap_year() -> None:
    start = D(2028, 1, 31)
    assert occurrence(start, Frequency.MONTHLY, 1) == D(2028, 2, 29)  # 2028 est bissextile
    assert occurrence(start, Frequency.MONTHLY, 2) == D(2028, 3, 31)


def test_monthly_on_the_30th_and_the_29th() -> None:
    assert occurrence(D(2026, 1, 30), Frequency.MONTHLY, 1) == D(2026, 2, 28)
    assert occurrence(D(2027, 1, 29), Frequency.MONTHLY, 1) == D(2027, 2, 28)
    assert occurrence(D(2028, 1, 29), Frequency.MONTHLY, 1) == D(2028, 2, 29)


def test_ordinary_day_never_changes() -> None:
    start = D(2026, 3, 5)
    assert {occurrence(start, Frequency.MONTHLY, n).day for n in range(24)} == {5}


def test_quarterly() -> None:
    start = D(2026, 11, 30)
    assert [occurrence(start, Frequency.QUARTERLY, n) for n in range(4)] == [
        D(2026, 11, 30),
        D(2027, 2, 28),
        D(2027, 5, 30),  # le 30 est de retour
        D(2027, 8, 30),
    ]


def test_yearly_from_a_leap_day() -> None:
    start = D(2028, 2, 29)
    assert [occurrence(start, Frequency.YEARLY, n) for n in range(5)] == [
        D(2028, 2, 29),
        D(2029, 2, 28),
        D(2030, 2, 28),
        D(2031, 2, 28),
        D(2032, 2, 29),  # le 29 revient l'année bissextile suivante
    ]


def test_first_occurrence_is_the_start_date_itself() -> None:
    for frequency in Frequency:
        assert occurrence(D(2026, 7, 14), frequency, 0) == D(2026, 7, 14)


def test_each_occurrence_is_independent_of_the_previous_ones() -> None:
    """Indice 7 calculé directement = indice 7 obtenu en parcourant les précédents."""
    start = D(2026, 1, 31)
    walked = [occurrence(start, Frequency.MONTHLY, n) for n in range(8)]
    assert occurrence(start, Frequency.MONTHLY, 7) == walked[7] == D(2026, 8, 31)


def test_year_rollover() -> None:
    assert occurrence(D(2026, 11, 15), Frequency.MONTHLY, 2) == D(2027, 1, 15)
    assert occurrence(D(2026, 12, 31), Frequency.MONTHLY, 2) == D(2027, 2, 28)


def test_occurrences_until_a_date() -> None:
    result = list(occurrences(D(2026, 1, 31), Frequency.MONTHLY, until=D(2026, 4, 30)))
    assert result == [
        (0, D(2026, 1, 31)),
        (1, D(2026, 2, 28)),
        (2, D(2026, 3, 31)),
        (3, D(2026, 4, 30)),  # `until` est inclus
    ]


def test_occurrences_can_resume_from_an_index() -> None:
    result = list(
        occurrences(D(2026, 1, 31), Frequency.MONTHLY, first_index=2, until=D(2026, 5, 31))
    )
    assert [index for index, _ in result] == [2, 3, 4]
    assert result[0][1] == D(2026, 3, 31)


def test_occurrences_stop_at_the_end_date() -> None:
    result = list(
        occurrences(D(2026, 1, 15), Frequency.MONTHLY, until=D(2026, 12, 31), end=D(2026, 3, 20))
    )
    assert [day for _, day in result] == [D(2026, 1, 15), D(2026, 2, 15), D(2026, 3, 15)]


def test_occurrences_end_date_is_inclusive() -> None:
    result = list(
        occurrences(D(2026, 1, 15), Frequency.MONTHLY, until=D(2026, 12, 31), end=D(2026, 2, 15))
    )
    assert [day for _, day in result] == [D(2026, 1, 15), D(2026, 2, 15)]


def test_no_occurrence_when_everything_is_after_the_limit() -> None:
    assert list(occurrences(D(2026, 6, 1), Frequency.MONTHLY, until=D(2026, 5, 31))) == []
    assert (
        list(
            occurrences(
                D(2026, 6, 1),
                Frequency.MONTHLY,
                first_index=0,
                until=D(2026, 9, 1),
                end=D(2026, 5, 1),
            )
        )
        == []
    )


def test_occurrences_resuming_beyond_the_limit_gives_nothing() -> None:
    assert (
        list(occurrences(D(2026, 1, 1), Frequency.MONTHLY, first_index=10, until=D(2026, 6, 1)))
        == []
    )


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (D(2026, 11, 16), 3, D(2027, 2, 16)),
        (D(2026, 11, 30), 3, D(2027, 2, 28)),  # horizon : replié sur la fin de février
        (D(2026, 1, 31), 1, D(2026, 2, 28)),
        (D(2026, 3, 15), 0, D(2026, 3, 15)),
        (D(2026, 3, 15), -3, D(2025, 12, 15)),
    ],
)
def test_shift_months(start: dt.date, months: int, expected: dt.date) -> None:
    assert shift_months(start, months) == expected


def test_frequency_labels_and_steps() -> None:
    assert [f.label for f in Frequency] == ["Mensuelle", "Trimestrielle", "Annuelle"]
    assert [f.months for f in Frequency] == [1, 3, 12]
