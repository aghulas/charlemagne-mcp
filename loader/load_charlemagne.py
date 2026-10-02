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
- Cle de secours : une table dont la cle (declaree ou 1ere colonne) a des
  doublons n'est plus ignoree ; elle est chargee avec une cle technique
  `_rowkey` = hash du contenu de la ligne + rang d'occurrence (les doublons
  exacts sont conserves : FAC_COMPTA_GENERAL en a 799 et ses sommes doivent
  rester justes). Sans identite stable, une ligne modifiee apparait comme
  une suppression + un ajout : ces tables sont donc *remplacees* (les lignes
  absentes de l'export sont supprimees), sinon PA_SUIVI_CONSOMMATEUR garderait
  l'ancien et le nouveau forfait d'un eleve.
- Upsert par cle (INSERT OR REPLACE) pour les autres tables : jamais de vidage
  complet, les lignes absentes de l'export sont conservees (export partiel).
  Exceptions, remplacees elles aussi : les tables de preparation de facturation
  (SNAPSHOT_TABLES), regenerees a chaque preparation dans Charlemagne, et toute
  table dont le CSV est present mais vide (la table est reellement vide dans
  Charlemagne : ex. FAC_GESTION_LIGNE apres validation).
- Un CSV vide (en-tete seul) cree quand meme la table : les tools ont besoin
  de la structure pour repondre proprement (« aucune preparation en cours »
  plutot que « no such table »).
- Rapport de diff a chaque execution (ajouts / modifications / suppressions /
  inchangees par table), alerte si le schema (colonnes) d'une table a change.
  Si la cle d'une table en base n'est plus celle attendue (ex. passage a la
  cle de secours), la table est reconstruite a partir de l'export.
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
ROWKEY_COL = "_rowkey"

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
    # Droits EcoleDirecte des adultes : ID_PERSO_ED est unique (362/362 lignes,
    # export du 30/09/2026) ; la 1ere colonne (IDPERSONNEL) ne l'est pas.
    "COM_PERSONNELS_ED": ["ID_PERSO_ED"],
    # Preferences : (type1, type2) unique (61/61), PREF_TYPE2 parfois nul.
    "COM_PREFERENCES": ["PREF_TYPE1", "PREF_TYPE2"],
    # Pieces recues : (lien personne, lien liste), cf. tools/famille.py.
    "COM_PIECE_RECU": ["ID_LIEN_PIECE_PERSONNE", "ID_LIEN_PIECE_LISTE"],
    # Forfaits d'activites (cantine, etude, garderie...) : une ligne par
    # activite et par eleve.
    "PA_SUIVI_CONSOMMATEUR": ["SI_CODE", "TYPE_PASSANT", "IDPASSANT"],
    # Sans cle naturelle connue -> cle de secours _rowkey automatiquement :
    # FAC_COMPTA_GENERAL (agregat comptable, doublons exacts legitimes),
    # FAC_GESTION_HISTO (lignes manuelles de la facturation complementaire),
    # COM_LOGS, ADM_ANC_CURSUS, ADM_LISTES_RUBRIQUES, ADM_STAT_RUBRIQUES,
    # COM_BADGE, COM_FORM_MULTIPLE, VS_EDITION_PARAM...
}

# Tables regenerees integralement par Charlemagne a chaque preparation de
# facturation : une ligne absente de l'export n'existe plus, on la supprime.
SNAPSHOT_TABLES = {
    "FAC_GESTION_ELEVE",
    "FAC_GESTION_FAMILLE",
    "FAC_GESTION_LIGNE",
    "FAC_GESTION_HISTO",
}


@dataclass
class TableReport:
    table: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    schema_changed: bool = False
    rebuilt: bool = False
    notes: list = field(default_factory=list)


def sanitize_columns(cols) -> list:
    return [c.strip().strip('"') for c in cols]


def compute_rowhash(df: pd.DataFrame, cols: list) -> pd.Series:
    def _hash(row):
        payload = "\x1f".join("" if v is None else str(v) for v in row)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    if df.empty:
        return pd.Series([], dtype=str)
    return df[cols].apply(_hash, axis=1)


