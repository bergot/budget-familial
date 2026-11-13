import pytest

from budget.domain.money import NARROW_NBSP, NBSP, format_cents, parse_amount


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, f"0,00{NBSP}€"),
        (5, f"0,05{NBSP}€"),
        (1250, f"12,50{NBSP}€"),
        (123456, f"1{NARROW_NBSP}234,56{NBSP}€"),
        (-1250, f"-12,50{NBSP}€"),
        (-5, f"-0,05{NBSP}€"),
        (100_000_000, f"1{NARROW_NBSP}000{NARROW_NBSP}000,00{NBSP}€"),
    ],
)
def test_format_cents(cents: int, expected: str) -> None:
    assert format_cents(cents) == expected


def test_format_cents_without_symbol() -> None:
    assert format_cents(1250, symbol=False) == "12,50"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12,50", 1250),
        ("12.50", 1250),
        ("12", 1200),
        ("12,5", 1250),
        ("0,05", 5),
        ("-12,50", -1250),
        ("+3", 300),
        ("1 234,56", 123456),
        (f"1{NARROW_NBSP}234,56{NBSP}€", 123456),
        ("  7,00 € ", 700),
        (".5", 50),
    ],
)
def test_parse_amount(text: str, expected: int) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text", ["", "  ", "abc", "1,2,3", "12,345", "1e3", "NaN", "--5", "1.234,56"]
)
def test_parse_amount_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(text)


@pytest.mark.parametrize("cents", [0, 1, 99, 100, 123456, -1, -99_999])
def test_round_trip(cents: int) -> None:
    assert parse_amount(format_cents(cents)) == cents
