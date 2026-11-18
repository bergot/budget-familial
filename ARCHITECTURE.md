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
| Migrations de schéma | Alembic | En place depuis l'étape 2, avant toute donnée réelle. |
| Gestion du projet | uv | Environnement, dépendances, verrouillage. |
| Tests | pytest | Base SQLite en mémoire. |
| Qualité du code | ruff (lint + format) | Un seul outil. Types vérifiés par mypy en mode strict (`uv run mypy`). |
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

**Conventions des services** (appliquées depuis l'étape 1) :

- Un service est une fonction qui reçoit la `Session` en premier paramètre.
- Un service fait `session.flush()` mais **ne fait jamais de commit** : l'appelant valide avec
  `with session.begin():` ou `session.commit()`. Plusieurs appels forment ainsi une seule
  transaction, annulée en bloc si l'un d'eux échoue.
- Les erreurs métier sont des exceptions qui héritent de `BudgetError`
  (`NotFoundError`, `DuplicateError`, `InvalidError`, dans `domain/errors.py`) ; l'interface
  les attrape pour afficher un message.
- Les données d'un formulaire entrent sous forme de `dataclass` immuable
  (`TransactionData`, `TransferData`) ; les identifiants (`account_id`...) sont passés, pas les
  objets ORM.
- Rien ne lit l'horloge en cachette : les fonctions qui dépendent de la date du jour
  acceptent un paramètre `today`, ce qui rend les tests déterministes.

**Conventions de l'interface** (appliquées depuis l'étape 2) :

- L'interface ouvre une session **courte** par action, avec `unit_of_work(factory)` (validée à
  la sortie du bloc, annulée sur exception). Elle ne garde jamais d'objets SQLAlchemy : après
  fermeture de la session ils sont détachés, et lire un attribut expiré lève
  `DetachedInstanceError`. Elle manipule des identifiants et des `dataclass`
  (`RegisterLine`, `AccountBalance`, `Choices`).
- Une `BudgetError` levée par un service est attrapée à un seul endroit (`MainWindow._run`)
  et affichée dans une boîte de dialogue ; le formulaire a déjà fait les vérifications de
  saisie, le service fait les vérifications métier.
- Les boîtes de dialogue (`QDialog`) ne touchent pas à la base : elles renvoient des valeurs
  (`values()`), et la fenêtre principale appelle les services. Exception : le dialogue des
  catégories, qui agit directement (chaque bouton valide aussitôt).
- La date « d'aujourd'hui » est injectée dans `MainWindow(today=...)`, comme pour les services.

---

## 4. Arborescence du dépôt

```
budget-familial/
├── pyproject.toml              # métadonnées, dépendances, ruff, mypy, pytest (géré par uv)
├── uv.lock                     # versions verrouillées (à versionner)
├── alembic.ini                 # développement seulement : créer de nouvelles migrations
├── budget-familial.spec        # construction de l'exécutable (PyInstaller)
├── LICENSE                     # MIT
├── README.md
├── ARCHITECTURE.md             # ce document
├── .github/workflows/ci.yml    # lint, types, tests, exécutables : Linux et Windows
├── packaging/launcher.py       # script de lancement pour PyInstaller
├── src/budget/
│   ├── __init__.py             # numéro de version
│   ├── __main__.py             # point d'entrée (option --base FICHIER)
│   ├── paths.py                # emplacement des données (pathlib + platformdirs)
│   ├── domain/
│   │   ├── enums.py            # ReconciliationStatus (none / pointed / reconciled)
│   │   ├── recurrence.py       # dates des échéances (fins de mois, sans dérive)
│   │   ├── errors.py           # BudgetError, NotFoundError, DuplicateError, InvalidError
│   │   └── money.py            # centimes <-> "12,50 €"
│   ├── db/
│   │   ├── base.py             # moteur, PRAGMA foreign_keys=ON, unit_of_work
│   │   ├── models.py           # tables
│   │   ├── migrate.py          # applique les migrations au démarrage
│   │   └── migrations/         # scripts Alembic (env.py, versions/0001, 0002...)
│   ├── services/
│   │   ├── accounts.py         # comptes, soldes
│   │   ├── categories.py
│   │   ├── lookups.py          # tiers, moyens de paiement
│   │   ├── transactions.py     # opérations, virements, registre
│   │   ├── reconciliation.py   # pointage, écart, validation, annulation
│   │   ├── schedules.py        # échéances et génération des opérations
│   │   └── choices.py          # listes de choix pour les formulaires
│   └── ui/
│       ├── app.py              # open_database (migrations, échéances), QApplication, boucle
│       ├── i18n.py             # Qt en français
│       ├── main_window.py      # fenêtre principale, menus, actions
│       ├── account_list.py     # liste des comptes (QTableView)
│       ├── register_view.py    # registre d'un compte (QTableView)
│       ├── models/             # QAbstractTableModel : account, register, pointing, schedule
│       └── dialogs/            # account, transaction, transfer, categories, reconciliation, schedules
└── tests/
    ├── conftest.py             # base SQLite en mémoire, comptes d'exemple
    ├── domain/  db/  services/ # tests sans Qt
    └── ui/                     # tests Qt (plugin « offscreen »), helpers de dialogues
```

