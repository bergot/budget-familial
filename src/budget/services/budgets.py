"""Budget : montants prévus par catégorie et par mois, comparés au réalisé.

Conventions :
- les montants prévus sont **positifs** ; le sens (dépense ou recette) vient du type de la
  catégorie (`Category.kind`) ;
- le **réalisé** est calculé à partir des opérations, jamais saisi : pour une dépense c'est
  l'opposé de la somme des opérations (une dépense de 40 € compte +40), pour une recette c'est
  la somme. Les virements entre comptes ne sont pas du budget : ils sont exclus ;
- une catégorie qui a des sous-catégories n'est pas modifiable directement : sa ligne est le
  **total** de ses sous-catégories et de sa ligne « sans sous-catégorie » (les opérations
  rangées directement dans la catégorie, et leur éventuel budget propre).
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from budget.db.models import BudgetLine, Category, Transaction
from budget.domain.enums import CategoryKind
from budget.domain.errors import InvalidError
from budget.services import categories
from budget.services._common import require

MIN_YEAR, MAX_YEAR = 2000, 2100
MONTHS = tuple(range(1, 13))
Months = tuple[int, ...]  # 12 valeurs en centimes : janvier à décembre
_ZERO: Months = (0,) * 12


class RowKind(StrEnum):
    HEADER = "header"  # titre de section : « Recettes », « Dépenses »
    CATEGORY = "category"  # catégorie sans sous-catégorie : modifiable
    PARENT_TOTAL = "parent_total"  # catégorie avec sous-catégories : total, non modifiable
    CHILD = "child"  # sous-catégorie : modifiable
    DIRECT = "direct"  # « (sans sous-catégorie) » d'une catégorie parente : modifiable
    UNCATEGORIZED = "uncategorized"  # opérations sans catégorie : réalisé seulement
    SECTION_TOTAL = "section_total"
    BALANCE = "balance"  # recettes - dépenses


@dataclass(frozen=True, slots=True)
class BudgetRow:
    """Une ligne de la grille : 12 montants prévus et 12 montants réalisés."""

    kind: RowKind
    label: str
    section: CategoryKind | None  # None pour la ligne de solde
    category_id: int | None  # catégorie dont le montant prévu est modifié (None si calculée)
    planned: Months = _ZERO
    actual: Months = _ZERO

    @property
    def editable(self) -> bool:
        return self.kind in (RowKind.CATEGORY, RowKind.CHILD, RowKind.DIRECT)

    @property
    def depth(self) -> int:
        return 1 if self.kind in (RowKind.CHILD, RowKind.DIRECT) else 0

    def variance(self, index: int) -> int:
        """Écart du mois `index` (0 = janvier), positif quand c'est « bon » : moins dépensé
        que prévu pour une dépense, plus encaissé que prévu pour une recette ou le solde."""
        return _variance(self.section, self.planned[index], self.actual[index])

    @property
    def planned_total(self) -> int:
        return sum(self.planned)

    @property
    def actual_total(self) -> int:
        return sum(self.actual)

    @property
    def variance_total(self) -> int:
        return _variance(self.section, self.planned_total, self.actual_total)


def _variance(section: CategoryKind | None, planned: int, actual: int) -> int:
    return planned - actual if section is CategoryKind.EXPENSE else actual - planned


@dataclass(frozen=True, slots=True)
class Budget:
    year: int
    rows: tuple[BudgetRow, ...]


# --- Calcul sur les séries de 12 mois --------------------------------------------------------


def _add(a: Months, b: Months) -> Months:
    return tuple(x + y for x, y in zip(a, b, strict=True))


def _sub(a: Months, b: Months) -> Months:
    return tuple(x - y for x, y in zip(a, b, strict=True))


def comparable_months(year: int, today: dt.date) -> int:
    """Nombre de premiers mois de `year` dont l'écart prévu/réalisé a un sens.

    Un mois à venir n'a encore rien réalisé : comparer reviendrait à annoncer des recettes
    « manquantes » et des économies sur des dépenses qui n'ont pas eu lieu. Le mois en cours
    est comparé tel quel (le réalisé y est partiel). Années passées : 12 ; futures : 0.
    """
    if year < today.year:
        return 12
    if year > today.year:
        return 0
    return today.month


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise InvalidError(f"L'année doit être comprise entre {MIN_YEAR} et {MAX_YEAR}")


def _check_month(month: int) -> None:
    if month not in MONTHS:
        raise InvalidError("Le mois doit être compris entre 1 et 12")


# --- Saisie des montants prévus --------------------------------------------------------------


def set_planned(
    session: Session, category_id: int, year: int, month: int, amount_cents: int
) -> None:
    """Fixe le montant prévu d'une catégorie pour un mois. Zéro efface la ligne."""
    _check_year(year)
    _check_month(month)
    require(session, Category, category_id, "Catégorie")
    if amount_cents < 0:
        raise InvalidError(
            "Le montant prévu ne peut pas être négatif : saisissez une dépense comme un "
            "montant positif (c'est le type de la catégorie qui fait la différence)"
        )
    line = session.scalars(
        select(BudgetLine).where(
            BudgetLine.category_id == category_id,
            BudgetLine.year == year,
            BudgetLine.month == month,
        )
    ).first()
    if amount_cents == 0:
        if line is not None:
            session.delete(line)
    elif line is None:
        session.add(
            BudgetLine(category_id=category_id, year=year, month=month, planned_cents=amount_cents)
        )
    else:
        line.planned_cents = amount_cents
    session.flush()


