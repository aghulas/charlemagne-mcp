"""Outils MCP - domaine eleves (recherche / identification).

Chaque fonction execute une requete parametree (jamais de concatenation de
texte libre dans du SQL) sur la base SQLite consolidee et retourne un
resultat structure minimal. Lecture seule uniquement.
"""

import sqlite3


def liste_eleves(
    conn: sqlite3.Connection,
    classe: str | None = None,
    actifs_seulement: bool = True,
) -> list[dict]:
    """Liste des eleves avec IDELEVE, nom, prenom et classe.

    Sert de base fiable pour retrouver l'IDELEVE d'un eleve a partir de son
    nom (ex. avant un import externe cote Charlemagne), plutot que de
    deviner un appariement par nom sans verification.

    classe : filtre optionnel sur le libelle de classe (COM_CLASSES.CL_LIBELLE),
        comparaison exacte insensible a la casse. None = toutes les classes.
    actifs_seulement : si True (par defaut), exclut les eleves ayant une
        EL_DATE_SORTIE renseignee (sortis en cours d'annee sur l'export
        charge). Ne couvre PAS les anciens eleves : ceux-ci sont dans
        ADM_ANCIEN, un namespace d'IDANCIEN separe de IDELEVE (voir
        schema-dictionary.md) - cette fonction ne les interroge jamais.
    """
    cur = conn.cursor()

    query = """
        SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, e.EL_DATE_SORTIE,
               c.CL_LIBELLE
        FROM COM_ELEVES e
        LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
        WHERE 1=1
    """
    params: list[str] = []
    if actifs_seulement:
        query += " AND (e.EL_DATE_SORTIE IS NULL OR e.EL_DATE_SORTIE = '')"
    if classe:
        query += " AND c.CL_LIBELLE = ? COLLATE NOCASE"
        params.append(classe)
    query += " ORDER BY c.CL_LIBELLE, e.EL_NOM1, e.EL_PRENOM1"

    rows = cur.execute(query, params).fetchall()
    return [
        {
            "id_eleve": row["IDELEVE"],
            "nom": row["EL_NOM1"],
            "prenom": row["EL_PRENOM1"],
            "nom_prenom": f"{row['EL_NOM1']} {row['EL_PRENOM1']}",
            "classe": row["CL_LIBELLE"],
            "actif": not bool(row["EL_DATE_SORTIE"]),
        }
        for row in rows
    ]