L'agencement `src/` empêche d'importer par accident le code non installé et est
géré nativement par uv. Le budget s'ajoutera dans `services/` et `ui/` à l'étape suivante.

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
| `Schedule` | `id`, `account_id`, `payee_id`, `amount_cents`, `category_id`, `payment_method_id`, `notes`, `frequency`, `start_date`, `end_date` (nullable), `generated_count`, `transfer_account_id` (nullable) | `transfer_account_id` renseigné pour un virement planifié ; `generated_count` = occurrences déjà générées |
| `BudgetLine` | `id`, `category_id`, `year`, `month`, `planned_cents` | Unique sur (`category_id`, `year`, `month`) |

### Mise en œuvre par étapes

Les tables sont créées au fil des étapes, chacune avec sa migration Alembic.

| Étape | Tables et colonnes ajoutées | Migration |
|---|---|---|
| 1 | `Account`, `Category`, `Payee`, `PaymentMethod`, `Transaction` | `0001` |
| 3 | `Reconciliation` ; `Transaction.status` et `Transaction.reconciliation_id` | `0002` |
| 4 | `Schedule` ; `Transaction.schedule_id` | `0003` |
| 5 | `BudgetLine` | à venir |

Les tables portent des noms pluriels en base (`accounts`, `transactions`...). Dans le code,
l'attribut `date` de `Transaction` est annoté `dt.date` (avec `import datetime as dt`) pour
éviter qu'un attribut du même nom que son type ne trouble les annotations.

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
| `POINTED` | Cochée lors d'un rapprochement en cours (enregistrée aussitôt en base) |
| `RECONCILED` | Rapprochement validé : rattachée à une `Reconciliation`, **figée** |

### Points de vigilance SQLite

- Les clés étrangères sont **désactivées par défaut** : exécuter `PRAGMA foreign_keys=ON`
  à chaque connexion (dans `db/base.py`).
- Les dates sont stockées en type `DATE` (SQLAlchemy convertit vers/depuis `datetime.date`).
- Index à prévoir sur `Transaction(account_id, date)` pour le registre.

### Migrations du schéma (Alembic)

Le schéma est géré par Alembic. L'application applique les migrations toute seule au
démarrage (`db/migrate.py`) : base neuve = toutes les tables créées ; base existante = seules
les migrations manquantes, sans toucher aux données.

Pour modifier le schéma (nouvelle colonne, nouvelle table) :

1. Modifier `db/models.py`.
2. Créer la migration :
   ```bash
   rm -f dev.sqlite
   uv run alembic upgrade head                                   # base de développement à jour
   uv run alembic revision --autogenerate -m "ajout du pointage"
   ```
3. **Relire** le fichier généré dans `db/migrations/versions/` : la détection automatique
   se trompe parfois (renommages vus comme suppression + création, par exemple).
4. Lancer les tests : `tests/db/test_migrations.py` échoue si les migrations ne reproduisent
   pas exactement les modèles.

SQLite sait peu modifier une table existante : Alembic passe par le mode « batch » (il recrée
la table : copie, suppression, renommage). Cela a deux conséquences, traitées dans
`db/migrate.py` :

- **Les clés étrangères sont désactivées pendant la migration**, puis un `PRAGMA
  foreign_key_check` vérifie l'intégrité. Sans cela, la suppression de la table ancienne
  déclenchait l'action `ON DELETE SET NULL` de `transfer_peer_id` et **effaçait en silence le
  lien entre les deux moitiés de chaque virement**. Ce défaut a été trouvé par
  `test_upgrade_from_version_1_keeps_existing_data` : toute migration touchant une table
  existante doit être testée avec des données, pas seulement sur une base vide.
- **Le fichier de base est copié avant toute migration en attente** (`budget.sqlite.avant-0002.bak`
  à côté du fichier) : SQLite n'annule pas proprement un `ALTER` qui échoue en cours de route.

Autres points de vigilance : nommer les contraintes de clé étrangère (sinon le `downgrade`
ne peut pas les supprimer), donner un `server_default` aux nouvelles colonnes obligatoires
(les lignes existantes en ont besoin), et relire le fichier généré.

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
2. Il pointe les opérations présentes sur le relevé (`NONE` -> `POINTED`). Le pointage est
   enregistré à chaque case cochée : on peut fermer l'écran et reprendre plus tard.
