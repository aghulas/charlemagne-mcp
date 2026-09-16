"""
Loader idempotent : exports CSV Charlemagne (UTF-16-LE) -> base SQLite consolidee.

Remplace load_erp.py / load_erp_combined.py (racine, obsoletes) : ceux-ci videaient
et rechargeaient chaque table a chaque execution, perdant l'historique en cas
d'export partiel. Ici :

- Cle = premiere colonne de chaque CSV par defaut (convention WinDev "ID...",
  confirmee sur 20 tables tirees au hasard parmi les 618 de l'export reel).
  Quelques tables (typiquement les tables "HISTO", un enregistrement par
  eleve/famille et par evenement de facturation) n'ont pas de cle a colonne
  unique : leur cle composite est declaree dans COMPOSITE_KEYS ci-dessous,
  a completer au fur et a mesure des decouvertes (voir schema-dictionary.md).
- Upsert par cle (INSERT OR REPLACE) : jamais de vidage complet.
- Rapport de diff a chaque execution (ajouts / modifications / suppressions /
  inchangees par table), alerte si le schema (colonnes) d'une table a change.
- Aucun DDL requis : la structure de chaque table est deduite du CSV (colonnes
  TEXT). Si un vrai DDL apparait un jour, il pourra remplacer `ensure_table`.

Usage:
    python loader/load_charlemagne.py <dossier_csv> [--db chemin/vers/base.db]
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROWHASH_COL = "_rowhash"

# Tables ou la 1ere colonne du CSV n'est pas une cle fiable a elle seule.
# Decouvert en inspectant les doublons reels (cf. schema-dictionary.md) :
# ce sont des tables d'historique de facturation, une ligne par evenement
# de facturation (IDVALIDATION) et par famille/eleve.
COMPOSITE_KEYS = {
    "FAC_HISTO_FAMILLE": ["IDVALIDATION", "IDRESPONSABLE"],
    "FAC_COMPTA_FAMILLE": ["IDVALIDATION", "IDRESPONSABLE"],
    "FAC_HISTO_ELEVE": ["IDVALIDATION", "IDELEVE"],  # NB: encore 12 doublons residuels, voir schema-dictionary.md
    "COM_LIENER": ["IDRESPONSABLE", "IDELEVE"],  # table de liaison eleve <-> responsable(s)
    # Ajouts verifies (cf. schema-dictionary.md, section "18 tables ignorees") :
    # la 1ere colonne du CSV n'est pas la cle, ou une cle composite est necessaire.
    "COM_PERSONNELS": ["IDPERSONNEL"],  # 1ere colonne CSV = ID_UTILISATEUR, non fiable (doublons)
    "REC_ENVOI_ONDE": ["IDRECENVOIONDE"],
    "VS_EDITION_ZONES": ["IDZONE"],
    "FAC_GRILLE_COMPTE": ["GC_CODE", "IDCLASSE"],
    "FAC_GRILLE_PRIX": ["GP_CODE", "IDCLASSE"],
    "ADM_PROFIL": ["ID_UTILISATEUR", "PR_TYPE"],
    "REC_ENTREE_ELEVE": ["IDELEVE", "EE_DATE"],
    # Restent ignorees (cle non trouvee) : COM_PERSONNELS_ED (3e composante non
    # identifiee), FAC_COMPTA_GENERAL (probablement pas de cle naturelle, table
    # d'agregation multi-enfants), et les tables jamais encore testees :
    # ADM_ANC_CURSUS, ADM_LISTES_RUBRIQUES, ADM_STAT_RUBRIQUES, COM_BADGE,
    # COM_FORM_MULTIPLE, COM_LOGS, VS_EDITION_PARAM.
}


@dataclass
class TableReport:
    table: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    schema_changed: bool = False
    notes: list = field(default_factory=list)


def sanitize_columns(cols) -> list:
    return [c.strip().strip('"') for c in cols]


def compute_rowhash(df: pd.DataFrame, cols: list) -> pd.Series:
    def _hash(row):
        payload = "\x1f".join("" if v is None else str(v) for v in row)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return df[cols].apply(_hash, axis=1)


def load_csv(csv_path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(
            csv_path, sep=",", encoding="utf-16-le", dtype=str, on_bad_lines="skip"
        )
    except pd.errors.EmptyDataError:
        return None
    df.columns = sanitize_columns(df.columns)
    if df.empty or len(df.columns) == 0:
        return None
    return df


def resolve_key_cols(table: str, df: pd.DataFrame) -> list:
    declared = COMPOSITE_KEYS.get(table)
    if declared and all(c in df.columns for c in declared):
        return declared
    return [df.columns[0]]


def ensure_table(conn: sqlite3.Connection, table: str, key_cols: list, cols: list, report: TableReport) -> None:
    cur = conn.cursor()
    exists = (
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )

    if not exists:
        other_cols_def = [f'"{c}" TEXT' for c in cols if c not in key_cols]
        key_cols_def = [f'"{c}" TEXT' for c in key_cols]
        pk_clause = "PRIMARY KEY (" + ", ".join(f'"{c}"' for c in key_cols) + ")"
        parts = [*key_cols_def, *other_cols_def, f'"{ROWHASH_COL}" TEXT', pk_clause]
        conn.execute(f'CREATE TABLE "{table}" ({", ".join(parts)})')
        return

    existing_cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
    missing = [c for c in cols if c not in existing_cols]
    dropped = [c for c in existing_cols if c not in cols and c not in (ROWHASH_COL, *key_cols)]
    if missing or dropped:
        report.schema_changed = True
        if missing:
            report.notes.append(f"colonnes ajoutees dans le CSV : {missing}")
            for c in missing:
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}" TEXT')
        if dropped:
            report.notes.append(
                f"colonnes absentes du CSV mais presentes en base (conservees) : {dropped}"
            )


def upsert_table(conn: sqlite3.Connection, table: str, key_cols: list, df: pd.DataFrame, report: TableReport) -> None:
    cols = list(df.columns)
    df = df.copy()
    df[ROWHASH_COL] = compute_rowhash(df, cols)

    cur = conn.cursor()
    key_select = ", ".join(f'"{c}"' for c in key_cols)
    before = {}
    for row in cur.execute(f'SELECT {key_select}, "{ROWHASH_COL}" FROM "{table}"'):
        before[row[:-1]] = row[-1]

    key_tuples = list(df[key_cols].itertuples(index=False, name=None))
    staging_keys = set(key_tuples)
    added = changed = unchanged = 0
    for key, h in zip(key_tuples, df[ROWHASH_COL]):
        if key not in before:
            added += 1
        elif before[key] != h:
            changed += 1
        else:
            unchanged += 1
    removed = len(set(before) - staging_keys)

    col_list = ", ".join(f'"{c}"' for c in cols) + f', "{ROWHASH_COL}"'
    placeholders = ", ".join("?" for _ in cols) + ", ?"
    cur.executemany(
        f'INSERT OR REPLACE INTO "{table}" ({col_list}) VALUES ({placeholders})',
        df[cols + [ROWHASH_COL]].itertuples(index=False, name=None),
    )

    report.added, report.changed, report.unchanged, report.removed = added, changed, unchanged, removed


def print_report(reports: list, skipped_empty: list, skipped_bad_pk: list) -> None:
    total_added = sum(r.added for r in reports)
    total_changed = sum(r.changed for r in reports)
    total_removed = sum(r.removed for r in reports)
    total_unchanged = sum(r.unchanged for r in reports)

    print("=" * 70)
    print("RAPPORT DE CHARGEMENT")
    print("=" * 70)
    print(f"{len(reports)} tables chargees.")
    print(f"  + {total_added} lignes ajoutees")
    print(f"  ~ {total_changed} lignes modifiees")
    print(f"  = {total_unchanged} lignes inchangees")
    print(f"  - {total_removed} lignes en base absentes de cet export (conservees, non supprimees)")

    moved = [r for r in reports if r.added or r.changed or r.removed]
    if moved:
        print(f"\nTables avec mouvement ({len(moved)}) :")
        for r in sorted(moved, key=lambda r: -(r.added + r.changed + r.removed))[:30]:
            flag = " [schema modifie]" if r.schema_changed else ""
            print(f"  {r.table:<35} +{r.added:<6} ~{r.changed:<6} -{r.removed:<6}{flag}")
        if len(moved) > 30:
            print(f"  ... et {len(moved) - 30} autre(s)")

    schema_changed = [r for r in reports if r.schema_changed]
    if schema_changed:
        print(f"\nALERTE - {len(schema_changed)} table(s) avec changement de schema :")
        for r in schema_changed:
            for note in r.notes:
                print(f"  {r.table}: {note}")

    if skipped_bad_pk:
        print(f"\nALERTE - {len(skipped_bad_pk)} table(s) ignorees (cle non fiable - "
              f"valeurs nulles ou dupliquees, a investiguer et eventuellement declarer "
              f"dans COMPOSITE_KEYS) :")
        for t in skipped_bad_pk:
            print(f"  {t}")

    print(f"\n{len(skipped_empty)} table(s) vides ignorees.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_dir", help="Dossier contenant les CSV exportes par Charlemagne")
    parser.add_argument(
        "--db",
        default="data/administration_consolidee.db",
        help="Chemin de la base SQLite consolidee (par defaut data/administration_consolidee.db)",
    )
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    csv_files = sorted(csv_dir.glob("*.csv"))
    print(f"{len(csv_files)} fichier(s) CSV trouve(s) dans {csv_dir}")

    reports = []
    skipped_empty = []
    skipped_bad_pk = []

    for csv_path in csv_files:
        table = csv_path.stem
        df = load_csv(csv_path)
        if df is None:
            skipped_empty.append(table)
            continue

        key_cols = resolve_key_cols(table, df)
        # NB : on ne rejette plus sur la seule presence de valeurs nulles dans
        # les colonnes cle (ex. COM_PREFERENCES : cle (PREF_TYPE1, PREF_TYPE2)
        # fiable - 0 doublon - mais 2 lignes avec PREF_TYPE2 null). pandas
        # .duplicated() traite NaN == NaN comme egaux, donc une vraie collision
        # (deux lignes avec exactement la meme cle, null y compris) reste
        # detectee et la table reste ignoree dans ce cas.
        if df.duplicated(subset=key_cols).any():
            skipped_bad_pk.append(table)
            continue

        report = TableReport(table=table)
        ensure_table(conn, table, key_cols, list(df.columns), report)
        upsert_table(conn, table, key_cols, df, report)
        reports.append(report)
        conn.commit()

    print_report(reports, skipped_empty, skipped_bad_pk)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
