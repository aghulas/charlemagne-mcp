"""Ecritures par compte et comparaison d'exercices, sur le FEC courant et les exercices clos.

Source : la base comptable (schema ``compta``) alimentee par loader/load_fec.py :
CPT_ECRITURE (periode courante, y compris le debut de l'exercice suivant tant qu'il n'est
pas ouvert) et CPT_ECRITURE_CLOS (un FEC par exercice clos). Les exercices sont rapportes
a la date d'ecriture : « 2024-2025 » = du 01/09/2024 au 31/08/2025.

Lecture seule. Confidentialite, comme pour le loader :
- le detail (libelle, ecriture par ecriture) n'est jamais donne pour les comptes de
  personnel et d'organismes sociaux (42x, 43x, 64x) ni pour les comptes familles (411) :
  seuls des totaux par compte ou par mois sont renvoyes ;
- les libelles des autres comptes sont ceux du FEC et peuvent contenir des noms
  (prestataires, parfois une personne) : a ne pas diffuser tels quels.

Les a-nouveaux (journal AN) sont exclus par defaut : sur les comptes de bilan ils doublent
le solde, sur les comptes 6 et 7 il n'y en a pas. Si le FEC d'un exercice clos contient des
ecritures de cloture (solde des comptes 6 et 7), les exclure avec ``exclure_journaux``.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict

MAX_COMPTES = 20
MAX_GROUPES = 300
MAX_ECRITURES = 300
PREFIXES_SANS_DETAIL = ("42", "43", "64", "411")
GROUPEMENTS = ("compte", "mois", "libelle", "ecriture")
JOURNAUX_A_NOUVEAUX = ("AN",)

MOIS = ["septembre", "octobre", "novembre", "decembre", "janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout"]

EXPR_EXERCICE = (
    "CASE WHEN substr(date_ecriture, 5, 2) >= '09' "
    "THEN substr(date_ecriture, 1, 4) || '-' || (CAST(substr(date_ecriture, 1, 4) AS INTEGER) + 1) "
    "ELSE (CAST(substr(date_ecriture, 1, 4) AS INTEGER) - 1) || '-' || substr(date_ecriture, 1, 4) END")
COLONNES = "journal, journal_lib, date_ecriture, compte, compte_lib, piece_ref, libelle, debit, credit, masquee"


def _a_des_clos(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM compta.sqlite_master WHERE type = 'table' AND name = 'CPT_ECRITURE_CLOS'"
                        ).fetchone() is not None


def _source(conn: sqlite3.Connection) -> str:
    sql = f"SELECT {EXPR_EXERCICE} AS exercice, {COLONNES} FROM compta.CPT_ECRITURE"
    if _a_des_clos(conn):
        sql += f" UNION ALL SELECT exercice, {COLONNES} FROM compta.CPT_ECRITURE_CLOS"
    return sql


def exercices_disponibles(conn: sqlite3.Connection) -> list[dict]:
    """Exercices charges, avec leur couverture (un exercice dont la derniere ecriture est avant aout est partiel)."""
    try:
        rows = conn.execute(
            f"SELECT exercice, MIN(date_ecriture), MAX(date_ecriture), COUNT(*) FROM ({_source(conn)}) "
            f"GROUP BY exercice ORDER BY exercice").fetchall()
        clos = {}
        if _a_des_clos(conn):
            clos = {r[0]: r[1] for r in conn.execute("SELECT exercice, charge_le FROM compta.CPT_EXPORT_CLOS")}
        courant = conn.execute("SELECT charge_le FROM compta.CPT_EXPORT").fetchone()
    except sqlite3.OperationalError as exc:
        raise ValueError("Base comptable absente ou vide : charger un FEC avec loader/load_fec.py.") from exc
    res = []
    for exercice, premiere, derniere, nb in rows:
        fin = exercice.split("-")[1]
        res.append({
            "exercice": exercice,
            "source": "clos" if exercice in clos else "courant",
            "premiere_ecriture": premiere,
            "derniere_ecriture": derniere,
            "nb_lignes": nb,
            "partiel": derniere < f"{fin}0801",
            "charge_le": clos.get(exercice) or (courant[0] if courant else None),
        })
    return res


def _exercices(conn: sqlite3.Connection, demandes: list[str] | str | None) -> list[dict]:
    dispo = exercices_disponibles(conn)
    if not dispo:
        raise ValueError("Aucune ecriture en base : charger un FEC avec loader/load_fec.py.")
    if not demandes:
        return dispo
    if isinstance(demandes, str):
        demandes = [d for d in re.split(r"[,; ]+", demandes) if d]
    voulus = []
    for d in demandes:
        d = d.strip().replace("/", "-")
        if not re.fullmatch(r"\d{4}-\d{4}", d) or int(d[5:]) != int(d[:4]) + 1:
            raise ValueError(f"Exercice invalide {d!r} : format AAAA-AAAA (ex. 2024-2025, du 01/09/2024 au 31/08/2025).")
        voulus.append(d)
    connus = {e["exercice"]: e for e in dispo}
    inconnus = [d for d in voulus if d not in connus]
    if inconnus:
        raise ValueError(f"Exercice(s) non charge(s) : {', '.join(inconnus)}. Disponibles : {', '.join(connus)}. "
                         f"Pour en ajouter : exporter le FEC de l'exercice (Compta > Outils > DGI/FEC) dans le "
                         f"dossier d'echange.")
    return [connus[d] for d in sorted(set(voulus))]


def _prefixes(comptes: list[str] | str | None) -> list[str]:
    if isinstance(comptes, str):
        comptes = [c for c in re.split(r"[,; ]+", comptes) if c]
    if not comptes:
        raise ValueError("Indiquer au moins un compte ou prefixe de compte (ex. '6064100', '606', '641').")
    if len(comptes) > MAX_COMPTES:
        raise ValueError(f"Trop de comptes ({len(comptes)}) : {MAX_COMPTES} au maximum.")
    res = []
    for c in comptes:
        c = str(c).strip()
        if not re.fullmatch(r"\d{1,8}", c):
            raise ValueError(f"Compte invalide {c!r} : chiffres seulement (numero ou debut de numero).")
        res.append(c)
    return res


def _sans_detail_sql() -> str:
    return " OR ".join(f"compte LIKE '{p}%'" for p in PREFIXES_SANS_DETAIL)


def _filtre(prefixes: list[str], exercices: list[dict], journal: str | None, exclure: list[str],
            detail: bool, recherche: str | None) -> tuple[str, list]:
    cond = ["(" + " OR ".join("compte LIKE ?" for _ in prefixes) + ")"]
    par = [p + "%" for p in prefixes]
    cond.append("exercice IN (" + ", ".join("?" for _ in exercices) + ")")
    par += [e["exercice"] for e in exercices]
    if journal:
        cond.append("journal = ?")
        par.append(journal.strip())
    if exclure:
        cond.append("journal NOT IN (" + ", ".join("?" for _ in exclure) + ")")
        par += exclure
    if detail:
        cond.append(f"masquee = 0 AND NOT ({_sans_detail_sql()})")
    if recherche:
        cond.append("libelle LIKE ?")
        par.append(f"%{recherche.strip()}%")
    return " AND ".join(cond), par


def _journaux_exclus(inclure_a_nouveaux: bool, exclure_journaux: list[str] | str | None) -> list[str]:
    if isinstance(exclure_journaux, str):
        exclure_journaux = [j for j in re.split(r"[,; ]+", exclure_journaux) if j]
    exclus = list(exclure_journaux or [])
    if not inclure_a_nouveaux:
        exclus += [j for j in JOURNAUX_A_NOUVEAUX if j not in exclus]
    return exclus


def _cle_libelle(libelle: str | None) -> str:
    s = re.sub(r"\(.*?\)", " ", libelle or "")
    s = re.sub(r"\d+(?:[/.\-]\d+)*", " ", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s or "(SANS LIBELLE)"


def _montant(debit: float, credit: float, classes: set[str]) -> float:
    """Sens naturel : produits (classe 7) = credit - debit ; charges et autres comptes = debit - credit."""
    return round(credit - debit, 2) if classes == {"7"} else round(debit - credit, 2)


def _avertissements(exercices: list[dict]) -> list[str]:
    av = [f"Exercice {e['exercice']} partiel (ecritures jusqu'au {e['derniere_ecriture']}) : ne pas le comparer "
          f"a un exercice complet." for e in exercices if e["partiel"]]
    return av


NOTE_SENS = ("montant : comptes de produits (7) = credit - debit ; charges (6) et autres comptes = debit - credit. "
             "A-nouveaux exclus par defaut.")


def ecritures_par_compte(conn: sqlite3.Connection, comptes, exercices=None, grouper_par: str = "compte",
                         recherche: str | None = None, journal: str | None = None,
                         inclure_a_nouveaux: bool = False, exclure_journaux=None,
                         limite: int = MAX_ECRITURES) -> dict:
    """Totaux ou detail des ecritures d'un ou plusieurs comptes, par exercice.

    grouper_par : compte (totaux par compte), mois (totaux par mois), libelle (totaux par libelle
    normalise, ex. par fournisseur), ecriture (une ligne par ecriture, limite lignes au plus).
    """
    if grouper_par not in GROUPEMENTS:
        raise ValueError(f"grouper_par invalide {grouper_par!r} : {', '.join(GROUPEMENTS)}.")
    if limite < 1:
        raise ValueError("limite doit etre >= 1.")
    prefixes = _prefixes(comptes)
    exs = _exercices(conn, exercices)
    exclus = _journaux_exclus(inclure_a_nouveaux, exclure_journaux)
    detail = grouper_par in ("libelle", "ecriture") or bool(recherche)
    where, par = _filtre(prefixes, exs, journal, exclus, detail, recherche)
    source = _source(conn)
    res: dict = {
        "comptes": prefixes, "exercices": [e["exercice"] for e in exs], "grouper_par": grouper_par,
        "filtres": {"recherche": recherche, "journal": journal, "journaux_exclus": exclus},
    }
    if detail:
        where_tous, par_tous = _filtre(prefixes, exs, journal, exclus, False, None)
        n_exclus = conn.execute(
            f"SELECT COUNT(*) FROM ({source}) WHERE {where_tous} AND (masquee = 1 OR {_sans_detail_sql()})",
            par_tous).fetchone()[0]
        if n_exclus:
            res["exclus_du_detail"] = (f"{n_exclus} ecritures de personnel / organismes sociaux / familles "
                                       f"(comptes {', '.join(PREFIXES_SANS_DETAIL)}) : detail non communique, "
                                       f"utiliser grouper_par='compte' ou 'mois' pour leurs totaux.")

    if grouper_par == "compte":
        rows = conn.execute(
            f"SELECT exercice, compte, MAX(compte_lib), SUM(debit), SUM(credit), COUNT(*) FROM ({source}) "
            f"WHERE {where} GROUP BY exercice, compte ORDER BY exercice, compte", par).fetchall()
        lignes = [{"exercice": e, "compte": c, "libelle_compte": lib, "debit": round(d, 2), "credit": round(cr, 2),
                   "montant": _montant(d, cr, {c[0]}), "nb": n} for e, c, lib, d, cr, n in rows]
    elif grouper_par == "mois":
        rows = conn.execute(
            f"SELECT exercice, substr(date_ecriture, 1, 6), SUM(debit), SUM(credit), COUNT(*), "
            f"GROUP_CONCAT(DISTINCT substr(compte, 1, 1)) FROM ({source}) WHERE {where} "
            f"GROUP BY exercice, substr(date_ecriture, 1, 6) ORDER BY substr(date_ecriture, 1, 6)", par).fetchall()
        lignes = [{"exercice": e, "mois": f"{m[:4]}-{m[4:]}", "debit": round(d, 2), "credit": round(cr, 2),
                   "montant": _montant(d, cr, set((cl or "").split(","))), "nb": n} for e, m, d, cr, n, cl in rows]
    else:
        brut = conn.execute(
            f"SELECT exercice, date_ecriture, journal, compte, piece_ref, libelle, debit, credit FROM ({source}) "
            f"WHERE {where} ORDER BY date_ecriture, compte", par).fetchall()
        if grouper_par == "libelle":
            groupes: dict[tuple, list] = defaultdict(lambda: [0.0, 0.0, 0, set(), "", ""])
            for e, d, j, c, p, lib, deb, cre in brut:
                g = groupes[(e, _cle_libelle(lib))]
                g[0] += deb
                g[1] += cre
                g[2] += 1
                g[3].add(c[0])
                g[4] = g[4] or d
                g[5] = d
            lignes = [{"exercice": e, "libelle": k, "debit": round(g[0], 2), "credit": round(g[1], 2),
                       "montant": _montant(g[0], g[1], g[3]), "nb": g[2], "premiere": g[4], "derniere": g[5]}
                      for (e, k), g in groupes.items()]
            lignes.sort(key=lambda x: (x["exercice"], -abs(x["montant"])))
        else:
            lignes = [{"exercice": e, "date": d, "journal": j, "compte": c, "piece": p, "libelle": lib,
                       "debit": deb, "credit": cre} for e, d, j, c, p, lib, deb, cre in brut]
    res["nb_lignes_totales"] = len(lignes)
    if len(lignes) > (limite if grouper_par == "ecriture" else MAX_GROUPES):
        cap = limite if grouper_par == "ecriture" else MAX_GROUPES
        lignes = lignes[:cap]
        res["tronque"] = f"{cap} premieres lignes seulement : restreindre les comptes, l'exercice ou la recherche."
    res["lignes"] = lignes

    tot = conn.execute(
        f"SELECT exercice, SUM(debit), SUM(credit), COUNT(*), GROUP_CONCAT(DISTINCT substr(compte, 1, 1)) "
        f"FROM ({source}) WHERE {where} GROUP BY exercice ORDER BY exercice", par).fetchall()
    res["totaux"] = {e: {"debit": round(d, 2), "credit": round(c, 2), "montant": _montant(d, c, set((cl or "").split(","))),
                         "nb": n} for e, d, c, n, cl in tot}
    res["exercices_disponibles"] = exercices_disponibles(conn)
    res["avertissements"] = _avertissements(exs)
    res["note"] = NOTE_SENS
    return res


def comparer_exercices_compta(conn: sqlite3.Connection, comptes, exercices=None, par: str = "compte",
                              inclure_a_nouveaux: bool = False, exclure_journaux=None) -> dict:
    """Compare des comptes d'un exercice a l'autre, par compte ou par mois de l'exercice (septembre -> aout)."""
    if par not in ("compte", "mois"):
        raise ValueError("par : 'compte' ou 'mois' (rang du mois dans l'exercice, septembre = 1).")
    prefixes = _prefixes(comptes)
    exs = _exercices(conn, exercices)
    if len(exs) < 2 and exercices:
        raise ValueError("Indiquer au moins deux exercices a comparer.")
    exclus = _journaux_exclus(inclure_a_nouveaux, exclure_journaux)
    where, par_sql = _filtre(prefixes, exs, None, exclus, False, None)
    source = _source(conn)
    cle = "compte" if par == "compte" else "CAST((CAST(substr(date_ecriture, 5, 2) AS INTEGER) + 3) % 12 AS INTEGER)"
    rows = conn.execute(
        f"SELECT {cle} AS cle, exercice, MAX(compte_lib), SUM(debit), SUM(credit), "
        f"GROUP_CONCAT(DISTINCT substr(compte, 1, 1)) FROM ({source}) WHERE {where} GROUP BY cle, exercice",
        par_sql).fetchall()
    noms = [e["exercice"] for e in exs]
    table: dict = {}
    for k, ex, lib, d, c, cl in rows:
        if par == "mois":
            k = int(k) + 1
        t = table.setdefault(k, {"lib": lib, "classes": set(), "val": {}})
        t["classes"] |= set((cl or "").split(","))
        t["val"][ex] = (d, c)
    lignes = []
    derniers = noms[-2:]
    for k in sorted(table):
        t = table[k]
        montants = {ex: (_montant(*t["val"][ex], t["classes"]) if ex in t["val"] else None) for ex in noms}
        ligne = {("compte" if par == "compte" else "rang_mois"): k}
        if par == "compte":
            ligne["libelle_compte"] = t["lib"]
        else:
            ligne["mois"] = MOIS[k - 1]
        ligne["montants"] = montants
        if len(derniers) == 2 and all(montants[x] is not None for x in derniers):
            a, b = montants[derniers[0]], montants[derniers[1]]
            ligne["ecart"] = round(b - a, 2)
            ligne["ecart_pct"] = round((b - a) / abs(a) * 100, 1) if a else None
        elif len(derniers) == 2:
            a, b = montants[derniers[0]] or 0.0, montants[derniers[1]] or 0.0
            ligne["ecart"] = round(b - a, 2)
            ligne["ecart_pct"] = None
        lignes.append(ligne)
    res = {"comptes": prefixes, "exercices": noms, "par": par, "ecart_entre": derniers if len(derniers) == 2 else None}
    res["nb_lignes_totales"] = len(lignes)
    if len(lignes) > MAX_GROUPES:
        lignes = lignes[:MAX_GROUPES]
        res["tronque"] = f"{MAX_GROUPES} premieres lignes seulement : restreindre les comptes."
    res["lignes"] = lignes
    classes = {t["classes"].copy().pop() for t in table.values() if len(t["classes"]) == 1}
    homogene = len(classes) == 1 and all(len(t["classes"]) == 1 for t in table.values())
    res["totaux"] = ({ex: round(sum(l["montants"][ex] or 0.0 for l in lignes), 2) for ex in noms}
                     if homogene and "tronque" not in res else None)
    res["exercices_disponibles"] = exercices_disponibles(conn)
    res["avertissements"] = _avertissements(exs)
    res["note"] = NOTE_SENS + ("" if res["totaux"] is not None else " Pas de total : comptes de classes ou de sens differents.")
    return res
