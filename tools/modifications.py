"""Outils MCP - journal des fiches a envoyer vers EcoleDirecte (COM_JOURNAL_MODIF).

COM_JOURNAL_MODIF est la file de SORTIE de Charlemagne vers EcoleDirecte : chaque
fiche (eleve ou responsable) modifiee dans Charlemagne y est inscrite "a traiter"
(TYPE `Eleve_ATraiter` / `Resp_ATraiter`) avec l'utilisateur Charlemagne qui a
modifie (UTILISATEUR), l'horodatage de la modification et celui de l'envoi
(DATE_HEURE_ENVOI a zero = jamais envoye), STATUT (`En attente`...). Les lignes
envoyees par la synchronisation (19h15 ou manuelle) sont supprimees ; la table
n'est pas repliquee vers EcoleDirecte (absente de Replica_EtablissementAD.rpm).

Interpretation etablie le 03/10/2026 : les deux lignes `Resp_ATraiter` du 23/09
correspondent a la validation dans Charlemagne de demandes de telephone envoyees
par le connecteur quatre minutes plus tot (plus aucune demande en attente cote
EcoleDirecte, numeros a jour) ; les six lignes restantes concernent toutes des
eleves sortis ou une inscription annulee, hors perimetre de la synchronisation,
donc jamais envoyees. Ce n'est PAS la file des demandes entrantes des familles
(celle-ci se lit dans la console EcoleDirecte, tool `ed_admin_demande_*`).

Usage : reperer les fiches modifiees pas encore parties vers EcoleDirecte et
expliquer pourquoi (`motif_probable`). Lecture seule uniquement.
"""

import datetime as dt
import sqlite3

from tools.referentiels import table_existe


def _date(valeur: str | None) -> str | None:
    """'20260831131848651' -> '2026-08-31 13:18:48' ; zero / vide -> None."""
    if not valeur or set(valeur) <= {"0"} or len(valeur) < 14:
        return None
    v = valeur
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"


def _jour(valeur: str | None) -> str | None:
    """'20260704' -> '2026-07-04' ; zero / vide -> None."""
    if not valeur or set(valeur) <= {"0"} or len(valeur) < 8:
        return None
    return f"{valeur[0:4]}-{valeur[4:6]}-{valeur[6:8]}"


def _eleve_sorti(date_sortie: str | None, aujourd_hui: str) -> bool:
    """Vrai si la date de sortie (AAAAMMJJ) est renseignee et deja passee."""
    return bool(date_sortie) and not set(date_sortie) <= {"0"} and date_sortie[:8] <= aujourd_hui


def _motif_responsable(conn: sqlite3.Connection, id_resp: str, aujourd_hui: str) -> str | None:
    """Un responsable sans aucun eleve actif rattache n'est plus dans le perimetre
    de la synchronisation EcoleDirecte."""
    if not table_existe(conn, "COM_LIENER"):
        return None
    rows = conn.execute(
        """
        SELECT e.IDELEVE, e.EL_DATE_SORTIE
        FROM COM_LIENER l JOIN COM_ELEVES e ON e.IDELEVE = l.IDELEVE
        WHERE l.IDRESPONSABLE = ?
        """,
        (id_resp,),
    ).fetchall()
    if not rows:
        return "aucun eleve rattache au responsable"
    if all(_eleve_sorti(r["EL_DATE_SORTIE"], aujourd_hui) for r in rows):
        sorties = sorted({_jour(r["EL_DATE_SORTIE"]) for r in rows if _jour(r["EL_DATE_SORTIE"])})
        return "aucun eleve actif rattache (sortie le " + ", ".join(sorties) + ") : hors perimetre de la synchro"
    return None


def modifications_ecoledirecte_en_attente(
    conn: sqlite3.Connection,
    statut: str | None = "En attente",
    aujourd_hui: dt.date | None = None,
) -> list[dict]:
    """Fiches modifiees dans Charlemagne et consignees dans COM_JOURNAL_MODIF
    comme restant a envoyer vers EcoleDirecte, avec le nom de la fiche
    (eleve ou responsable) et un motif probable quand la ligne est bloquee.

    statut : filtre exact sur STATUT (par defaut 'En attente') ; None = tout
        le journal.
    aujourd_hui : date de reference pour juger qu'un eleve est sorti (tests).
    """
    if not table_existe(conn, "COM_JOURNAL_MODIF"):
        return []
    ref = (aujourd_hui or dt.date.today()).strftime("%Y%m%d")
    query = """
        SELECT j.ID_JOURNAL_MODIF, j.TYPE, j.TYPE_FICHIER, j.ID_CHARLEMAGNE,
               j.DATE_HEURE_MODIF, j.DATE_HEURE_ENVOI, j.UTILISATEUR, j.STATUT, j.DETAIL,
               e.EL_NOM1, e.EL_PRENOM1, e.EL_DATE_SORTIE, c.CL_LIBELLE,
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
        motif = None
        if row["TYPE_FICHIER"] == "ELEVE":
            fiche = f"{row['EL_NOM1'] or ''} {row['EL_PRENOM1'] or ''}".strip() or None
            if fiche is None:
                motif = "fiche eleve introuvable dans l'export"
            elif _eleve_sorti(row["EL_DATE_SORTIE"], ref):
                motif = f"eleve sorti le {_jour(row['EL_DATE_SORTIE'])} : hors perimetre de la synchro"
        elif row["TYPE_FICHIER"] == "RESPONSABLE":
            fiche = f"{row['RE_NOM1'] or ''} {row['RE_PRENOM1'] or ''}".strip() or None
            if fiche is None:
                motif = "fiche responsable introuvable dans l'export"
            else:
                motif = _motif_responsable(conn, row["ID_CHARLEMAGNE"], ref)
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
                "motif_probable": motif,
            }
        )
    return resultat
