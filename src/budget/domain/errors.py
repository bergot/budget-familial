"""Exceptions métier.

Les services lèvent ces exceptions ; l'interface les attrape pour afficher un message
à l'utilisateur. Toutes héritent de `BudgetError`, ce qui permet d'écrire un seul
`except BudgetError` là où l'on veut tout intercepter.
"""


class BudgetError(Exception):
    """Erreur métier de base."""


class NotFoundError(BudgetError):
    """Un élément demandé (compte, catégorie, opération...) n'existe pas."""


class DuplicateError(BudgetError):
    """Un élément de même nom existe déjà."""


class InvalidError(BudgetError):
    """Une donnée ou une opération est refusée par les règles métier."""