def fill_planned(
    session: Session, category_id: int, year: int, *, from_month: int, amount_cents: int
) -> None:
    """Applique le même montant de `from_month` (inclus) à décembre : recopier vers la droite."""
    _check_month(from_month)
    for month in range(from_month, 13):
        set_planned(session, category_id, year, month, amount_cents)


def copy_planned(session: Session, from_year: int, to_year: int, *, overwrite: bool = False) -> int:
    """Reprend les montants prévus d'une année dans une autre ; retourne le nombre écrit.

    Par défaut, les cases déjà renseignées de l'année cible ne sont pas touchées.
    """
    _check_year(from_year)
    _check_year(to_year)
    if from_year == to_year:
        raise InvalidError("L'année source et l'année cible doivent être différentes")
    source = session.scalars(select(BudgetLine).where(BudgetLine.year == from_year)).all()
    existing = {
        (line.category_id, line.month)
        for line in session.scalars(select(BudgetLine).where(BudgetLine.year == to_year))
    }
    written = 0
    for line in source:
        if (line.category_id, line.month) in existing and not overwrite:
            continue
        set_planned(session, line.category_id, to_year, line.month, line.planned_cents)
        written += 1
    return written


# --- Lecture : prévu et réalisé ---------------------------------------------------------------


def _planned_by_category(session: Session, year: int) -> dict[int, Months]:
    series: dict[int, list[int]] = {}
    for line in session.scalars(select(BudgetLine).where(BudgetLine.year == year)):
        series.setdefault(line.category_id, [0] * 12)[line.month - 1] = line.planned_cents
    return {category_id: tuple(values) for category_id, values in series.items()}


