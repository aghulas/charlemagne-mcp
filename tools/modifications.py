"""Outils MCP - journal des modifications EcoleDirecte (COM_JOURNAL_MODIF).

COM_JOURNAL_MODIF consigne les modifications de fiches (eleve ou responsable)
faites dans Charlemagne et marquees "a traiter" pour EcoleDirecte : TYPE
(`Eleve_ATraiter` / `Resp_ATraiter`), TYPE_FICHIER, ID_CHARLEMAGNE (IDELEVE
ou IDRESPONSABLE), auteur Charlemagne (UTILISATEUR), horodatages de la
modification et de l'envoi (DATE_HEURE_ENVOI a zero = jamais envoye),
STATUT (`En attente`...). Sur l'export du 02/10/2026 : 6 lignes en attente
depuis fin aout, toutes non envoyees, DETAIL vide.

Interpretation a confirmer dans Charlemagne (module EcoleDirecte > journal
des modifications) : la table ressemble a la file des modifications
d'identite qui attendent un traitement cote EcoleDirecte ; l'outil expose
les faits (qui, quoi, quand, statut) sans trancher la cause.
Lecture seule uniquement.
"""

import sqlite3

from tools.referentiels import table_existe


def _date(valeur: str | None) -> str | None:
    """'20260831131848651' -> '2026-08-31 13:18:48' ; zero / vide -> None."""
    if not valeur or set(valeur) <= {"0"} or len(valeur) < 14:
        return None
    v = valeur
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"


def modifications_ecoledirecte_en_attente(
    conn: sqlite3.Connection,
    statut: str | None = "En attente",
) -> list[dict]:
    """Modifications de fiches consignees dans COM_JOURNAL_MODIF, avec le nom de
    la fiche concernee (eleve ou responsable).

    statut : filtre exact sur STATUT (par defaut 'En attente') ; None = tout
        le journal.
    """
    if not table_existe(conn, "COM_JOURNAL_MODIF"):
        return []
    query = """
        SELECT j.ID_JOURNAL_MODIF, j.TYPE, j.TYPE_FICHIER, j.ID_CHARLEMAGNE,
               j.DATE_HEURE_MODIF, j.DATE_HEURE_ENVOI, j.UTILISATEUR, j.STATUT, j.DETAIL,
               e.EL_NOM1, e.EL_PRENOM1, c.CL_LIBELLE,
               r.RE_NOM1, r.RE_PRENOM1
        FROM COM_JOURNAL_MODIF j
        LEFT JOIN COM_ELEVES e
               ON j.TYPE_FICHIER = 'ELEVE' AND e.IDELEVE = j.ID_CHARLEMAGNE
        LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
        LEFT JOIN COM_RESPONSABLES r
               ON j.TYPE_FICHIER = 'RESPONSABLE' AND r.IDRESPONSABLE = j.ID_CHARLEMAGNE
        WHERE 1=1
    """
    params: list[str] = []
    if statut is not None:
        query += " AND j.STATUT = ? COLLATE NOCASE"
        params.append(statut)
    query += " ORDER BY j.DATE_HEURE_MODIF"

    resultat = []
    for row in conn.execute(query, params):
        if row["TYPE_FICHIER"] == "ELEVE":
            fiche = f"{row['EL_NOM1'] or ''} {row['EL_PRENOM1'] or ''}".strip() or None
        elif row["TYPE_FICHIER"] == "RESPONSABLE":
            fiche = f"{row['RE_NOM1'] or ''} {row['RE_PRENOM1'] or ''}".strip() or None
        else:
            fiche = None
        resultat.append(
            {
                "id_journal": row["ID_JOURNAL_MODIF"],
                "type": row["TYPE"],
                "fichier": row["TYPE_FICHIER"],
                "id_charlemagne": row["ID_CHARLEMAGNE"],
                "fiche": fiche,
                "classe": row["CL_LIBELLE"],
                "modifie_le": _date(row["DATE_HEURE_MODIF"]),
                "envoye_le": _date(row["DATE_HEURE_ENVOI"]),
                "par": row["UTILISATEUR"],
                "statut": row["STATUT"],
                "detail": row["DETAIL"] or None,
            }
        )
    return resultat