3. Écart = solde du relevé - (solde rapproché + total des opérations pointées), où le solde
   rapproché = solde initial + opérations déjà rapprochées.
4. La validation n'est possible que si l'écart est nul et qu'au moins une opération est
   pointée ; les opérations passent alors à `RECONCILED`.

Règles associées :

- Chaque compte se rapproche séparément ; les deux moitiés d'un virement aussi.
- La date d'un relevé ne peut pas précéder celle du dernier rapprochement du compte.
- Une opération **rapprochée est figée** : modification et suppression refusées (virement
  compris, dès qu'une moitié est rapprochée).
- Seul le **dernier** rapprochement d'un compte peut être annulé (les soldes rapprochés se
  suivent en chaîne) ; ses opérations redeviennent non pointées et modifiables.
- Une opération pointée reste modifiable ; si on la change de compte, son pointage est remis à zéro.
- L'écran n'affiche que les opérations non rapprochées, jusqu'à la date du relevé (plus toutes
  celles déjà pointées) ; une case permet d'afficher les opérations postérieures.

### Échéances

Une échéance (`Schedule`) est un modèle d'opération ou de virement avec un rythme
(mensuelle, trimestrielle, annuelle), une date de début et une date de fin facultative.

**Dates.** La n-ième occurrence se calcule directement à partir de la date de début
(`domain/recurrence.py`), jamais à partir de la précédente : une échéance au 31 donne le
31 janvier, le 28 février, puis **de nouveau le 31 mars** (pas de dérive). Un 29 février annuel
se replie sur le 28 les années non bissextiles et revient le 29 les bissextiles.

**Génération.** Au lancement, `generate_due_transactions` crée les opérations jusqu'à un
horizon (3 mois par défaut, paramètre `horizon_months`), pour qu'elles apparaissent dans
le solde prévisionnel.

- **Pas de doublon** : le compteur `generated_count` avance dans la même transaction que la
  création des opérations ; relancer la génération ne recrée rien.
- **Rattrapage** : si l'application n'a pas été ouverte pendant des mois, toutes les occurrences
  manquantes sont créées. Une date de début passée provoque de même la création immédiate des
  occurrences passées (le formulaire le signale).
- **Indépendance** : une opération générée est une opération comme une autre (`schedule_id` ne
  garde que son origine). La modifier ou la supprimer ne touche pas l'échéance, et une
  opération supprimée n'est jamais recréée.
- **Virement planifié** : crée les deux moitiés liées, chacune avec `schedule_id` (cas du
  crédit mensuel SG vers Boursorama). Le montant est positif, le sens est « compte -> destination ».
- **Échéance impossible à générer** (compte clôturé par exemple) : ignorée et signalée à
  l'utilisateur, sans bloquer les autres ni perdre d'occurrence ; reprise automatiquement
  quand la cause disparaît.

**Modification.** Changer le modèle (montant, tiers, catégorie...) n'affecte que les opérations
futures ; celles déjà générées ne bougent pas. Une fois des opérations générées, la date de début
et la fréquence sont **verrouillées** (le décompte des occurrences deviendrait incohérent) :
pour changer de rythme, on termine l'échéance par une date de fin et on en crée une nouvelle.

**Suppression.** Supprimer une échéance conserve les opérations déjà générées (leur
`schedule_id` passe à NULL). Un compte ou une catégorie utilisés par une échéance ne peuvent pas
être supprimés.

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
3. **Cellules modifiables** : pour qu'une cellule puisse être cochée ou éditée, le modèle
   ajoute `flags()` (ex. `ItemIsUserCheckable`), répond au rôle `CheckStateRole` dans `data()`
   et implémente `setData()`, que Qt appelle quand l'utilisateur agit (voir `pointing_model.py`).
4. **Boucle d'événements** : `app.exec()` tourne tant que la fenêtre est ouverte.
   Aucune opération longue ne doit la bloquer (non critique à notre volume de données).
5. **Dialogues** : `QDialog` pour le formulaire de saisie, avec validation avant
   fermeture.
6. **Français uniquement** : les textes sont écrits directement en français ; pas de
   chaîne de traduction à gérer. Les formats de date et de nombre suivent la locale
   française.

---

## 9. Stratégie de tests

- **pytest**, avec une base SQLite **en mémoire** recréée pour chaque test
  (fixture dans `tests/conftest.py`).
- `domain` et `services` sont testés exhaustivement : soldes, virements liés,
  rapprochement (écart nul / non nul), génération d'échéances (fins de mois, années
  bissextiles, absence de doublons à la relance), calcul prévu/réalisé.
