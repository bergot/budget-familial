"""Montants : conversion entre centimes (entiers) et texte français.

Toute l'application manipule des montants en **centimes**, sous forme d'entiers :
12,50 EUR s'écrit 1250. Seule cette couche convertit vers et depuis le texte.
"""

import re
from decimal import Decimal

NARROW_NBSP = "\u202f"  # séparateur de milliers français
NBSP = "\u00a0"  # espace insécable avant le symbole monétaire

_AMOUNT_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")


def format_cents(cents: int, *, symbol: bool = True) -> str:
    """Formate des centimes en texte français : 123456 -> '1 234,56 €'."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    grouped = f"{euros:,}".replace(",", NARROW_NBSP)
    text = f"{sign}{grouped},{rest:02d}"
    return f"{text}{NBSP}€" if symbol else text


def parse_amount(text: str) -> int:
    """Convertit un texte saisi par l'utilisateur en centimes.

    Accepte la virgule ou le point décimal, les espaces (y compris insécables),
    un signe '-' ou '+', et un symbole '€' final : '1 234,5 €' -> 123450.

    Lève `ValueError` si le texte n'est pas un montant valide ou a plus de
    deux décimales.
    """
    cleaned = text.strip()
    for char in (" ", NBSP, NARROW_NBSP, "€"):
        cleaned = cleaned.replace(char, "")
    cleaned = cleaned.replace(",", ".")
    if not cleaned:
        raise ValueError("montant vide")

    if not _AMOUNT_RE.fullmatch(cleaned):
        raise ValueError(f"montant invalide : {text!r}")

    value = Decimal(cleaned)
    cents = value * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"plus de deux décimales : {text!r}")
    return int(cents)
