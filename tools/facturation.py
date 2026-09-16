"""Outils MCP - domaine facturation.

Chaque fonction execute une requete parametree (jamais de concatenation de
texte libre dans du SQL) sur la base SQLite consolidee et retourne un
resultat structure minimal. Lecture seule uniquement.
"""

import sqlite3


def solde_eleve(conn: sqlite3.Connection, id_eleve: str) -> dict:
    """Solde d'un eleve, ventile par responsable lie (COM_LIENER).

    Un eleve peut avoir plusieurs responsables (ex. parents separes) ; en
    pratique un seul a en general des lignes de facturation dans
    FAC_COMPTA_FAMILLE - l'autre apparait alors avec 0 evenement, ce qui
    n'est pas une erreur. Le solde n'est jamais attribue a l'eleve seul :
    il est toujours rattache explicitement a un responsable nomme.
    """
    cur = conn.cursor()

    eleve = cur.execute(
        "SELECT IDELEVE, EL_NOM1, EL_PRENOM1 FROM COM_ELEVES WHERE IDELEVE = ?",
        (id_eleve,),
    ).fetchone()
    if eleve is None:
        raise ValueError(f"Aucun eleve avec IDELEVE={id_eleve!r}")

    responsables = cur.execute(
        """
        SELECT r.IDRESPONSABLE, r.RE_NOM1, r.RE_PRENOM1, r.RE_CODE_COMPTABLE,
               l.LER_TYPE_RESP, l.LER_LIEN
        FROM COM_LIENER l
        JOIN COM_RESPONSABLES r ON r.IDRESPONSABLE = l.IDRESPONSABLE
        WHERE l.IDELEVE = ?
        """,
        (id_eleve,),
    ).fetchall()

    par_responsable = []
    for resp in responsables:
        totals = cur.execute(
            """
            SELECT SUM(CAST(CF_DEBIT AS REAL)) AS total_debit,
                   SUM(CAST(CF_CREDIT AS REAL)) AS total_credit,
                   COUNT(*) AS nb_evenements
            FROM FAC_COMPTA_FAMILLE
            WHERE IDRESPONSABLE = ?
            """,
            (resp["IDRESPONSABLE"],),
        ).fetchone()
        total_debit = totals["total_debit"] or 0.0
        total_credit = totals["total_credit"] or 0.0
        par_responsable.append(
            {
                "id_responsable": resp["IDRESPONSABLE"],
                "responsable": f"{resp['RE_PRENOM1']} {resp['RE_NOM1']}",
                "lien": resp["LER_LIEN"],
                "code_comptable": resp["RE_CODE_COMPTABLE"],
                "nb_evenements_facturation": totals["nb_evenements"],
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "solde": round(total_debit - total_credit, 2),
            }
        )

    return {
        "id_eleve": eleve["IDELEVE"],
        "eleve": f"{eleve['EL_PRENOM1']} {eleve['EL_NOM1']}",
        "responsables": par_responsable,
        "note": (
            "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel. "
            "'Statut de facture' et 'impayes' ne sont pas encore fiables sur cette base "
            "(voir schema-dictionary.md) - ne pas les deduire de ce resultat."
        ),
    }
