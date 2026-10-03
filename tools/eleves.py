"""Outils MCP - domaine eleves (recherche / identification).

Chaque fonction execute une requete parametree (jamais de concatenation de
texte libre dans du SQL) sur la base SQLite consolidee et retourne un
resultat structure minimal. Lecture seule uniquement.
"""

import sqlite3

from tools.referentiels import anciennete_par_eleve, enseignants_par_classe


def liste_eleves(
    conn: sqlite3.Connection,
    classe: str | None = None,
    actifs_seulement: bool = True,
) -> list[dict]:
    """Liste des eleves avec IDELEVE, nom, prenom, sexe, classe, enseignant(s)
    de la classe et anciennete dans l'ecole.

    enseignants : enseignant(s) principal(aux) de la classe (COM_PROFS_PRINCIPAUX,
        plusieurs lignes possibles en co-enseignement) ; liste vide si la table
        est absente de la base.
    premiere_annee / nb_annees_precedentes : d'apres ADM_HISTO_CLASSE_MEF
        (annees scolaires passees dans l'ecole) ; None / 0 pour un eleve arrive
        cette annee ou si la table est absente.

    Le sexe est repris tel quel de COM_ELEVES.EL_SEXE ('M' / 'F' sur l'export
    courant), sans normalisation : c'est la valeur saisie dans Charlemagne,
    utile notamment pour un controle de coherence avec un autre outil.

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
        SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, e.EL_SEXE,
               e.EL_DATE_SORTIE, e.EL_IDCLASSE, c.CL_LIBELLE
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
    enseignants = enseignants_par_classe(conn)
    anciennete = anciennete_par_eleve(conn)
    resultat = []
    for row in rows:
        histo = anciennete.get(str(row["IDELEVE"]), {})
        resultat.append(
            {
                "id_eleve": row["IDELEVE"],
                "nom": row["EL_NOM1"],
                "prenom": row["EL_PRENOM1"],
                "nom_prenom": f"{row['EL_NOM1']} {row['EL_PRENOM1']}",
                "sexe": row["EL_SEXE"],
                "classe": row["CL_LIBELLE"],
                "enseignants": [e["nom_prenom"] for e in enseignants.get(str(row["EL_IDCLASSE"]), [])],
                "premiere_annee": histo.get("premiere_annee"),
                "nb_annees_precedentes": histo.get("nb_annees_precedentes", 0),
                "actif": not bool(row["EL_DATE_SORTIE"]),
            }
        )
    return resultat
