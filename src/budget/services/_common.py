"""Fonctions partagées par les services."""

from sqlalchemy.orm import Session

from budget.domain.errors import InvalidError, NotFoundError


def require[T](session: Session, model: type[T], id_: int, label: str) -> T:
    """Retourne l'objet `model` d'identifiant `id_`, ou lève `NotFoundError`.

    `[T]` (syntaxe Python 3.12+) déclare un type générique : si on passe `Account`,
    le résultat est typé `Account`, et l'éditeur le sait.
    """
    obj = session.get(model, id_)
    if obj is None:
        raise NotFoundError(f"{label} introuvable (id={id_})")
    return obj


def clean_name(name: str, label: str) -> str:
    """Retire les espaces superflus ; refuse un nom vide."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise InvalidError(f"{label} : le nom ne peut pas être vide")
    return cleaned
