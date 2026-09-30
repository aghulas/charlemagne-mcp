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


# ---------------------------------------------------------------------------
# Droits EcoleDirecte des adultes (onglet "EcoleDirecte" de la fiche adulte,
# fonctions, notifications, profils utilisateurs Charlemagne).
#
# Tables (export natif Charlemagne, verifiees sur l'export du 30/09/2026) :
#   COM_PERSONNELS.PE_AVECED           coche "Utilisateur EcoleDirecte"
#   COM_PERSONNELS_ED                  PED_TYPE='ETAB'   : etablissement coche (PED_CLEF = id etab)
#                                      PED_TYPE='MODULE' : fonctionnalite autorisee (PED_CLEF = code)
#                                      cle fiable : ID_PERSO_ED
#   TAB_FONCTIONS / ADM_FONCTION_PERSONNEL   fonctions (Secretariat, Direction...)
#   COM_PERSONNELS_PREFERENCE          PEP_TYPE='INT_...' : notifications (PEP_VALEUR '1'/'0')
#   ADM_PROFIL                         options des profils utilisateurs Charlemagne
#
# Libelles des codes : rapproches des ecrans decrits dans le support de
# formation Aplim "CED4 - Ecole Directe" (§3.1 fiche adulte, §7.3 notifications).
# Un code inconnu est renvoye tel quel plutot que devine.
# ---------------------------------------------------------------------------

FONCTIONNALITES_ED = {
    "ADMIN": "Accès au site d'administration",
    "POSTIT": "Gestion des post-it",
    "AGENDA": "Gestion de l'agenda",
    "MESSAGE": "Messagerie",
    "BL_PARENTS": "Non joignable par les familles",
    "EDT": "Emploi du temps",
    "CDT": "Cahier de textes",
    "APPEL": "Feuille d'appel",
    "AFF_EL": "Coordonnées des élèves",
    "ABS": "Absences",
    "RET": "Retards",
    "SANCTION": "Sanctions",
    "ENCOURAGE": "Encouragements",
    "NOTES": "Notes",
    "MOY": "Moyennes",
    "CONSEIL": "Conseil de classe et LSL",
    "CARNET_CORRESP": "Carnet de correspondance",
    "PAIEMENT": "Paiement / règlements en ligne",
}

NOTIFICATIONS_ED = {
    "INT_MESSAGE_ED": "Messages EcoleDirecte en attente",
    "INT_COORDONNEES": "Demande de modification des coordonnées des familles",
    "INT_MODEREG": "Demande de modification des conditions de règlement",
    "INT_DEMANDE_MODIF_EL": "Demande de modifications élève",
    "INT_APPEL": "Appels en classe en attente",
    "INT_JUSTIF": "Demande de justification d'absences / retards",
    "INT_DEMANDE_SANCTION": "Demande de sanction",
    "INT_INSCR": "Suivi journalier (inscriptions)",
    "INT_REGL_LIGNE": "Demande de règlements en ligne en attente",
}

OPTIONS_PROFIL = {
    "EcoleD_LoginPass": "Visualisation des logins / mots de passe EcoleDirecte",
    "EcoleD_SmsRecapTous": "Récapitulatif des SMS pour tous les utilisateurs",
    "EmailsRecapTous": "Récapitulatif des e-mails pour tous les utilisateurs",
}


def _table_existe(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _colonnes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}  # nom de table fixe, pas d'entree utilisateur


