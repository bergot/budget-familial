# Architecture du projet : application de budget familial

> Document de référence du projet. Il décrit le périmètre, les choix techniques,
> l'architecture du code, le modèle de données et le déroulement du développement.
> Il évolue avec le projet : toute décision structurante doit y être consignée.

## Sommaire

1. [Objectif et périmètre](#1-objectif-et-périmètre)
2. [Choix techniques](#2-choix-techniques)
3. [Architecture en couches](#3-architecture-en-couches)
4. [Arborescence du dépôt](#4-arborescence-du-dépôt)
5. [Modèle de données](#5-modèle-de-données)
6. [Règles métier](#6-règles-métier)
7. [Idiomes Python modernes utilisés](#7-idiomes-python-modernes-utilisés)
8. [Notions Qt à connaître](#8-notions-qt-à-connaître)
9. [Stratégie de tests](#9-stratégie-de-tests)
10. [Environnement de développement (Linux)](#10-environnement-de-développement-linux)
11. [Plan de développement](#11-plan-de-développement)
12. [Risques et questions ouvertes](#12-risques-et-questions-ouvertes)

---

## 1. Objectif et périmètre

Application de bureau de gestion de budget familial, inspirée du noyau fonctionnel de
Grisbi. Usage quotidien, **un seul utilisateur**, **Linux et Windows**, interface
**en français uniquement**, **une seule devise (l'euro)**. Environ 50 opérations par
semaine, sur deux banques (Société Générale et Boursorama).

### Fonctions retenues

- Plusieurs comptes, chacun avec un solde initial.
- Opérations : date, tiers, montant, imputation (catégorie / sous-catégorie),
  moyen de paiement, notes. Saisie d'opérations futures.
- Virements entre comptes.
- Rapprochement bancaire (pointage par rapport au relevé).
- Opérations planifiées (échéances) : annuelle, trimestrielle, mensuelle,
  créées automatiquement.
- Budget : prévisionnel contre réel, recettes budgétées comme les dépenses,
  planification pluriannuelle sous forme de grille (imputations en lignes,
  mois en colonnes, saisie directe des montants prévus).

### Hors périmètre (décisions fermes)

- Pas de ventilation d'une opération sur plusieurs catégories.
- Pas de rapports.
- Pas de multi-devises.
- Pas d'import/export OFX pour l'instant (le modèle doit pouvoir l'accueillir plus tard).
- Pas de migration depuis Grisbi (`.gsb`).
- Pas de chiffrement du fichier de données.
- Pas de gestion de chéquiers pour Boursorama.

### Cartes à débit différé

Elles ne sont utilisées qu'avec le compte Boursorama. Les opérations sont saisies à
leur **date d'achat** ; seule cette date d'opération est suivie. Le prélèvement global
de fin de mois n'est **pas** géré : aucune logique spécifique n'est nécessaire.
Le compte Boursorama est alimenté chaque mois par un virement depuis le compte SG
(cas d'usage typique d'une échéance de virement).

### Ordre de priorité fonctionnelle

1. Comptes
2. Saisie des opérations
3. Rapprochement
4. Budget

Les échéances sont développées entre le rapprochement et le budget.

---

## 2. Choix techniques

| Domaine | Choix | Remarque |
|---|---|---|
| Langage | Python 3.14 | Voir la note de compatibilité ci-dessous. |
| Interface | PySide6 (Qt 6) | Licence LGPL, compatible avec un dépôt MIT. |
| Base de données | SQLite | Un seul fichier, simple à sauvegarder. |
| Accès aux données | SQLAlchemy 2.x (ORM) | Style moderne : `Mapped[...]`, `select()`. |
| Migrations de schéma | Alembic | Introduit à la fin de l'étape 2, avant les données réelles. |
| Gestion du projet | uv | Environnement, dépendances, verrouillage. |
| Tests | pytest | Base SQLite en mémoire. |
| Qualité du code | ruff (lint + format) | Un seul outil. Vérification de types optionnelle (pyright ou mypy). |
| Packaging | PyInstaller | Un build par système d'exploitation. |
| Intégration continue | GitHub Actions | Matrice Linux / Windows. |
| Licence | MIT | |
| Éditeur | Zed | |

**Note de compatibilité Python 3.14.** PyInstaller annonce le support de Python 3.14
depuis la version 6.15. PySide6 est disponible pour Python 3.14 dans les distributions
Linux (6.10.x). La disponibilité des wheels PyPI pour toutes les dépendances est à
valider dès l'étape 0 (`uv add PySide6 SQLAlchemy`). Plan B si une dépendance bloque :
épingler Python 3.13 sans rien changer d'autre au projet.

### Décisions structurantes

| Décision | Raison |
|---|---|
| Montants stockés en **centimes (entiers)** | Évite les erreurs d'arrondi des `float` (`0.1 + 0.2 != 0.3`). Alternative : `Decimal`, plus lourd à stocker en SQLite. |
| Montant **signé** (dépense < 0, recette > 0) | Le budget traite recettes et dépenses de la même façon. |
| **Solde calculé**, jamais stocké | Solde = solde initial + somme des opérations. Aucune désynchronisation possible. |
| Virement = **deux opérations liées** | Chaque compte voit son mouvement ; le service garantit la cohérence des deux côtés. |
| Logique métier dans des **services**, pas dans l'interface | Testable sans Qt ; interface remplaçable. |
| Échéances **générées au lancement** | Pas de tâche de fond ; les opérations créées restent modifiables individuellement. |

---

## 3. Architecture en couches

```
┌────────────────────────────┐
│ ui        (PySide6)        │  fenêtres, dialogues, modèles Qt
└─────────────┬──────────────┘
              │ appelle
┌─────────────▼──────────────┐
│ services  (logique métier) │  règles, calculs, transactions de base
└─────────────┬──────────────┘
              │ utilise
┌─────────────▼──────────────┐
│ db        (SQLAlchemy)     │  modèles, moteur, sessions
└────────────────────────────┘

domain : types et fonctions pures, utilisables par toutes les couches
```

**Règle de dépendance** : une couche ne connaît que celles situées en dessous d'elle.
L'interface n'écrit jamais de SQL ; les services n'importent jamais Qt ; `domain`
n'importe ni SQLAlchemy ni Qt.

| Couche | Responsabilité | Exemples |
|---|---|---|
| `domain` | Types purs, sans effet de bord | `Frequency`, calcul des prochaines échéances, formatage des montants |
| `db` | Persistance | Classes `Account`, `Transaction`, création du moteur, sessions |
| `services` | Cas d'usage métier | `create_transfer()`, `reconcile()`, `generate_due_transactions()`, `budget_grid()` |
| `ui` | Présentation | `MainWindow`, `RegisterView`, `TransactionDialog`, `BudgetGrid` |

Les services reçoivent une `Session` SQLAlchemy en paramètre. Les valeurs de retour
destinées à l'interface sont de simples `dataclass` immuables.

---

## 4. Arborescence du dépôt

```
budget-familial/
├── pyproject.toml            # métadonnées, dépendances (géré par uv)
├── uv.lock                   # versions verrouillées (à versionner)
├── LICENSE                   # MIT
├── README.md
├── ARCHITECTURE.md           # ce document
├── alembic.ini               # ajouté à l'étape 2
├── migrations/               # scripts de migration Alembic
├── .github/workflows/        # tests et builds Linux / Windows
├── src/budget/
│   ├── __init__.py
│   ├── __main__.py           # point d'entrée : python -m budget
│   ├── paths.py              # emplacement des données (pathlib + platformdirs)
│   ├── domain/
│   │   ├── enums.py          # Frequency, ReconciliationStatus
│   │   ├── money.py          # centimes <-> "12,50 €"
│   │   └── recurrence.py     # calcul des dates d'échéance
│   ├── db/
│   │   ├── base.py           # DeclarativeBase, moteur, PRAGMA foreign_keys=ON
│   │   └── models.py         # tables
│   ├── services/
│   │   ├── accounts.py
│   │   ├── categories.py
│   │   ├── transactions.py   # opérations et virements
│   │   ├── reconciliation.py
│   │   ├── schedules.py
│   │   └── budgets.py
│   └── ui/
│       ├── app.py            # QApplication, boucle d'événements
│       ├── main_window.py
│       ├── account_list.py
│       ├── register_view.py
│       ├── transaction_dialog.py
│       ├── reconciliation_view.py
│       ├── schedule_view.py
│       ├── budget_grid.py
│       └── models/           # sous-classes de QAbstractTableModel
└── tests/
    ├── conftest.py           # fixtures : session SQLite en mémoire
    ├── domain/
    └── services/
```

L'agencement `src/` empêche d'importer par accident le code non installé et est
géré nativement par uv.

---

## 5. Modèle de données

| Table | Colonnes principales | Contraintes |
|---|---|---|
| `Account` | `id`, `name`, `bank` (nullable), `initial_balance_cents`, `closed` | `name` unique |
| `Category` | `id`, `name`, `parent_id` (auto-référence, nullable) | Deux niveaux maximum : catégorie, sous-catégorie |
| `Payee` | `id`, `name` | `name` unique |
| `PaymentMethod` | `id`, `name` | `name` unique |
| `Transaction` | `id`, `account_id`, `date`, `payee_id`, `amount_cents` (signé), `category_id`, `payment_method_id`, `notes`, `status`, `reconciliation_id`, `transfer_peer_id`, `schedule_id` | Clés étrangères ; `transfer_peer_id` auto-référence |
| `Reconciliation` | `id`, `account_id`, `statement_date`, `statement_balance_cents` | |
| `Schedule` | `id`, `account_id`, `payee_id`, `amount_cents`, `category_id`, `payment_method_id`, `notes`, `frequency`, `start_date`, `end_date` (nullable), `last_generated_date`, `transfer_account_id` (nullable) | `transfer_account_id` renseigné pour un virement planifié |
| `BudgetLine` | `id`, `category_id`, `year`, `month`, `planned_cents` | Unique sur (`category_id`, `year`, `month`) |

### Relations

- Un `Account` possède plusieurs `Transaction`.
- Une `Category` peut avoir une `Category` parente.
- Un virement = deux `Transaction` (une par compte) reliées par `transfer_peer_id`.
- Une `Transaction` créée par une échéance garde le lien `schedule_id`.
- Une `Transaction` rapprochée est rattachée à une `Reconciliation`.

### Statut de pointage

Trois états, repris de la logique de Grisbi :

| Statut | Signification |
|---|---|
| `NONE` | Non pointée |
| `POINTED` | Cochée lors d'un rapprochement en cours |
| `RECONCILED` | Rapprochement validé (rattachée à une `Reconciliation`) |

### Points de vigilance SQLite

- Les clés étrangères sont **désactivées par défaut** : exécuter `PRAGMA foreign_keys=ON`
  à chaque connexion (dans `db/base.py`).
- Les dates sont stockées en type `DATE` (SQLAlchemy convertit vers/depuis `datetime.date`).
- Index à prévoir sur `Transaction(account_id, date)` pour le registre.

---

## 6. Règles métier

### Opérations et soldes

- Solde d'un compte = `initial_balance_cents` + somme des `amount_cents` de ses opérations.
- Les opérations futures comptent dans le « solde prévisionnel » ; le « solde actuel »
  ne retient que les opérations dont la date est passée ou égale à aujourd'hui.

### Virements

- Créer, modifier et supprimer un virement agit **toujours sur les deux opérations**,
  dans une seule transaction de base de données.
- Les deux montants sont opposés (`-x` sur le compte source, `+x` sur la destination).
- Un virement n'a pas de catégorie de dépense ou de recette.

### Rapprochement

1. L'utilisateur saisit la date et le solde du relevé.
2. Il pointe les opérations présentes sur le relevé (`NONE` → `POINTED`).
3. Écart = solde du relevé − (dernier solde rapproché + somme des opérations pointées).
4. La validation n'est possible que si l'écart est nul ; les opérations passent alors
   à `RECONCILED`.

### Échéances

- Fréquences : mensuelle, trimestrielle, annuelle.
- Au lancement de l'application, le service génère les opérations dues jusqu'à un
  horizon configurable (quelques mois), à partir de `last_generated_date`.
- Cas limite : une échéance fixée au 31 doit se replier sur le dernier jour des mois
  plus courts, sans dériver (le 31 janvier donne le 28 février, puis le 31 mars).
- Les opérations générées sont indépendantes : on peut les modifier ou les supprimer
  sans toucher à l'échéance.
- Une échéance peut être un virement (compte de destination renseigné).

### Budget

- Une ligne par catégorie ou sous-catégorie, par année et par mois.
- Recettes et dépenses sont traitées de la même façon (montants signés).
- Le « réalisé » est la somme des opérations de la période pour la catégorie.
- Le prévisionnel couvre l'année en cours et les suivantes.
- Les virements entre comptes sont exclus du réalisé.
- **Question ouverte** : le budget d'une catégorie parente est-il la somme de ses
  sous-catégories, ou saisi indépendamment ? À trancher à l'étape 5.

---

## 7. Idiomes Python modernes utilisés

### Typage

Toutes les fonctions publiques sont annotées. `str | None` (Python 3.10+) remplace
`Optional[str]`. Depuis Python 3.14, les annotations sont évaluées paresseusement.

```python
def balance(session: Session, account_id: int) -> int: ...
```

### SQLAlchemy 2.x

Déclaration des tables avec `DeclarativeBase`, `Mapped[...]` et `mapped_column()` :
SQLAlchemy lit les annotations pour construire les colonnes.

```python
from datetime import date
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    bank: Mapped[str | None]  # None => colonne nullable
    initial_balance_cents: Mapped[int] = mapped_column(default=0)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    date: Mapped[date]
    amount_cents: Mapped[int]  # signé
    notes: Mapped[str] = mapped_column(default="")

    account: Mapped[Account] = relationship(back_populates="transactions")
```

Requêtes avec `select()` (et non l'ancien `session.query`) :

```python
from sqlalchemy import select, func

total = session.scalar(
    select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.account_id == account_id
    )
)
```

Sessions et transactions : le bloc `begin()` valide à la sortie normale et annule
en cas d'exception.

```python
with Session(engine) as session, session.begin():
    session.add(Transaction(...))
```

### dataclasses

Pour transporter des valeurs entre services et interface :

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BudgetCell:
    category_id: int
    year: int
    month: int
    planned_cents: int
    actual_cents: int
```

`frozen=True` rend l'objet immuable ; `slots=True` réduit son empreinte mémoire ;
`__init__`, `__repr__` et `__eq__` sont générés automatiquement.

### Énumérations

```python
from enum import StrEnum


class Frequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
```

### pathlib

Chemins composés avec `/`, identiques sous Linux et Windows ; `platformdirs` fournit
le dossier de données propre à chaque système.

```python
from pathlib import Path
from platformdirs import user_data_path


def data_file() -> Path:
    folder = user_data_path("budget-familial", ensure_exists=True)
    return folder / "budget.sqlite"
```

---

## 8. Notions Qt à connaître

1. **Signaux et slots** : un widget émet un signal (`clicked`, `dataChanged`), une
   fonction (le slot) y réagit.
2. **Modèle / vue** : un `QTableView` n'affiche pas lui-même les données ; il interroge
   un `QAbstractTableModel` écrit par nos soins (`rowCount`, `columnCount`, `data`,
   et `setData` + `flags` pour l'édition). Ce mécanisme sert au registre et à la grille
   de budget.
3. **Boucle d'événements** : `app.exec()` tourne tant que la fenêtre est ouverte.
   Aucune opération longue ne doit la bloquer (non critique à notre volume de données).
4. **Dialogues** : `QDialog` pour le formulaire de saisie, avec validation avant
   fermeture.
5. **Français uniquement** : les textes sont écrits directement en français ; pas de
   chaîne de traduction à gérer. Les formats de date et de nombre suivent la locale
   française.

---

## 9. Stratégie de tests

- **pytest**, avec une base SQLite **en mémoire** recréée pour chaque test
  (fixture dans `tests/conftest.py`).
- `domain` et `services` sont testés exhaustivement : soldes, virements liés,
  rapprochement (écart nul / non nul), génération d'échéances (fins de mois, années
  bissextiles, absence de doublons à la relance), calcul prévu/réalisé.
- L'interface est testée à la marge (démarrage de la fenêtre, éventuellement
  `pytest-qt`) : la logique doit rester dans les services pour être testable sans Qt.
- Intégration continue : tests et lint à chaque push, sur Linux et Windows.
- Un test de non-régression est ajouté pour chaque bogue corrigé.

---

## 10. Environnement de développement (Linux)

Prérequis : Python 3.14, uv, git, éditeur Zed.

```bash
# Création du projet (disposition src/)
uv init --package budget-familial
cd budget-familial
uv python pin 3.14

# Dépendances d'exécution
uv add PySide6 SQLAlchemy platformdirs

# Dépendances de développement
uv add --dev pytest ruff pyinstaller

# Lancer l'application / les tests / le lint
uv run python -m budget
uv run pytest
uv run ruff check . && uv run ruff format .
```

**Dépendance système Qt sous Linux** : depuis Qt 6.5, le plugin d'affichage `xcb`
nécessite la bibliothèque `libxcb-cursor0` (Debian/Ubuntu ; nom voisin sur les autres
distributions). Si la fenêtre ne s'ouvre pas, l'erreur le mentionne :

```bash
sudo apt install libxcb-cursor0
```

**Packaging** : PyInstaller ne produit pas d'exécutable pour un autre système que celui
sur lequel il tourne. L'exécutable Linux se construit sous Linux, celui de Windows
sous Windows (en pratique via GitHub Actions).

---

## 11. Plan de développement

Chaque étape produit un résultat utilisable et testé avant de passer à la suivante.

### Étape 0 : mise en place

- Projet uv, structure `src/`, pytest, ruff, dépôt GitHub, licence MIT, README minimal.
- Validation de la compatibilité Python 3.14 des dépendances.
- Test de fumée : une fenêtre PySide6 vide, un exécutable PyInstaller fonctionnel sous
  Linux, puis sous Windows via GitHub Actions.

**Livrable** : squelette qui s'exécute, se teste et se package.

### Étape 1 : modèle et logique métier (priorité : comptes)

- Modèles `Account`, `Category`, `Payee`, `PaymentMethod`, `Transaction`.
- Services : comptes, catégories à deux niveaux, opérations, **virements liés**,
  solde actuel et prévisionnel.
- Moteur SQLite avec `PRAGMA foreign_keys=ON`, création du fichier de données.
- Tests unitaires complets.

**Livrable** : logique métier de base, entièrement testée, sans interface.

### Étape 2 : interface minimale (priorité : saisie)

- Fenêtre principale, liste des comptes avec soldes.
- Registre d'un compte : `QTableView` + `QAbstractTableModel`.
- Formulaire de saisie et de modification (`QDialog`), saisie d'opérations futures.
- Mise en place d'Alembic (migrations) avant la saisie des données réelles.

**Livrable** : première version utilisable au quotidien (comptes + saisie).

### Étape 3 : rapprochement (priorité : rapprochement)

- Modèle `Reconciliation` et statut de pointage.
- Service de rapprochement (calcul de l'écart, validation).
- Écran de rapprochement : saisie du relevé, pointage, validation.

**Livrable** : rapprochement bancaire fonctionnel sur les deux banques.

### Étape 4 : échéances

- Modèle `Schedule`, module `domain/recurrence.py` (dates, fins de mois).
- Génération automatique au lancement, sans doublons.
- Écran de gestion des échéances, y compris le virement mensuel SG → Boursorama.

**Livrable** : opérations récurrentes créées automatiquement.

### Étape 5 : budget (priorité : budget)

- Modèle `BudgetLine`, service de calcul prévu/réalisé.
- Grille éditable façon tableur : catégories en lignes, mois en colonnes, saisie directe
  des montants prévus, année en cours et suivantes.
- Décision sur le budget des catégories parentes (voir section 6).

**Livrable** : suivi budgétaire prévisionnel contre réel.

### Étape 6 : finitions

- Sauvegardes du fichier SQLite (copie horodatée, avec rotation).
- Packaging final Linux et Windows, icône, version affichée.
- README complet pour le dépôt public, documentation d'installation et d'utilisation.

**Livrable** : version publiable.

### Évolutions possibles (hors plan actuel)

- Import/export OFX avec détection de doublons.
- Rapports.

---

## 12. Risques et questions ouvertes

| Sujet | Risque / question | Réponse prévue |
|---|---|---|
| Python 3.14 | Une dépendance sans wheel pour 3.14 | Test à l'étape 0 ; repli sur Python 3.13 |
| Packaging | Comportement différent Linux / Windows | Build dans la CI dès l'étape 0 |
| Qt débutant | Courbe d'apprentissage du modèle/vue | Interface minimale d'abord ; logique isolée dans les services |
| Schéma de données | Évolutions une fois les données réelles saisies | Alembic dès la fin de l'étape 2 |
| Budget parent/enfant | Somme des sous-catégories ou saisie indépendante | À trancher à l'étape 5 |
| Horizon des échéances | Durée de génération à l'avance | Paramètre configurable, valeur par défaut de quelques mois |
| Sauvegarde | Perte du fichier de données | Sauvegardes automatiques à l'étape 6 ; d'ici là, copie manuelle |
