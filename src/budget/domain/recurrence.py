"""Calcul des dates des échéances récurrentes (fonctions pures, sans base de données).

Le piège : une échéance fixée au 31 janvier. Le mois suivant n'a que 28 jours, donc on
tombe le 28 février. Mais le mois d'après doit revenir au 31 mars, pas rester au 28.

Pour éviter toute **dérive**, on ne calcule jamais « la date suivante » à partir de la
précédente. On calcule la n-ième occurrence directement à partir de la date de départ :
`occurrence(start, frequency, n)`. Chaque date est ainsi indépendante des autres.
"""

import calendar
import datetime as dt
from collections.abc import Iterator

from budget.domain.enums import Frequency


def shift_months(day: dt.date, months: int, *, anchor_day: int | None = None) -> dt.date:
    """Décale `day` de `months` mois, en se repliant sur le dernier jour du mois si besoin.

    `anchor_day` est le jour du mois visé (par défaut, celui de `day`) : le 31 visé donne
    le 28 ou 29 en février, le 30 en avril, etc.
    """
    target = day.year * 12 + (day.month - 1) + months
    year, month_index = divmod(target, 12)
    month = month_index + 1
    wanted_day = anchor_day if anchor_day is not None else day.day
    return dt.date(year, month, min(wanted_day, calendar.monthrange(year, month)[1]))


def occurrence(start: dt.date, frequency: Frequency, index: int) -> dt.date:
    """Date de la n-ième occurrence (`index` = 0 pour la première, c'est `start` lui-même)."""
    return shift_months(start, frequency.months * index)


def occurrences(
    start: dt.date,
    frequency: Frequency,
    *,
    first_index: int = 0,
    until: dt.date,
    end: dt.date | None = None,
) -> Iterator[tuple[int, dt.date]]:
    """Produit les couples (indice, date) à partir de `first_index`, jusqu'à `until` inclus.

    `end` est la date de fin facultative de l'échéance : aucune occurrence après elle.
    """
    last = min(until, end) if end is not None else until
    index = first_index
    while (day := occurrence(start, frequency, index)) <= last:
        yield index, day
        index += 1