def _year_bounds(year: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


def _signed_by_category(session: Session, year: int) -> dict[int, Months]:
    """Somme signée des opérations par catégorie et par mois (virements exclus)."""
    first, last = _year_bounds(year)
    month = extract("month", Transaction.date)
    rows = session.execute(
        select(Transaction.category_id, month, func.sum(Transaction.amount_cents))
        .where(
            Transaction.date >= first,
            Transaction.date <= last,
            Transaction.transfer_peer_id.is_(None),
            Transaction.category_id.is_not(None),
        )
        .group_by(Transaction.category_id, month)
    )
    series: dict[int, list[int]] = {}
    for category_id, month_number, total in rows:
        if category_id is None:  # exclu par le WHERE, mais le typage l'ignore
            continue
        series.setdefault(category_id, [0] * 12)[int(month_number) - 1] = int(total)
    return {category_id: tuple(values) for category_id, values in series.items()}


def _uncategorized(session: Session, year: int) -> dict[CategoryKind, Months]:
    """Opérations sans catégorie, séparées par signe : recettes d'un côté, dépenses de l'autre."""
    first, last = _year_bounds(year)
    month = extract("month", Transaction.date)
    positive = func.sum(case((Transaction.amount_cents > 0, Transaction.amount_cents), else_=0))
    negative = func.sum(case((Transaction.amount_cents < 0, -Transaction.amount_cents), else_=0))
    rows = session.execute(
        select(month, positive, negative)
        .where(
            Transaction.date >= first,
            Transaction.date <= last,
            Transaction.transfer_peer_id.is_(None),
            Transaction.category_id.is_(None),
        )
        .group_by(month)
    )
    income = [0] * 12
    expense = [0] * 12
    for month_number, plus, minus in rows:
        income[int(month_number) - 1] = int(plus or 0)
        expense[int(month_number) - 1] = int(minus or 0)
    return {CategoryKind.INCOME: tuple(income), CategoryKind.EXPENSE: tuple(expense)}


def _realized(signed: Months, kind: CategoryKind) -> Months:
    """Réalisé d'une catégorie : une dépense compte positivement (opposé de la somme signée)."""
    return signed if kind is CategoryKind.INCOME else tuple(-value for value in signed)


def build_budget(session: Session, year: int, *, hide_empty_direct: bool = True) -> Budget:
    """Construit la grille de l'année : section Recettes, section Dépenses, puis le solde.

    `hide_empty_direct` masque les lignes « sans sous-catégorie » qui n'ont ni budget ni
    réalisé (elles encombreraient la grille pour rien).
    """
    _check_year(year)
    planned = _planned_by_category(session, year)
    signed = _signed_by_category(session, year)
    uncategorized = _uncategorized(session, year)
    roots = categories.list_root_categories(session)

    rows: list[BudgetRow] = []
    section_totals: dict[CategoryKind, tuple[Months, Months]] = {}

    for kind, title in ((CategoryKind.INCOME, "Recettes"), (CategoryKind.EXPENSE, "Dépenses")):
        rows.append(BudgetRow(RowKind.HEADER, title, kind, None))
        total_planned, total_actual = _ZERO, _ZERO

        for root in (r for r in roots if r.kind is kind):
            own_planned = planned.get(root.id, _ZERO)
            own_actual = _realized(signed.get(root.id, _ZERO), kind)

            if not root.children:
                rows.append(
                    BudgetRow(RowKind.CATEGORY, root.name, kind, root.id, own_planned, own_actual)
                )
                total_planned = _add(total_planned, own_planned)
                total_actual = _add(total_actual, own_actual)
                continue

            group_planned, group_actual = own_planned, own_actual
            child_rows: list[BudgetRow] = []
            for child in root.children:
                child_planned = planned.get(child.id, _ZERO)
                child_actual = _realized(signed.get(child.id, _ZERO), kind)
                child_rows.append(
                    BudgetRow(
                        RowKind.CHILD, child.name, kind, child.id, child_planned, child_actual
                    )
                )
                group_planned = _add(group_planned, child_planned)
                group_actual = _add(group_actual, child_actual)

            rows.append(
                BudgetRow(
                    RowKind.PARENT_TOTAL, root.name, kind, root.id, group_planned, group_actual
                )
            )
            rows.extend(child_rows)
            if not hide_empty_direct or any(own_planned) or any(own_actual):
                rows.append(
                    BudgetRow(
                        RowKind.DIRECT,
                        "(sans sous-catégorie)",
                        kind,
                        root.id,
                        own_planned,
                        own_actual,
                    )
                )
            total_planned = _add(total_planned, group_planned)
            total_actual = _add(total_actual, group_actual)

        loose = uncategorized[kind]
        if any(loose):
            rows.append(
                BudgetRow(RowKind.UNCATEGORIZED, "Non catégorisé", kind, None, _ZERO, loose)
            )
            total_actual = _add(total_actual, loose)

        label = "Total recettes" if kind is CategoryKind.INCOME else "Total dépenses"
        rows.append(
            BudgetRow(RowKind.SECTION_TOTAL, label, kind, None, total_planned, total_actual)
        )
        section_totals[kind] = (total_planned, total_actual)

    income_planned, income_actual = section_totals[CategoryKind.INCOME]
    expense_planned, expense_actual = section_totals[CategoryKind.EXPENSE]
    rows.append(
        BudgetRow(
            RowKind.BALANCE,
            "Solde (recettes - dépenses)",
            None,
            None,
            _sub(income_planned, expense_planned),
            _sub(income_actual, expense_actual),
        )
    )
    return Budget(year=year, rows=tuple(rows))
