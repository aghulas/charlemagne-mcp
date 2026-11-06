"""
Loader du Fichier des Ecritures Comptables (FEC) de Charlemagne Comptabilite -> SQLite.

Le module Comptabilite de Charlemagne n'a ni export CSV de ses tables ni ligne de
commande (voir la cartographie compta du projet, par. 9.1) : la source retenue est
l'export natif *Outils > DGI/FEC*, fait a la main en session RDP, destinataire
« Non DGI (validees + non validees) », type Texte. Constats sur le fichier reel
(08/10/2026) :

- texte tabule, en-tete aux 18 noms de la norme DGFiP, encodage CP-1252, CRLF ;
- les lignes ont 19 champs : une 19e colonne « journal+piece » (ex. ``56+09-25/2``)
  sans nom dans l'en-tete ; ``EcritureNum`` et ``DateLet`` sont toujours vides et
  ``ValidDate`` vaut la date d'ecriture (le mode « Non DGI » n'est pas conforme a la
  norme - sans consequence ici) ;
- le nom du fichier porte la date de CLOTURE de l'exercice, pas la fin de la
  periode exportee : un export prolonge ecrase le precedent. La periode se lit
  donc dans le contenu ;
- avant l'ouverture de l'exercice suivant, ses ecritures sortent du meme dossier
  (periode prolongee au-dela de la cloture), sans a-nouveaux : les soldes sont
  cumules depuis le debut de l'exercice ouvert.

Le FEC est une photographie complete de la periode : chaque chargement REMPLACE
la table (idempotent par construction). La base est construite dans un fichier
temporaire puis substituee a l'ancienne.

Exercices clos (historique) : un FEC dont les ecritures s'arretent AVANT le debut de
la periode deja chargee (ex. l'exercice 2024-2025 quand la base commence au
01/09/2025) est range a part, dans CPT_ECRITURE_CLOS (colonne ``exercice``,
« 2024-2025 ») avec une ligne par exercice dans CPT_EXPORT_CLOS. Il remplace
uniquement son propre exercice et ne touche ni a CPT_ECRITURE ni aux outils de
suivi des familles (impayes, echeanciers), qui ne lisent que la periode courante.
Inversement, charger un nouveau FEC de la periode courante conserve les exercices
clos. Un FEC a cheval sur deux exercices ou desequilibre est refuse.

Confidentialite : les ecritures de paie (journal dont le libelle contient « PAIE »,
comptes 42x, 43x, 64x) sont chargees SANS libelle ni compte auxiliaire : seuls les
montants restent, pour les agregats. Le FEC ne contient aucune donnee bancaire.

Usage :
  python3 loader/load_fec.py <SIREN>FEC<AAAAMMJJ>.txt --db ~/Charlemagne/2026-2027/comptabilite_consolidee.db
  (defaut --db : CHARLEMAGNE_COMPTA_DB, sinon comptabilite_consolidee.db a cote de CHARLEMAGNE_DB,
  sinon data/comptabilite_consolidee.db - meme regle que le serveur, db/connection_compta.py)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_DB = "data/comptabilite_consolidee.db"

# Colonnes de la norme (arrete du 29 juillet 2013), dans l'ordre du fichier.
COLONNES_FEC = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum", "CompteLib",
    "CompAuxNum", "CompAuxLib", "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
    "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise",
]

# Prefixes de comptes dont le detail n'est jamais conserve (salaires, organismes sociaux).
PREFIXES_SENSIBLES = ("42", "43", "64")

DDL = """
CREATE TABLE CPT_ECRITURE (
    rang            INTEGER PRIMARY KEY,   -- numero de ligne dans le FEC (1 = premiere ecriture)
    journal         TEXT NOT NULL,
    journal_lib     TEXT,
    num_ecriture    TEXT,
    date_ecriture   TEXT NOT NULL,         -- AAAAMMJJ
    compte          TEXT NOT NULL,         -- compte general (collectif 4111000 pour les familles)
    compte_lib      TEXT,
    compte_aux      TEXT,                  -- compte auxiliaire (4111NOM = COM_RESPONSABLES.RE_CODE_COMPTABLE)
    compte_aux_lib  TEXT,
    piece_ref       TEXT,
    piece_date      TEXT,
    libelle         TEXT,
    debit           REAL NOT NULL,
    credit          REAL NOT NULL,
    lettrage        TEXT,
    date_lettrage   TEXT,
    date_validation TEXT,
    cle_piece       TEXT,                  -- 19e colonne Charlemagne : journal+piece
    masquee         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_cpt_aux ON CPT_ECRITURE (compte_aux);
CREATE INDEX ix_cpt_compte ON CPT_ECRITURE (compte);
CREATE INDEX ix_cpt_piece ON CPT_ECRITURE (journal, piece_ref, date_ecriture);
CREATE TABLE CPT_EXPORT (
    fichier          TEXT,
    sha256           TEXT,
    charge_le        TEXT,                 -- AAAA-MM-JJ HH:MM:SS
    periode_debut    TEXT,                 -- AAAAMMJJ (premiere ecriture)
    periode_fin      TEXT,                 -- AAAAMMJJ (derniere ecriture)
    nb_lignes        INTEGER,
    total_debit      REAL,
    total_credit     REAL,
    nb_lignes_masquees INTEGER
);
""" + """
CREATE TABLE CPT_ECRITURE_CLOS (            -- exercices clos : memes colonnes + exercice
    exercice        TEXT NOT NULL,         -- « 2024-2025 » (1er septembre -> 31 aout)
    rang            INTEGER NOT NULL,      -- numero de ligne dans le FEC de cet exercice
    journal         TEXT NOT NULL,
    journal_lib     TEXT,
    num_ecriture    TEXT,
    date_ecriture   TEXT NOT NULL,         -- AAAAMMJJ
    compte          TEXT NOT NULL,
    compte_lib      TEXT,
    compte_aux      TEXT,
    compte_aux_lib  TEXT,
    piece_ref       TEXT,
    piece_date      TEXT,
    libelle         TEXT,
    debit           REAL NOT NULL,
    credit          REAL NOT NULL,
    lettrage        TEXT,
    date_lettrage   TEXT,
    date_validation TEXT,
    cle_piece       TEXT,
    masquee         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (exercice, rang)
);
CREATE INDEX ix_cpt_clos_compte ON CPT_ECRITURE_CLOS (exercice, compte);
CREATE TABLE CPT_EXPORT_CLOS (
    exercice         TEXT PRIMARY KEY,
    fichier          TEXT,
    sha256           TEXT,
    charge_le        TEXT,
    periode_debut    TEXT,
    periode_fin      TEXT,
    nb_lignes        INTEGER,
    total_debit      REAL,
    total_credit     REAL,
    nb_lignes_masquees INTEGER
);
"""

DDL_CLOS = DDL[DDL.index("CREATE TABLE CPT_ECRITURE_CLOS"):]

COLONNES_ECRITURE = ["rang", "journal", "journal_lib", "num_ecriture", "date_ecriture", "compte", "compte_lib",
                     "compte_aux", "compte_aux_lib", "piece_ref", "piece_date", "libelle", "debit", "credit",
                     "lettrage", "date_lettrage", "date_validation", "cle_piece", "masquee"]
COLONNES_EXPORT = ["fichier", "sha256", "charge_le", "periode_debut", "periode_fin", "nb_lignes", "total_debit",
                   "total_credit", "nb_lignes_masquees"]


def exercice_de(aaaammjj: str) -> str:
    """Exercice comptable (1er septembre -> 31 aout) d'une date AAAAMMJJ : « 2024-2025 »."""
    annee, mois = int(aaaammjj[:4]), int(aaaammjj[4:6])
    debut = annee if mois >= 9 else annee - 1
    return f"{debut}-{debut + 1}"


def montant(valeur: str) -> float:
    v = (valeur or "").strip().replace(" ", "").replace(" ", "")
    if not v:
        return 0.0
    return float(v.replace(",", "."))


def lire_texte(chemin: Path) -> str:
    brut = chemin.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return brut.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Encodage non reconnu : {chemin}")


def sensible(journal_lib: str, compte: str) -> bool:
    return "PAIE" in (journal_lib or "").upper() or compte.startswith(PREFIXES_SENSIBLES)


def lire_fec(chemin: Path) -> list[dict]:
    """Lit un FEC et renvoie les ecritures normalisees (sans en-tete)."""
    texte = lire_texte(chemin).replace("\r\n", "\n").replace("\r", "\n")
    lignes = [l for l in texte.split("\n") if l.strip()]
    if not lignes:
        raise ValueError(f"FEC vide : {chemin}")
    sep = "\t" if "\t" in lignes[0] else "|"
    entete = [c.strip() for c in lignes[0].split(sep)]
    manquantes = [c for c in ("JournalCode", "EcritureDate", "CompteNum", "Debit", "Credit") if c not in entete]
    if manquantes:
        raise ValueError(f"En-tete FEC invalide, colonnes absentes : {manquantes}")
    pos = {nom: entete.index(nom) for nom in COLONNES_FEC if nom in entete}
    n = len(entete)
    ecritures = []
    for i, ligne in enumerate(lignes[1:], start=1):
        champs = ligne.split(sep)
        if len(champs) < n:
            champs += [""] * (n - len(champs))

        def g(nom: str) -> str:
            return champs[pos[nom]].strip() if nom in pos else ""

        e = {
            "rang": i,
            "journal": g("JournalCode"),
            "journal_lib": g("JournalLib"),
            "num_ecriture": g("EcritureNum"),
            "date_ecriture": g("EcritureDate"),
            "compte": g("CompteNum"),
            "compte_lib": g("CompteLib"),
            "compte_aux": g("CompAuxNum"),
            "compte_aux_lib": g("CompAuxLib"),
            "piece_ref": g("PieceRef"),
            "piece_date": g("PieceDate"),
            "libelle": g("EcritureLib"),
            "debit": montant(g("Debit")),
            "credit": montant(g("Credit")),
            "lettrage": g("EcritureLet"),
            "date_lettrage": g("DateLet"),
            "date_validation": g("ValidDate"),
            "cle_piece": champs[n].strip() if len(champs) > n else "",
            "masquee": 0,
        }
        if len(e["date_ecriture"]) != 8 or not e["date_ecriture"].isdigit():
            raise ValueError(f"Ligne {i + 1} : date d'ecriture invalide {e['date_ecriture']!r}")
        if sensible(e["journal_lib"], e["compte"]):
            e.update(libelle="", compte_aux="", compte_aux_lib="", masquee=1)
        ecritures.append(e)
    return ecritures


def resume(ecritures: list[dict]) -> dict:
    par_journal = defaultdict(lambda: {"lignes": 0, "debit": 0.0, "credit": 0.0, "lib": ""})
    for e in ecritures:
        j = par_journal[e["journal"]]
        j["lignes"] += 1
        j["debit"] += e["debit"]
        j["credit"] += e["credit"]
        j["lib"] = e["journal_lib"]
    dates = [e["date_ecriture"] for e in ecritures]
    return {
        "nb_lignes": len(ecritures),
        "periode_debut": min(dates) if dates else None,
        "periode_fin": max(dates) if dates else None,
        "total_debit": round(sum(e["debit"] for e in ecritures), 2),
        "total_credit": round(sum(e["credit"] for e in ecritures), 2),
        "nb_lignes_masquees": sum(e["masquee"] for e in ecritures),
        "par_journal": dict(par_journal),
    }


def precedent(db: Path) -> dict | None:
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(db)
        try:
            row = conn.execute("SELECT fichier, periode_debut, periode_fin, nb_lignes, total_debit "
                               "FROM CPT_EXPORT").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return dict(zip(("fichier", "periode_debut", "periode_fin", "nb_lignes", "total_debit"), row))


SEUIL_RECUL = 10   # au-dela, un FEC qui perd des ecritures recentes est un export borne trop tot


def ecritures_apres(db: Path, date_fin: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM CPT_ECRITURE WHERE date_ecriture > ?", (date_fin,)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _reprendre_clos(conn: sqlite3.Connection, ancienne: Path) -> None:
    """Recopie les exercices clos de la base remplacee dans la base en construction."""
    if not ancienne.exists():
        return
    conn.execute("ATTACH DATABASE ? AS ancienne", (str(ancienne),))
    try:
        tables = {t for (t,) in conn.execute("SELECT name FROM ancienne.sqlite_master WHERE type = 'table'")}
        if "CPT_ECRITURE_CLOS" in tables:
            cols = ", ".join(["exercice"] + COLONNES_ECRITURE)
            conn.execute(f"INSERT INTO CPT_ECRITURE_CLOS ({cols}) SELECT {cols} FROM ancienne.CPT_ECRITURE_CLOS")
        if "CPT_EXPORT_CLOS" in tables:
            cols = ", ".join(["exercice"] + COLONNES_EXPORT)
            conn.execute(f"INSERT INTO CPT_EXPORT_CLOS ({cols}) SELECT {cols} FROM ancienne.CPT_EXPORT_CLOS")
        conn.commit()
    finally:
        conn.commit()
        conn.execute("DETACH DATABASE ancienne")


def exercices_clos(db: Path) -> list[dict]:
    """Exercices clos deja charges (vide si la base n'en a pas ou n'existe pas)."""
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.execute("SELECT exercice, fichier, periode_debut, periode_fin, nb_lignes, charge_le "
                           "FROM CPT_EXPORT_CLOS ORDER BY exercice")
        return [dict(zip(("exercice", "fichier", "periode_debut", "periode_fin", "nb_lignes", "charge_le"), row))
                for row in cur]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def charger_clos(fec: Path, db: Path, ecritures: list[dict], r: dict, accepter_recul: bool = False) -> dict:
    """Range le FEC d'un exercice clos dans CPT_ECRITURE_CLOS, sans toucher a la periode courante."""
    exercices = sorted({exercice_de(e["date_ecriture"]) for e in ecritures})
    if len(exercices) != 1:
        raise ValueError(
            f"FEC a cheval sur plusieurs exercices ({', '.join(exercices)}) : exporter exercice par exercice "
            f"(du 01/09 au 31/08).")
    exercice = exercices[0]
    tmp = db.with_name(db.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    src = sqlite3.connect(db)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)                    # copie coherente, puis modification de la copie
        src.close()
        dst.executescript(DDL_CLOS.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS")
                          .replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS"))
        row = dst.execute("SELECT fichier, periode_debut, periode_fin, nb_lignes FROM CPT_EXPORT_CLOS "
                          "WHERE exercice = ?", (exercice,)).fetchone()
        avant = dict(zip(("fichier", "periode_debut", "periode_fin", "nb_lignes"), row)) if row else None
        if avant and not accepter_recul and r["nb_lignes"] < avant["nb_lignes"] - SEUIL_RECUL:
            raise ValueError(
                f"FEC de l'exercice {exercice} plus court que celui deja charge ({r['nb_lignes']} lignes contre "
                f"{avant['nb_lignes']}) : export incomplet ? Relancer avec --accepter-recul pour le remplacer.")
        dst.execute("DELETE FROM CPT_ECRITURE_CLOS WHERE exercice = ?", (exercice,))
        dst.execute("DELETE FROM CPT_EXPORT_CLOS WHERE exercice = ?", (exercice,))
        cols = ", ".join(["exercice"] + COLONNES_ECRITURE)
        dst.executemany(
            f"INSERT INTO CPT_ECRITURE_CLOS ({cols}) VALUES ({', '.join('?' * (len(COLONNES_ECRITURE) + 1))})",
            [(exercice, *(e[c] for c in COLONNES_ECRITURE)) for e in ecritures])
        dst.execute(
            "INSERT INTO CPT_EXPORT_CLOS (exercice, " + ", ".join(COLONNES_EXPORT) + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (exercice, fec.name, hashlib.sha256(fec.read_bytes()).hexdigest(),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["periode_debut"], r["periode_fin"], r["nb_lignes"],
             r["total_debit"], r["total_credit"], r["nb_lignes_masquees"]))
        dst.commit()
    except Exception:
        dst.close()
        tmp.unlink(missing_ok=True)
        raise
    dst.close()
    os.replace(tmp, db)
    r.update(exercice=exercice, clos=True, avant=avant)
    return r


def charger(fec: Path, db: Path, accepter_recul: bool = False) -> dict:
    ecritures = lire_fec(fec)
    r = resume(ecritures)
    if abs(r["total_debit"] - r["total_credit"]) > 0.01:
        raise ValueError(f"FEC desequilibre : debit {r['total_debit']} / credit {r['total_credit']}")
    avant = precedent(db)
    if avant and avant["periode_debut"] and r["periode_fin"] and r["periode_fin"] < avant["periode_debut"]:
        # exercice entierement anterieur a la periode chargee : historique, range a part
        return charger_clos(fec, db, ecritures, r, accepter_recul=accepter_recul)
    if avant and not accepter_recul and r["periode_fin"]:
        # Le FEC ne contient pas la periode demandee, seulement les ecritures : la derniere peut
        # reculer legitimement (ecriture recente supprimee). Un export borne trop tot (l'ecran
        # DGI/FEC propose la fin de l'exercice) se reconnait aux ecritures deja chargees qu'il perd.
        perdues = ecritures_apres(db, r["periode_fin"])
        if perdues > SEUIL_RECUL:
            raise ValueError(
                f"FEC plus court que celui deja charge : ecritures jusqu'au {r['periode_fin']}, alors que "
                f"{perdues} ecritures deja chargees sont posterieures (jusqu'au {avant['periode_fin']}). "
                f"Refaire l'export jusqu'a la date du jour (periode par defaut de l'ecran DGI/FEC = fin de "
                f"l'exercice) ou relancer avec --accepter-recul.")
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(db.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(DDL)
        _reprendre_clos(conn, db)          # les exercices clos survivent au rechargement de la periode courante
        cols = list(ecritures[0].keys()) if ecritures else []
        if ecritures:
            conn.executemany(
                f"INSERT INTO CPT_ECRITURE ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [tuple(e[c] for c in cols) for e in ecritures])
        conn.execute(
            "INSERT INTO CPT_EXPORT VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fec.name, hashlib.sha256(fec.read_bytes()).hexdigest(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             r["periode_debut"], r["periode_fin"], r["nb_lignes"], r["total_debit"], r["total_credit"],
             r["nb_lignes_masquees"]))
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, db)
    r["avant"] = avant
    return r


def main() -> int:
    parser = argparse.ArgumentParser(description="Charge un FEC Charlemagne dans une base SQLite (remplacement complet).")
    parser.add_argument("fec", help="Fichier FEC (<SIREN>FEC<AAAAMMJJ>.txt)")
    defaut = os.environ.get("CHARLEMAGNE_COMPTA_DB") or (
        str(Path(os.environ["CHARLEMAGNE_DB"]).expanduser().parent / "comptabilite_consolidee.db")
        if os.environ.get("CHARLEMAGNE_DB") else DEFAULT_DB)
    parser.add_argument("--db", default=defaut,
                        help="Base SQLite a (re)creer (defaut : CHARLEMAGNE_COMPTA_DB, sinon a cote de CHARLEMAGNE_DB)")
    parser.add_argument("--accepter-recul", action="store_true",
                        help="charger meme si la periode s'arrete avant celle du FEC deja charge")
    args = parser.parse_args()
    fec, db = Path(args.fec).expanduser(), Path(args.db).expanduser()
    try:
        r = charger(fec, db, accepter_recul=args.accepter_recul)
    except (OSError, ValueError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    if r.get("clos"):
        print(f"FEC d'exercice clos charge : {fec.name} -> {db} (exercice {r['exercice']})")
    else:
        print(f"FEC charge : {fec.name} -> {db}")
    print(f"  periode {r['periode_debut']} -> {r['periode_fin']}, {r['nb_lignes']} lignes, "
          f"debit = credit = {r['total_debit']:.2f}, {r['nb_lignes_masquees']} lignes de paie sans detail")
    for code, j in sorted(r["par_journal"].items()):
        print(f"  {code:6} {j['lib'][:28]:28} {j['lignes']:6} lignes  {j['debit']:14.2f}")
    a = r["avant"]
    if a:
        print(f"  chargement precedent : {a['fichier']}, {a['periode_debut']} -> {a['periode_fin']}, "
              f"{a['nb_lignes']} lignes ({r['nb_lignes'] - a['nb_lignes']:+d})")
    clos = exercices_clos(db)
    if clos:
        print("  exercices clos en base : " + ", ".join(f"{c['exercice']} ({c['nb_lignes']} lignes)" for c in clos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