def compute_rowkey(df: pd.DataFrame, cols: list) -> pd.Series:
    """Cle de secours : hash du contenu + rang d'occurrence (doublons exacts
    conserves et distingues : h#0, h#1...). Stable d'un export a l'autre tant
    que la ligne ne change pas."""
    h = compute_rowhash(df, cols)
    if df.empty:
        return h
    rang = h.groupby(h).cumcount()
    return h + "#" + rang.astype(str)


def load_csv(csv_path: Path) -> pd.DataFrame | None:
    """Lit un CSV d'export. Renvoie None si le fichier n'a meme pas d'en-tete ;
    un DataFrame vide (avec colonnes) si la table est exportee vide."""
    try:
        df = pd.read_csv(
            csv_path, sep=",", encoding="utf-16-le", dtype=str, on_bad_lines="skip"
        )
    except pd.errors.EmptyDataError:
        return None
    df.columns = sanitize_columns(df.columns)
    if len(df.columns) == 0:
        return None
    return df


def resolve_key_cols(table: str, df: pd.DataFrame) -> list:
    declared = COMPOSITE_KEYS.get(table)
    if declared and all(c in df.columns for c in declared):
        return declared
    return [df.columns[0]]


def existing_key_cols(conn: sqlite3.Connection, table: str) -> list | None:
    """Cle primaire de la table en base (None si la table n'existe pas)."""
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not info:
        return None
    return [r[1] for r in sorted((r for r in info if r[5] > 0), key=lambda r: r[5])]


def ensure_table(conn: sqlite3.Connection, table: str, key_cols: list, cols: list, report: TableReport) -> None:
    cur = conn.cursor()
    current_key = existing_key_cols(conn, table)

    if current_key is not None and current_key != key_cols:
        report.rebuilt = True
        report.notes.append(f"cle en base {current_key} differente de la cle attendue {key_cols} : table reconstruite")
        conn.execute(f'DROP TABLE "{table}"')
        current_key = None

    if current_key is None:
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


def upsert_table(conn: sqlite3.Connection, table: str, key_cols: list, df: pd.DataFrame,
                 report: TableReport, replace: bool = False) -> None:
    """Upsert par cle. Avec replace=True, les lignes en base absentes de
    l'export sont supprimees (tables sans identite stable, snapshots, CSV vide)."""
    cols = [c for c in df.columns if c != ROWKEY_COL]
    df = df.copy()
    df[ROWHASH_COL] = compute_rowhash(df, cols)

    cur = conn.cursor()
    key_select = ", ".join(f'"{c}"' for c in key_cols)
    before = {}
    for row in cur.execute(f'SELECT {key_select}, "{ROWHASH_COL}" FROM "{table}"'):
        before[row[:-1]] = row[-1]

    key_tuples = list(df[key_cols].itertuples(index=False, name=None)) if not df.empty else []
    staging_keys = set(key_tuples)
    added = changed = unchanged = 0
    for key, h in zip(key_tuples, df[ROWHASH_COL]):
        if key not in before:
            added += 1
        elif before[key] != h:
            changed += 1
        else:
            unchanged += 1
    absent = set(before) - staging_keys
    removed = len(absent)

    if not df.empty:
        insert_cols = [c for c in df.columns if c != ROWHASH_COL]
        col_list = ", ".join(f'"{c}"' for c in insert_cols) + f', "{ROWHASH_COL}"'
        placeholders = ", ".join("?" for _ in insert_cols) + ", ?"
        cur.executemany(
            f'INSERT OR REPLACE INTO "{table}" ({col_list}) VALUES ({placeholders})',
            df[insert_cols + [ROWHASH_COL]].itertuples(index=False, name=None),
        )
    if replace and absent:
        where = " AND ".join(f'"{c}" IS ?' for c in key_cols)
        cur.executemany(f'DELETE FROM "{table}" WHERE {where}', list(absent))
        report.notes.append(f"{removed} ligne(s) absente(s) de l'export supprimee(s)")

    report.added, report.changed, report.unchanged, report.removed = added, changed, unchanged, removed


