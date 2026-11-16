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
