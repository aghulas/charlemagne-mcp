"""Referentiels et enrichissements partages entre les outils.

Toutes les fonctions tolerent l'absence d'une table (export plus ancien,
base de test) : elles renvoient alors un dictionnaire vide plutot que de
faire echouer l'outil appelant. Lecture seule uniquement.

Tables utilisees (voir schema-dictionary.md, section "Inventaire") :
- TAB_LIENS           : libelle des liens de parente (COM_LIENER.LER_LIEN)
- TAB_CSP             : libelle des CSP (COM_RESPONSABLES.RE_CSP1)
- TAB_SIT_FAM         : libelle des situations familiales (RE_ID_SITFAM)
- COM_PROFS_PRINCIPAUX: enseignant(s) principal(aux) par classe
- ADM_HISTO_CLASSE_MEF: une ligne par eleve et par annee scolaire passee
"""

import sqlite3


def table_existe(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _dictionnaire(conn: sqlite3.Connection, table: str, cle: str, libelle: str) -> dict[str, str]:
    if not table_existe(conn, table):
        return {}
    return {
        str(r[0]): r[1]
        for r in conn.execute(f'SELECT "{cle}", "{libelle}" FROM "{table}"')
        if r[0] is not None and r[0] != ""
    }


# Codes observes sur l'export avant que TAB_LIENS soit exploitee : conserves
# en repli pour une base ou la table serait absente.
LIBELLES_LIEN_REPLI = {"PS": "Père", "MS": "Mère", "PM": "Autre parent", "AU": "Autre"}


def libelles_liens(conn: sqlite3.Connection) -> dict[str, str]:
    """Code de lien de parente -> libelle (TAB_LIENS, 30 codes)."""
    return {**LIBELLES_LIEN_REPLI, **_dictionnaire(conn, "TAB_LIENS", "LIE_CODE", "LIE_LIBELLE")}


def libelles_csp(conn: sqlite3.Connection) -> dict[str, str]:
    """Code CSP -> libelle (TAB_CSP, nomenclature INSEE a 2 chiffres)."""
    return _dictionnaire(conn, "TAB_CSP", "CSP_CODE", "CSP_LIBELLE")


def libelles_situations_familiales(conn: sqlite3.Connection) -> dict[str, str]:
    """Identifiant de situation familiale -> libelle (TAB_SIT_FAM)."""
    return _dictionnaire(conn, "TAB_SIT_FAM", "IDTAB_SIT_FAM", "SF_LIBELLE")


def enseignants_par_classe(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """IDCLASSE -> enseignants principaux [{id_personnel, nom_prenom}], dans l'ordre NUM_LIGNE.

    Une classe peut avoir plusieurs lignes (co-enseignement).
    """
    if not (table_existe(conn, "COM_PROFS_PRINCIPAUX") and table_existe(conn, "COM_PERSONNELS")):
        return {}
    resultat: dict[str, list[dict]] = {}
    for r in conn.execute(
        """
        SELECT pp.IDCLASSE, pp.IDPERSONNEL, p.PE_NOM, p.PE_PRENOM
        FROM COM_PROFS_PRINCIPAUX pp
        LEFT JOIN COM_PERSONNELS p ON p.IDPERSONNEL = pp.IDPERSONNEL
        ORDER BY pp.IDCLASSE, CAST(pp.NUM_LIGNE AS INTEGER)
        """
    ):
        resultat.setdefault(str(r[0]), []).append(
            {
                "id_personnel": r[1],
                "nom_prenom": f"{r[2] or ''} {r[3] or ''}".strip() or None,
            }
        )
    return resultat


def anciennete_par_eleve(conn: sqlite3.Connection) -> dict[str, dict]:
    """IDELEVE -> {premiere_annee, nb_annees_precedentes, parcours}.

    Source : ADM_HISTO_CLASSE_MEF (annees passees uniquement ; l'annee en
    cours est dans COM_ELEVES). `parcours` = liste chronologique
    [{annee, niveau, du, au}] ; `niveau` est CODE_MEF_INTERNE tel quel
    (libelle court ou code MEF selon les annees, non normalise).
    """
    if not table_existe(conn, "ADM_HISTO_CLASSE_MEF"):
        return {}
    resultat: dict[str, dict] = {}
    for r in conn.execute(
        """
        SELECT IDELEVE, ANNEE_SCOLAIRE, CODE_MEF_INTERNE, DATE_ENTREE, DATE_SORTIE
        FROM ADM_HISTO_CLASSE_MEF
        ORDER BY IDELEVE, ANNEE_SCOLAIRE
        """
    ):
        fiche = resultat.setdefault(
            str(r[0]), {"premiere_annee": r[1], "nb_annees_precedentes": 0, "parcours": []}
        )
        fiche["nb_annees_precedentes"] += 1
        fiche["parcours"].append({"annee": r[1], "niveau": r[2], "du": r[3], "au": r[4]})
    return resultat