def print_report(reports: list, skipped_no_header: list, rowkey_tables: list, empty_tables: list) -> None:
    total_added = sum(r.added for r in reports)
    total_changed = sum(r.changed for r in reports)
    total_removed = sum(r.removed for r in reports)
    total_unchanged = sum(r.unchanged for r in reports)
    total_deleted = sum(r.removed for r in reports if any("supprimee" in n for n in r.notes))

    print("=" * 70)
    print("RAPPORT DE CHARGEMENT")
    print("=" * 70)
    print(f"{len(reports)} tables chargees (dont {len(empty_tables)} vides, structure creee ou videe).")
    print(f"  + {total_added} lignes ajoutees")
    print(f"  ~ {total_changed} lignes modifiees")
    print(f"  = {total_unchanged} lignes inchangees")
    print(f"  - {total_removed} lignes en base absentes de cet export "
          f"({total_deleted} supprimees : tables remplacees ; {total_removed - total_deleted} conservees)")

    moved = [r for r in reports if r.added or r.changed or r.removed]
    if moved:
        print(f"\nTables avec mouvement ({len(moved)}) :")
        for r in sorted(moved, key=lambda r: -(r.added + r.changed + r.removed))[:30]:
            flag = " [schema modifie]" if r.schema_changed else ""
            flag += " [reconstruite]" if r.rebuilt else ""
            print(f"  {r.table:<35} +{r.added:<6} ~{r.changed:<6} -{r.removed:<6}{flag}")
        if len(moved) > 30:
            print(f"  ... et {len(moved) - 30} autre(s)")

    noted = [r for r in reports if r.schema_changed or r.rebuilt]
    if noted:
        print(f"\nALERTE - {len(noted)} table(s) avec changement de schema ou de cle :")
        for r in noted:
            for note in r.notes:
                if "supprimee" not in note:
                    print(f"  {r.table}: {note}")

    if rowkey_tables:
        print(f"\n{len(rowkey_tables)} table(s) chargee(s) avec la cle de secours _rowkey "
              f"(cle declaree ou 1ere colonne non unique ; lignes remplacees a chaque export) :")
        for t in rowkey_tables:
            print(f"  {t}")

    print(f"\n{len(skipped_no_header)} fichier(s) sans en-tete ignore(s).")


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
    skipped_no_header = []
    rowkey_tables = []
    empty_tables = []

    for csv_path in csv_files:
        table = csv_path.stem
        df = load_csv(csv_path)
        if df is None:
            skipped_no_header.append(table)
            continue

        key_cols = resolve_key_cols(table, df)
        replace = table in SNAPSHOT_TABLES or df.empty
        # NB : on ne rejette pas sur la seule presence de valeurs nulles dans
        # les colonnes cle (ex. COM_PREFERENCES : cle (PREF_TYPE1, PREF_TYPE2)
        # fiable - 0 doublon - mais 2 lignes avec PREF_TYPE2 null). pandas
        # .duplicated() traite NaN == NaN comme egaux, donc une vraie collision
        # (deux lignes avec exactement la meme cle, null y compris) est
        # detectee : la table passe alors a la cle de secours.
        if not df.empty and df.duplicated(subset=key_cols).any():
            df[ROWKEY_COL] = compute_rowkey(df, [c for c in df.columns if c != ROWKEY_COL])
            key_cols = [ROWKEY_COL]
            replace = True
            rowkey_tables.append(table)
        if df.empty:
            empty_tables.append(table)

        report = TableReport(table=table)
        ensure_table(conn, table, key_cols, [c for c in df.columns if c != ROWKEY_COL], report)
        upsert_table(conn, table, key_cols, df, report, replace=replace)
        reports.append(report)
        conn.commit()

    print_report(reports, skipped_no_header, rowkey_tables, empty_tables)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
