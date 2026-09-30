"""Outils MCP - comparaison de deux exports Charlemagne.

A chaque nouvel export, la premiere question est « qu'est-ce qui a change depuis le
precedent ? ». Ce module compare la base servie au MCP a une archive (base SQLite
d'un export anterieur) et resume les changements utiles : volumes par table,
parametrage de la facturation (formules, lignes, grilles), fiches eleves /
responsables / foyers, liens eleve-responsable, informations complementaires, et
si la facturation en preparation a ete recalculee.

Lecture seule. Les donnees bancaires ne sont jamais renvoyees en clair : seul le
fait qu'elles soient renseignees ou non est indique.
"""

import hashlib
import re
import os
import sqlite3
from pathlib import Path

CHAMPS_MASQUES = {"RE_IBAN", "RE_BIC", "RE_COMPTE_BANQUE", "RE_CODE_BANQUE", "RE_CLE_RIB", "RE_CODE_GUICHET",
                  "RE_DOMICILIATION", "RE_TIRE"}
# Filet de securite par motif : tout champ bancaire (banque, guichet, RIB, IBAN, BIC,
# domiciliation, titulaire du compte « TIRE », mandat, RUM) ou numero de securite
# sociale est masque, meme s'il n'est pas liste ci-dessus. Le 30/09/2026, RE_DOMICILIATION
# et RE_TIRE sortaient en clair, et RE_GUICHET ne correspondait a aucune colonne reelle
# (la colonne s'appelle RE_CODE_GUICHET).
_MOTIF_MASQUE = re.compile(r"(^|_)(IBAN|BIC|BANQUE|GUICHET|RIB|DOMICILIATION|TIRE|NUM_?SECU|MANDAT|RUM)(_|$)")


def est_masque(champ: str) -> bool:
    return champ in CHAMPS_MASQUES or bool(_MOTIF_MASQUE.search(champ.upper()))


FICHES = (
    ("COM_ELEVES", "IDELEVE", "EL_NOM1", "EL_PRENOM1"),
    ("COM_RESPONSABLES", "IDRESPONSABLE", "RE_NOM1", "RE_PRENOM1"),
    ("COM_FOYER", "IDFOYER", None, None),
)
PARAMETRAGE = (
    ("FAC_FORMULE", ("ID_FORMULE",)),
    ("FAC_LIGNE", ("LI_CODE",)),
    ("FAC_GRILLE_PRIX", ("GP_CODE", "IDCLASSE", "GP_PERIODE")),
    ("FAC_GRILLE_COMPTE", ("GC_CODE", "IDCLASSE")),
    ("FAC_REM_FAMILLE", None),
    ("FAC_REM_ELEVE", None),
    ("FAC_REGIME", None),
    ("FAC_QUOTIENT", None),
)
MAX_DETAILS = 50


def lister_archives(dossier: str | None = None) -> list[str]:
    """Bases archivees disponibles (les plus recentes en dernier)."""
    d = Path(dossier or os.environ.get("CHARLEMAGNE_ARCHIVES_DIR", "data/archives"))
    if not d.is_dir():
        return []
    return sorted(str(p) for p in d.glob("*.db"))


def ouvrir_archive(chemin: str) -> sqlite3.Connection:
    p = Path(chemin)
    if not p.exists():
        raise ValueError(f"Archive introuvable : {chemin}")
    conn = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _colonnes(conn, table) -> list[str]:
    if table not in _tables(conn):
        return []
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]  # nom de table issu de sqlite_master / constante


def _compte(conn, table) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table in _tables(conn) else 0


def _valeur(champ, v):
    if est_masque(champ):
        return "renseigné" if str(v or "").strip() else "vide"
    v = "" if v is None else str(v)
    if v.startswith("{\\rtf"):
        return "(texte mis en forme)"
    return v if len(v) <= 80 else v[:77] + "..."


def _signature(conn, table) -> str | None:
    if table not in _tables(conn):
        return None
    h = hashlib.md5()
    for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2, 3'):
        h.update(repr(tuple(row)).encode())
    return h.hexdigest()[:12]


