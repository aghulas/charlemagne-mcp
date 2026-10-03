"""Outils MCP - calendrier scolaire (jours de classe par mois).

Sources : VS_CONGE (un enregistrement par jour sans classe - week-ends,
mercredis, vacances, feries - avec IDCLASSE = 0 pour toute l'ecole) et
VS_TAB_PERIODES (trimestres T1-T3, semestres S1-S2, avec dates).
Les dates Charlemagne sont au format AAAAMMJJ.

Usage principal : prorata au mois des lignes de facturation (cantine,
garderie, etude) - voir la skill charlemagne-facturation et
FAC_GRILLE_PERIODE (mois factures par ligne). Lecture seule uniquement.
"""

import sqlite3
from datetime import date, timedelta

from tools.referentiels import table_existe


def _date(aaaammjj: str | None) -> date | None:
    if not aaaammjj or len(aaaammjj) < 8:
        return None
    return date(int(aaaammjj[0:4]), int(aaaammjj[4:6]), int(aaaammjj[6:8]))


def jours_de_classe(
    conn: sqlite3.Connection,
    id_classe: str | None = None,
) -> dict:
    """Nombre de jours de classe par mois sur l'annee scolaire couverte par
    VS_TAB_PERIODES (du debut de T1 a la fin de T3), d'apres VS_CONGE.

    id_classe : prend en plus en compte les conges propres a cette classe
        (IDCLASSE = id_classe) s'il en existe ; les conges IDCLASSE = 0
        (toute l'ecole) s'appliquent toujours.

    Retourne {"periodes": [...], "debut", "fin", "jours_par_mois": {"2026-09": 17, ...},
    "total", "nb_jours_sans_classe"}. Un dictionnaire vide est renvoye si les
    tables manquent.
    """
    if not (table_existe(conn, "VS_CONGE") and table_existe(conn, "VS_TAB_PERIODES")):
        return {}

    periodes = [
        {"code": r["CODE_PERIODE"], "debut": _date(r["DATE_DEBUT"]), "fin": _date(r["DATE_FIN"])}
        for r in conn.execute(
            "SELECT CODE_PERIODE, DATE_DEBUT, DATE_FIN FROM VS_TAB_PERIODES ORDER BY DATE_DEBUT"
        )
    ]
    periodes = [p for p in periodes if p["debut"] and p["fin"]]
    if not periodes:
        return {}
    debut = min(p["debut"] for p in periodes)
    fin = max(p["fin"] for p in periodes)

    query = "SELECT CO_JOUR FROM VS_CONGE WHERE IDCLASSE = '0' OR IDCLASSE = 0"
    params: list[str] = []
    if id_classe is not None:
        query += " OR IDCLASSE = ?"
        params.append(str(id_classe))
    sans_classe = {_date(r[0]) for r in conn.execute(query, params)}
    sans_classe.discard(None)

    jours_par_mois: dict[str, int] = {}
    total = 0
    jour = debut
    while jour <= fin:
        if jour not in sans_classe:
            cle = f"{jour.year:04d}-{jour.month:02d}"
            jours_par_mois[cle] = jours_par_mois.get(cle, 0) + 1
            total += 1
        jour += timedelta(days=1)

    return {
        "periodes": [
            {"code": p["code"], "debut": p["debut"].isoformat(), "fin": p["fin"].isoformat()}
            for p in periodes
        ],
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "jours_par_mois": jours_par_mois,
        "total": total,
        "nb_jours_sans_classe": sum(1 for j in sans_classe if debut <= j <= fin),
    }
