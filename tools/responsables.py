"""Outils MCP - domaine responsables (parents / tuteurs d'eleves).

Perimetre strictement distinct de COM_PERSONNELS (enseignants et personnels
de l'etablissement, voir tools/personnels.py) : ici uniquement les familles,
via COM_LIENER (table de liaison) puis COM_RESPONSABLES.

Un eleve peut avoir plusieurs responsables : on passe donc toujours par
COM_LIENER, jamais par un raccourci supposant un responsable unique.

Une fiche COM_RESPONSABLES peut porter deux personnes (blocs de colonnes
suffixees 1 et 2 : RE_NOM1/RE_NOM2, RE_EMAILPERSO1/RE_EMAILPERSO2...). Sur
l'export courant le bloc 2 est toujours vide, mais le code le gere pour ne
pas perdre silencieusement une personne si cela change.

Champs volontairement NON exposes : coordonnees bancaires (RE_IBAN, RE_BIC,
RE_CODE_BANQUE, RE_CODE_GUICHET, RE_COMPTE_BANQUE, RE_CLE_RIB,
RE_DOMICILIATION), quotients familiaux et parametres de facturation. Le
besoin couvert ici est l'identite et le contact, pas la facturation.
"""

import sqlite3

# COM_LIENER.LER_LIEN : codes observes sur l'export (PS/MS majoritaires).
LIBELLES_LIEN = {
    "PS": "Père",
    "MS": "Mère",
    "PM": "Autre parent",
    "AU": "Autre",
}


def _personne(row: sqlite3.Row, bloc: int) -> dict | None:
    """Extrait le bloc de colonnes 1 ou 2 d'une fiche responsable.

    Retourne None si le bloc ne porte aucun nom (cas normal du bloc 2 sur
    l'export courant).
    """
    nom = row[f"RE_NOM{bloc}"]
    prenom = row[f"RE_PRENOM{bloc}"]
    if not (nom or prenom):
        return None
    return {
        "bloc": bloc,
        "civilite": row[f"RE_CIVILITE{bloc}"],
        "particule": row[f"RE_PARTICULE{bloc}"],
        "nom": nom,
        "prenom": prenom,
        "nom_jeune_fille": row[f"RE_NOM_JFILLE{bloc}"],
        "email_perso": row[f"RE_EMAILPERSO{bloc}"],
        "email_pro": row[f"RE_EMAILPRO{bloc}"],
        "tel_portable": row[f"RE_TELPORTABLE{bloc}"],
        "tel_pro": row[f"RE_TELPRO{bloc}"],
    }


_REQUETE = """
    SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, e.EL_DATE_SORTIE,
           c.CL_LIBELLE,
           l.IDRESPONSABLE, l.LER_LIEN, l.LER_TYPE_RESP, l.LER_ORDRE,
           r.RE_CIVILITE1, r.RE_PARTICULE1, r.RE_NOM1, r.RE_PRENOM1,
           r.RE_NOM_JFILLE1, r.RE_EMAILPERSO1, r.RE_EMAILPRO1,
           r.RE_TELPORTABLE1, r.RE_TELPRO1,
           r.RE_CIVILITE2, r.RE_PARTICULE2, r.RE_NOM2, r.RE_PRENOM2,
           r.RE_NOM_JFILLE2, r.RE_EMAILPERSO2, r.RE_EMAILPRO2,
           r.RE_TELPORTABLE2, r.RE_TELPRO2,
           r.RE_TELDOMICILE, r.RE_CODEPOSTAL, r.RE_VILLE
    FROM COM_ELEVES e
    LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
    JOIN COM_LIENER l ON l.IDELEVE = e.IDELEVE
    JOIN COM_RESPONSABLES r ON r.IDRESPONSABLE = l.IDRESPONSABLE
    WHERE 1=1
"""


def responsables_eleves(
    conn: sqlite3.Connection,
    id_eleve: str | None = None,
    classe: str | None = None,
    actifs_seulement: bool = True,
) -> list[dict]:
    """Responsables (parents/tuteurs) des eleves, groupes par eleve.

    id_eleve : IDELEVE exact. None = tous les eleves du perimetre.
    classe : filtre optionnel sur COM_CLASSES.CL_LIBELLE, insensible a la casse.
    actifs_seulement : exclut les eleves ayant une EL_DATE_SORTIE renseignee.

    Un eleve sans aucun lien dans COM_LIENER n'apparait pas dans le resultat.
    """
    cur = conn.cursor()
    query = _REQUETE
    params: list[str] = []
    if actifs_seulement:
        query += " AND (e.EL_DATE_SORTIE IS NULL OR e.EL_DATE_SORTIE = '')"
    if id_eleve:
        query += " AND e.IDELEVE = ?"
        params.append(id_eleve)
    if classe:
        query += " AND c.CL_LIBELLE = ? COLLATE NOCASE"
        params.append(classe)
    query += " ORDER BY c.CL_LIBELLE, e.EL_NOM1, e.EL_PRENOM1, l.LER_ORDRE"

    rows = cur.execute(query, params).fetchall()

    par_eleve: dict[str, dict] = {}
    for row in rows:
        fiche = par_eleve.setdefault(
            row["IDELEVE"],
            {
                "id_eleve": row["IDELEVE"],
                "nom_prenom": f"{row['EL_NOM1']} {row['EL_PRENOM1']}",
                "classe": row["CL_LIBELLE"],
                "responsables": [],
            },
        )
        lien = row["LER_LIEN"]
        personnes = [p for p in (_personne(row, 1), _personne(row, 2)) if p]
        for personne in personnes:
            fiche["responsables"].append(
                {
                    "id_responsable": row["IDRESPONSABLE"],
                    "lien": lien,
                    "lien_libelle": LIBELLES_LIEN.get(lien, lien),
                    "type_resp": row["LER_TYPE_RESP"],
                    "tel_domicile": row["RE_TELDOMICILE"],
                    "code_postal": row["RE_CODEPOSTAL"],
                    "ville": row["RE_VILLE"],
                    **personne,
                }
            )
    return list(par_eleve.values())