def comparer_exports(actuel: sqlite3.Connection, precedent: sqlite3.Connection) -> dict:
    """Resume les changements entre deux bases consolidees."""
    res: dict = {}
    # 1. volumes
    ta, tp = _tables(actuel), _tables(precedent)
    volumes = []
    for t in sorted(ta | tp):
        a, p = _compte(actuel, t), _compte(precedent, t)
        if a != p:
            volumes.append({"table": t, "avant": p, "apres": a})
    res["tables_modifiees"] = volumes

    # 2. parametrage de la facturation
    param = {}
    for table, cles in PARAMETRAGE:
        if table not in ta and table not in tp:
            continue
        ca, cp = _colonnes(actuel, table), _colonnes(precedent, table)
        cols = [c for c in ca if c in cp]
        if not cols:
            continue
        sel = ", ".join(f'"{c}"' for c in cols)
        ra = {tuple(r) for r in actuel.execute(f'SELECT {sel} FROM "{table}"')} if table in ta else set()
        rp = {tuple(r) for r in precedent.execute(f'SELECT {sel} FROM "{table}"')} if table in tp else set()
        if ra == rp:
            continue
        ajouts, retraits = sorted(ra - rp, key=str), sorted(rp - ra, key=str)
        param[table] = {
            "nb_ajouts": len(ajouts),
            "nb_retraits": len(retraits),
            "ajouts": [dict(zip(cols, (_valeur(c, v) for c, v in zip(cols, r)))) for r in ajouts[:MAX_DETAILS]],
            "retraits": [dict(zip(cols, (_valeur(c, v) for c, v in zip(cols, r)))) for r in retraits[:MAX_DETAILS]],
        }
    res["parametrage_facturation"] = param

    # 3. fiches eleves / responsables / foyers : champs modifies
    fiches = {}
    for table, cle, nom, prenom in FICHES:
        ca, cp = _colonnes(actuel, table), _colonnes(precedent, table)
        cols = [c for c in ca if c in cp and c != cle]
        if not cols:
            continue
        sel = ", ".join(f'"{c}"' for c in [cle] + cols)
        a = {r[0]: r for r in actuel.execute(f'SELECT {sel} FROM "{table}"')}
        p = {r[0]: r for r in precedent.execute(f'SELECT {sel} FROM "{table}"')}
        modifs, champs = [], {}
        for k, ra in a.items():
            rp = p.get(k)
            if rp is None or tuple(ra) == tuple(rp):
                continue
            diff = {c: {"avant": _valeur(c, rp[i + 1]), "apres": _valeur(c, ra[i + 1])}
                    for i, c in enumerate(cols) if ra[i + 1] != rp[i + 1]}
            for c, d in diff.items():
                if est_masque(c) and d["avant"] == d["apres"]:
                    d["apres"] += " (modifié)"  # valeur masquee changee : on le dit, sans la montrer
            if not diff:
                continue
            for c in diff:
                champs[c] = champs.get(c, 0) + 1
            libelle = " ".join(str(ra[cols.index(x) + 1] or "") for x in (nom, prenom) if x in cols) if nom else ""
            modifs.append({"id": k, "libelle": libelle.strip(), "champs": diff})
        nouveaux = [k for k in a if k not in p]
        supprimes = [k for k in p if k not in a]
        if modifs or nouveaux or supprimes:
            fiches[table] = {"nb_modifies": len(modifs), "champs_modifies": champs, "nouveaux": nouveaux[:MAX_DETAILS],
                             "supprimes": supprimes[:MAX_DETAILS], "details": modifs[:MAX_DETAILS]}
    res["fiches"] = fiches

    # 4. liens eleve-responsable (payeur, pourcentage, type de responsable)
    sel = "IDRESPONSABLE, IDELEVE, LER_TYPE_RESP, LER_VERSQUI, LER_POURCENTAGE"
    liens = []
    if {"COM_LIENER"} <= ta & tp:
        la = {(r[0], r[1]): tuple(r[2:]) for r in actuel.execute(f"SELECT {sel} FROM COM_LIENER")}
        lp = {(r[0], r[1]): tuple(r[2:]) for r in precedent.execute(f"SELECT {sel} FROM COM_LIENER")}
        for k in sorted(set(la) | set(lp)):
            if la.get(k) != lp.get(k):
                liens.append({"id_responsable": k[0], "id_eleve": k[1],
                              "avant": dict(zip(("type", "paie", "pourcentage"), lp.get(k) or ())),
                              "apres": dict(zip(("type", "paie", "pourcentage"), la.get(k) or ()))})
    res["liens_eleve_responsable"] = liens[:MAX_DETAILS]

    # 5. informations complementaires (eleves et responsables)
    infos = {}
    for table, cle in (("ADM_ICE_SAISIE", "IDELEVE"), ("ADM_ICR_SAISIE", "IDRESPONSABLE")):
        if table not in ta or table not in tp:
            continue
        ca = [c for c in _colonnes(actuel, table) if c in _colonnes(precedent, table)]
        val = [c for c in ca if "SAISIE" in c]
        idc = next((c for c in ca if c.startswith("ID_IC")), None)
        if not idc:
            continue
        sel = ", ".join([cle, idc] + val)
        a = {(r[0], r[1]): tuple(r[2:]) for r in actuel.execute(f"SELECT {sel} FROM {table}")}
        p = {(r[0], r[1]): tuple(r[2:]) for r in precedent.execute(f"SELECT {sel} FROM {table}")}
        ch = [{"id": k[0], "info": k[1], "avant": p.get(k), "apres": a.get(k)} for k in sorted(set(a) | set(p)) if a.get(k) != p.get(k)]
        if ch:
            infos[table] = {"nb": len(ch), "details": ch[:MAX_DETAILS]}
    res["informations_complementaires"] = infos

    # 6. facturation recalculee ?
    fac = {}
    for table in ("FAC_GESTION_LIGNE", "FAC_HISTO_LIGNE", "FAC_VALIDATION"):
        sa, sp = _signature(actuel, table), _signature(precedent, table)
        fac[table] = {"lignes_avant": _compte(precedent, table), "lignes_apres": _compte(actuel, table), "identique": sa == sp}
    res["facturation"] = fac
    if fac["FAC_GESTION_LIGNE"]["identique"] and param.get("FAC_FORMULE"):
        res["alerte"] = ("Les formules ont change mais la preparation de facturation est identique : "
                         "elle n'a pas ete relancee depuis ces changements.")
    return res