def droits_ecoledirecte(
    conn: sqlite3.Connection,
    id_personnel: str | None = None,
    actifs_seulement: bool = True,
) -> dict:
    """Droits EcoleDirecte de chaque adulte, tels que parametres dans Charlemagne.

    Pour chaque adulte : coche "Utilisateur EcoleDirecte", fonctions,
    etablissements coches, fonctionnalites autorisees / refusees,
    notifications actives / inactives, et points d'attention calcules
    (personnel sans etablissement, sans fonction - donc invisible des familles
    dans la messagerie -, sans messagerie...). Renvoie aussi les options des
    profils utilisateurs Charlemagne (visualisation des mots de passe...).

    Les enseignants (PE_TYPE 'prof') heritent de leurs droits par leur
    categorie : l'absence de reglage fiche par fiche est normale pour eux.
    """
    manquantes = [t for t in ("COM_PERSONNELS", "COM_PERSONNELS_ED") if not _table_existe(conn, t)]
    if manquantes:
        raise ValueError(f"Tables absentes de la base consolidee : {', '.join(manquantes)}.")

    cols = _colonnes(conn, "COM_PERSONNELS")
    avec_ed = "PE_AVECED" if "PE_AVECED" in cols else "NULL"
    query = f"""
        SELECT IDPERSONNEL, PE_NOM, PE_PRENOM, PE_TYPE, PE_DATE_SORTIE, {avec_ed} AS PE_AVECED
        FROM COM_PERSONNELS WHERE 1=1
    """
    params: list[str] = []
    if id_personnel:
        query += " AND IDPERSONNEL = ?"
        params.append(str(id_personnel))
    if actifs_seulement:
        query += " AND (PE_DATE_SORTIE IS NULL OR PE_DATE_SORTIE = '')"
    query += " ORDER BY PE_NOM, PE_PRENOM"
    adultes = conn.execute(query, params).fetchall()
    if id_personnel and not adultes:
        raise ValueError(f"Aucun adulte avec IDPERSONNEL={id_personnel!r} (ou adulte sorti).")

    fonctions: dict[str, list[str]] = {}
    if _table_existe(conn, "ADM_FONCTION_PERSONNEL") and _table_existe(conn, "TAB_FONCTIONS"):
        for r in conn.execute(
            """SELECT fp.IDPERSONNEL, f.LIBELLE FROM ADM_FONCTION_PERSONNEL fp
               LEFT JOIN TAB_FONCTIONS f ON f.IDFONCTION = fp.IDFONCTION"""
        ):
            fonctions.setdefault(r["IDPERSONNEL"], []).append(r["LIBELLE"] or "?")
    fonctions_existantes = (
        [r["LIBELLE"] for r in conn.execute("SELECT LIBELLE FROM TAB_FONCTIONS ORDER BY IDFONCTION")]
        if _table_existe(conn, "TAB_FONCTIONS") else []
    )

    etabs: dict[str, list[str]] = {}
    modules: dict[str, dict[str, bool]] = {}
    for r in conn.execute("SELECT IDPERSONNEL, PED_TYPE, PED_CLEF, PED_AUTORIS FROM COM_PERSONNELS_ED"):
        autorise = str(r["PED_AUTORIS"]) == "1"
        if r["PED_TYPE"] == "ETAB" and autorise:
            etabs.setdefault(r["IDPERSONNEL"], []).append(r["PED_CLEF"])
        elif r["PED_TYPE"] == "MODULE":
            modules.setdefault(r["IDPERSONNEL"], {})[r["PED_CLEF"]] = autorise

    notifs: dict[str, dict[str, bool]] = {}
    if _table_existe(conn, "COM_PERSONNELS_PREFERENCE"):
        for r in conn.execute(
            "SELECT IDPERSONNEL, PEP_TYPE, PEP_VALEUR FROM COM_PERSONNELS_PREFERENCE WHERE PEP_TYPE LIKE 'INT\\_%' ESCAPE '\\'"
        ):
            notifs.setdefault(r["IDPERSONNEL"], {})[r["PEP_TYPE"]] = str(r["PEP_VALEUR"]) == "1"

    def libelles(codes: dict[str, bool], table: dict[str, str], valeur: bool) -> list[str]:
        return [table.get(c, c) for c, v in sorted(codes.items()) if v is valeur]

    resultats = []
    for a in adultes:
        pid = a["IDPERSONNEL"]
        est_prof = a["PE_TYPE"] == "prof"
        mods = modules.get(pid, {})
        nts = notifs.get(pid, {})
        utilisateur_ed = str(a["PE_AVECED"]) == "1" if a["PE_AVECED"] is not None else None
        attention: list[str] = []
        if not est_prof and utilisateur_ed:
            if not etabs.get(pid):
                attention.append("Utilisateur EcoleDirecte sans établissement coché : ne voit aucun élève.")
            if mods and not any(mods.values()):
                attention.append("Aucune fonctionnalité EcoleDirecte autorisée.")
            elif mods and not mods.get("MESSAGE", False):
                attention.append("Messagerie non autorisée.")
            if not fonctions.get(pid):
                attention.append("Aucune fonction : invisible des familles dans la messagerie EcoleDirecte.")
            if nts and not nts.get("INT_MESSAGE_ED", False):
                attention.append("Pas de notification des messages EcoleDirecte en attente.")
            if nts.get("INT_COORDONNEES") and not nts.get("INT_DEMANDE_MODIF_EL"):
                attention.append(
                    "Notifiée des demandes de modification de coordonnées mais pas des "
                    "demandes de modifications élève (activités, régime...)."
                )
        resultats.append({
            "id_personnel": pid,
            "nom_prenom": f"{a['PE_NOM']} {a['PE_PRENOM']}",
            "type": a["PE_TYPE"],
            "utilisateur_ecoledirecte": utilisateur_ed,
            "fonctions": fonctions.get(pid, []),
            "etablissements_coches": etabs.get(pid, []),
            "fonctionnalites_autorisees": libelles(mods, FONCTIONNALITES_ED, True),
            "fonctionnalites_refusees": libelles(mods, FONCTIONNALITES_ED, False),
            "notifications_actives": libelles(nts, NOTIFICATIONS_ED, True),
            "notifications_inactives": libelles(nts, NOTIFICATIONS_ED, False)
            + [NOTIFICATIONS_ED[c] for c in NOTIFICATIONS_ED if nts and c not in nts],
            "points_attention": attention,
        })

    profils = []
    if _table_existe(conn, "ADM_PROFIL"):
        par_util: dict[str, list[str]] = {}
        for r in conn.execute("SELECT ID_UTILISATEUR, PR_TYPE, PR_VALEUR FROM ADM_PROFIL ORDER BY ID_UTILISATEUR"):
            if str(r["PR_VALEUR"]).upper() in ("O", "1"):
                par_util.setdefault(r["ID_UTILISATEUR"], []).append(OPTIONS_PROFIL.get(r["PR_TYPE"], r["PR_TYPE"]))
        profils = [{"id_utilisateur": u, "options_actives": o} for u, o in par_util.items()]

    return {
        "fonctions_existantes": fonctions_existantes,
        "nb_adultes": len(resultats),
        "adultes": resultats,
        "profils_utilisateurs_charlemagne": profils,
        "non_visible_dans_l_export": [
            "Case « Activer les notifications EcoleDirecte » de Charlemagne Outils › Configuration",
            "Profil administrateur de la console EcoleDirecte (e-mail, mobile)",
            "Groupe restreignant la consultation des élèves (onglet EcoleDirecte, zone Groupe)",
        ],
    }