- L'interface est testée avec Qt en mode « offscreen » (sans écran, y compris en CI) :
  modèles Qt, formulaires, et fenêtre principale de bout en bout. Pour les boîtes de dialogue
  modales, `tests/ui/helpers.py` fournit `answer_next_dialog`, qui remplit les champs et clique
  sur les boutons dès que le dialogue s'affiche (le vrai `exec()` est donc exercé). La logique
  reste dans les services, testée sans Qt.
- **Hygiène des tests Qt** (`tests/ui/conftest.py`, `helpers.py`) : après chaque test, toutes
  les fenêtres sont fermées et détruites. Sans cela, elles survivent jusqu'à la sortie de Python,
  PySide détruit l'application Qt avant elles et le processus **plante en sortie** (segfault ou
  corruption de mémoire) : tous les tests passent mais le code de retour est non nul, donc la CI
  est rouge, de façon intermittente (l'ordre de destruction dépend de la graine de hachage).
  Les réponses de dialogue sont aussi surveillées : une assertion qui échoue dans l'une d'elles,
  ou une réponse jamais jouée, fait échouer le test (Qt se contenterait d'afficher l'exception).
  Quand plusieurs dialogues sont imbriqués, la réponse va au plus profond.
  Pour vérifier la stabilité : `for s in 1 2 3 4 5 6; do PYTHONHASHSEED=$s uv run pytest -q; echo $?; done`.
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

**Lancer l'application sur une base d'essai** (sans toucher à tes vraies données) :

```bash
uv run budget-familial --base /tmp/essai.sqlite
```

**Packaging** : `uv run pyinstaller --noconfirm budget-familial.spec` produit le dossier
`dist/budget-familial/`. Le fichier `.spec` déclare les migrations Alembic comme données :
ce sont des scripts chargés par chemin, que PyInstaller ne détecte pas tout seul.
PyInstaller ne produit pas d'exécutable pour un autre système que celui
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

### Étape 1 : modèle et logique métier (priorité : comptes) : terminée

- Moteur SQLite avec `PRAGMA foreign_keys=ON`, création du fichier de données.
- Modèles `Account`, `Category`, `Payee`, `PaymentMethod`, `Transaction`.
- Montants : conversion centimes / texte français (`domain/money.py`).
- Services : comptes (clôture, suppression refusée s'il y a des opérations), catégories à
  deux niveaux, tiers et moyens de paiement, opérations, **virements liés**, solde actuel et
  prévisionnel, registre avec solde cumulé.
- Tests unitaires et un scénario de bout en bout sur fichier SQLite.

**Livrable** : logique métier de base, entièrement testée, sans interface.

### Étape 2 : interface minimale (priorité : saisie) : terminée

- Fenêtre principale : liste des comptes avec soldes (actuel et prévisionnel) à gauche,
  registre du compte sélectionné à droite (`QTableView` + `QAbstractTableModel`).
- Formulaires : compte, opération (dépense ou recette, tiers avec auto-complétion),
  virement ; modification par double-clic ; suppression avec confirmation.
- Opérations à venir en gris italique ; virements libellés « depuis / vers » ; comptes clôturés
  masqués (affichables). Gestion des catégories et sous-catégories.
- Interface en français (Qt traduit : dates, boutons, menus contextuels).
- Alembic en place, base créée et migrée au premier lancement.

**Livrable** : première version utilisable au quotidien (comptes + saisie).

### Étape 3 : rapprochement (priorité : rapprochement) : terminée

- Table `Reconciliation`, statut de pointage des opérations, première migration sur base
  peuplée (`0002`), avec désactivation des clés étrangères pendant la migration et
  sauvegarde préalable du fichier.
- Service de rapprochement : pointage, écart, validation, annulation du dernier
  rapprochement, historique ; opérations rapprochées figées.
- Écran de rapprochement (cases à cocher, écart en direct, validation) ; colonne « R » dans le
  registre ; état du rapprochement affiché sous le titre du compte.

**Livrable** : rapprochement bancaire fonctionnel sur les deux banques.

### Étape 4 : échéances : terminée

- Table `Schedule` et lien `Transaction.schedule_id` (migration `0003`, testée sur une base
  peuplée : virements et rapprochements intacts).
- `domain/recurrence.py` : dates mensuelles, trimestrielles, annuelles, fins de mois sans dérive.
- Service : création et modification d'échéances, génération sans doublon avec rattrapage,
  échéances ignorées signalées.
- Écran de gestion des échéances ; génération au lancement (`open_database`) ; virement
  mensuel SG vers Boursorama pris en charge ; origine visible dans le registre (infobulle).

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
| Horizon des échéances | Durée de génération à l'avance | Paramètre `horizon_months` du service (3 mois) ; réglage dans l'interface à envisager à l'étape 6 |
| Sauvegarde | Perte du fichier de données | Sauvegardes automatiques à l'étape 6 ; d'ici là, copie manuelle |
