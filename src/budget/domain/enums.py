"""Énumérations métier."""

from enum import StrEnum


class ReconciliationStatus(StrEnum):
    """État d'une opération vis-à-vis du relevé bancaire.

    Un `StrEnum` est une énumération dont les membres sont aussi des chaînes : on peut
    comparer `status == "pointed"`, mais on écrit `status is ReconciliationStatus.POINTED`.
    """

    NONE = "none"  # pas encore vue sur un relevé
    POINTED = "pointed"  # cochée pendant un rapprochement en cours
    RECONCILED = "reconciled"  # rapprochement validé : l'opération est figée


class Frequency(StrEnum):
    """Fréquence d'une échéance."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @property
    def label(self) -> str:
        """Libellé français affiché dans l'interface."""
        return _FREQUENCY_LABELS[self]

    @property
    def months(self) -> int:
        """Nombre de mois entre deux occurrences."""
        return _FREQUENCY_MONTHS[self]


_FREQUENCY_LABELS = {
    Frequency.MONTHLY: "Mensuelle",
    Frequency.QUARTERLY: "Trimestrielle",
    Frequency.YEARLY: "Annuelle",
}
_FREQUENCY_MONTHS = {Frequency.MONTHLY: 1, Frequency.QUARTERLY: 3, Frequency.YEARLY: 12}


class CategoryKind(StrEnum):
    """Nature d'une catégorie : une dépense ou une recette.

    Le budget se saisit toujours avec des montants positifs ; c'est le type de la catégorie
    qui dit s'il s'agit d'une sortie ou d'une entrée d'argent.
    """

    EXPENSE = "expense"
    INCOME = "income"

    @property
    def label(self) -> str:
        return "Dépense" if self is CategoryKind.EXPENSE else "Recette"
