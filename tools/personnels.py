"""Outils MCP - domaine adultes (enseignants / personnels).

Chaque fonction execute une requete parametree (jamais de concatenation de
texte libre dans du SQL) sur la base SQLite consolidee et retourne un
resultat structure minimal. Lecture seule uniquement.

Perimetre : COM_PERSONNELS (enseignants et personnels de l'etablissement).
Ne couvre PAS COM_RESPONSABLES (parents/tuteurs des eleves) - un besoin
distinct, a traiter par une fonction dediee le jour ou il se presente.
"""

import sqlite3


def liste_personnels(
    conn: sqlite3.Connection,
    actifs_seulement: bool = True,
) -> list[dict]:
    """Liste des adultes (enseignants/personnels) avec IDPERSONNEL, nom, prenom.

    Sert de base fiable pour retrouver l'IDPERSONNEL d'un adulte a partir de
    son nom (ex. avant une affectation de photos ou un import externe),
    plutot que de deviner un appariement par nom sans verification.

    La particule (PE_PARTICULE) est exposee separement du nom : Charlemagne
    distingue les deux, et certains traitements (ex. affectation automatique
    des photos par nom de fichier) exigent explicitement que la particule
    n'apparaisse pas dans le nom utilise pour l'appariement.

    actifs_seulement : si True (par defaut), exclut les adultes ayant une
        PE_DATE_SORTIE renseignee.
    """
    cur = conn.cursor()

    query = """
        SELECT IDPERSONNEL, PE_NOM, PE_PRENOM, PE_PARTICULE, PE_TYPE, PE_DATE_SORTIE
        FROM COM_PERSONNELS
        WHERE 1=1
    """
    params: list[str] = []
    if actifs_seulement:
        query += " AND (PE_DATE_SORTIE IS NULL OR PE_DATE_SORTIE = '')"
    query += " ORDER BY PE_NOM, PE_PRENOM"

    rows = cur.execute(query, params).fetchall()
    return [
        {
            "id_personnel": row["IDPERSONNEL"],
            "nom": row["PE_NOM"],
            "prenom": row["PE_PRENOM"],
            "particule": row["PE_PARTICULE"] or None,
            "nom_prenom": f"{row['PE_NOM']} {row['PE_PRENOM']}",
            "type": row["PE_TYPE"],
            "actif": not bool(row["PE_DATE_SORTIE"]),
        }
        for row in rows
    ]
