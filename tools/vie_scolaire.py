"""Outils MCP - vie scolaire : emploi du temps des classes et appels integres.

Emploi du temps (module Vie Scolaire de Charlemagne) :
- VS_HORAIRE            : horaires de l'etablissement (HO_DEBUT, HO_FIN, HO_TYPE cours/repas)
- VS_HORAIRE_CLASSE     : horaires propres a une classe ("Affinage classe" : cours,
                          recreations, repas) - prioritaires sur VS_HORAIRE quand ils existent
- VS_EDT_TYPE_ENTETE    : semaines types (une par import ou par saisie)
- VS_EDT_TYPE_COURS     : cours d'une semaine type (JOUR 1=lundi..7, HEURE_DEBUT/FIN HHMM,
                          SEMAINE vide/A/B pour l'alternance)
- VS_EDT_TYPE_PROF / VS_EDT_TYPE_SALLE : enseignant(s) et salle(s) d'un cours type
- VS_EDT_COURS (+ VS_EDT_PROF, VS_EDT_SALLE) : cours generes, date par date
- VS_EDT_ALTERNANCES    : calendrier des semaines A/B (SE_DEBUT = lundi, AAAAMMJJ)

Appels (saisis dans EcoleDirecte, recuperes par Vie scolaire > Traitement > Suivi des
appels enseignants) :
- VS_APPEL_PROF   : un appel par classe et par demi-journee (AP_COURS_DATE,
                    AP_COURS_HEURE_DEBUT/FIN, AP_EFFECTIF, AP_NB_ABSENCE, AP_DATE_INTEGRATION)
- VS_ABSENCE      : absences (AB_ORIGINE = 'AppelEd' pour celles venues d'EcoleDirecte ;
                    Charlemagne fusionne les demi-journees consecutives d'un meme eleve)
- VS_ABSENCE_JOUR : detail jour par jour (AJ_DEMIJ_AM / AJ_DEMIJ_PM)

Les heures sont au format HHMM et les dates AAAAMMJJ. Lecture seule uniquement.
"""

import sqlite3
from datetime import date, timedelta

from tools.referentiels import table_existe

JOURS = {1: "lundi", 2: "mardi", 3: "mercredi", 4: "jeudi", 5: "vendredi", 6: "samedi", 7: "dimanche"}


def _hhmm(v: str | None) -> str | None:
    if not v:
        return None
    v = str(v).zfill(4)
    return f"{v[:2]}:{v[2:4]}"


def _aaaammjj(d: str | None) -> str | None:
    """Accepte AAAA-MM-JJ ou AAAAMMJJ, renvoie AAAAMMJJ."""
    if not d:
        return None
    return d.replace("-", "")[:8]


def _iso(v: str | None) -> str | None:
    if not v or len(v) < 8:
        return None
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"


def _classe(conn: sqlite3.Connection, classe: str) -> dict | None:
    """Retrouve une classe par identifiant, code (CM2A) ou libelle (CM2 A)."""
    c = str(classe).strip()
    row = conn.execute(
        "SELECT IDCLASSE, CL_CODE, CL_LIBELLE FROM COM_CLASSES "
        "WHERE IDCLASSE = ? OR UPPER(CL_CODE) = UPPER(?) OR UPPER(CL_LIBELLE) = UPPER(?) "
        "OR UPPER(REPLACE(CL_LIBELLE, ' ', '')) = UPPER(REPLACE(?, ' ', ''))",
        (c, c, c, c),
    ).fetchone()
    if row is None:
        return None
    return {"id_classe": str(row[0]), "code": row[1], "libelle": row[2]}


def _matieres(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_existe(conn, "TAB_MATIERE"):
        return {}
    return {r[0]: r[1] for r in conn.execute("SELECT MA_CODE_GESTION, MA_LIBELLE FROM TAB_MATIERE")}


def _personnels(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_existe(conn, "COM_PERSONNELS"):
        return {}
    return {
        str(r[0]): " ".join(x for x in (r[1], r[2]) if x).strip()
        for r in conn.execute("SELECT IDPERSONNEL, PE_NOM, PE_PRENOM FROM COM_PERSONNELS")
    }


def _salles(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_existe(conn, "VS_SALLES"):
        return {}
    return {str(r[0]): r[1] for r in conn.execute("SELECT IDSALLE, SA_CODE FROM VS_SALLES")}


def _liens(conn: sqlite3.Connection, table: str, colonne: str) -> dict[str, list[str]]:
    res: dict[str, list[str]] = {}
    if not table_existe(conn, table):
        return res
    for r in conn.execute(f'SELECT IDCOURS, "{colonne}" FROM "{table}"'):
        if r[1] not in (None, "", "0", 0):
            res.setdefault(str(r[0]), []).append(str(r[1]))
    return res


def horaires_classe(conn: sqlite3.Connection, id_classe: str) -> dict:
    """Horaires applicables a une classe : ceux de la classe s'ils existent, sinon
    ceux de l'etablissement."""
    lignes = []
    source = None
    if table_existe(conn, "VS_HORAIRE_CLASSE"):
        lignes = conn.execute(
            "SELECT HO_DEBUT, HO_FIN, HO_TYPE FROM VS_HORAIRE_CLASSE WHERE IDCLASSE = ? "
            "ORDER BY HO_DEBUT",
            (id_classe,),
        ).fetchall()
        source = "classe"
    if not lignes and table_existe(conn, "VS_HORAIRE"):
        lignes = conn.execute("SELECT HO_DEBUT, HO_FIN, HO_TYPE FROM VS_HORAIRE ORDER BY HO_DEBUT").fetchall()
        source = "etablissement"
    return {
        "source": source,
        "plages": [{"debut": _hhmm(r[0]), "fin": _hhmm(r[1]), "type": r[2]} for r in lignes],
    }


def emploi_du_temps_classe(
    conn: sqlite3.Connection,
    classe: str,
    date_debut: str | None = None,
    date_fin: str | None = None,
) -> dict:
    """Emploi du temps d'une classe : horaires, semaine type la plus recente et,
    si des dates sont donnees, les cours generes sur la periode.

    classe : identifiant, code (CM2A) ou libelle (CM2 A).
    date_debut / date_fin : AAAA-MM-JJ (ou AAAAMMJJ) ; si date_fin est omise,
        la periode couvre 7 jours a partir de date_debut.

    Un dictionnaire vide est renvoye si les tables d'emploi du temps manquent.
    """
    if not (table_existe(conn, "VS_EDT_TYPE_COURS") and table_existe(conn, "COM_CLASSES")):
        return {}
    cl = _classe(conn, classe)
    if cl is None:
        return {"error": f"Classe introuvable : {classe}"}
    idc = cl["id_classe"]
    mats, pers, salles = _matieres(conn), _personnels(conn), _salles(conn)

    entete = conn.execute(
        "SELECT MAX(CAST(IDENTETE AS INTEGER)) FROM VS_EDT_TYPE_COURS WHERE IDCLASSE = ?", (idc,)
    ).fetchone()[0]
    semaine_type = None
    if entete is not None:
        libelle = None
        if table_existe(conn, "VS_EDT_TYPE_ENTETE"):
            r = conn.execute(
                "SELECT LIBELLE, DESCRIPTION FROM VS_EDT_TYPE_ENTETE WHERE IDENTETE = ?", (str(entete),)
            ).fetchone()
            libelle = (r[0], r[1]) if r else None
        profs = _liens(conn, "VS_EDT_TYPE_PROF", "IDPERSONNEL")
        sals = _liens(conn, "VS_EDT_TYPE_SALLE", "IDSALLE")
        jours: dict[str, list] = {}
        nb = 0
        for r in conn.execute(
            "SELECT IDCOURS, JOUR, HEURE_DEBUT, HEURE_FIN, CODE_MATIERE, SEMAINE FROM VS_EDT_TYPE_COURS "
            "WHERE IDCLASSE = ? AND IDENTETE = ? ORDER BY CAST(JOUR AS INTEGER), HEURE_DEBUT",
            (idc, str(entete)),
        ):
            nb += 1
            jours.setdefault(JOURS.get(int(r[1]), str(r[1])), []).append(
                {
                    "debut": _hhmm(r[2]),
                    "fin": _hhmm(r[3]),
                    "matiere": r[4] or None,
                    "matiere_libelle": mats.get(r[4]) if r[4] else None,
                    "semaine": r[5] or None,
                    "enseignants": [pers.get(p, p) for p in profs.get(str(r[0]), [])],
                    "salles": [salles.get(s, s) for s in sals.get(str(r[0]), [])],
                }
            )
        semaine_type = {
            "id_entete": str(entete),
            "libelle": libelle[0] if libelle else None,
            "description": libelle[1] if libelle else None,
            "nb_cours": nb,
            "nb_cours_sans_matiere": sum(1 for L in jours.values() for c in L if not c["matiere"]),
            "jours": jours,
        }

    res = {
        "classe": cl,
        "horaires": horaires_classe(conn, idc),
        "semaine_type": semaine_type,
    }

    d1 = _aaaammjj(date_debut)
    if d1:
        d2 = _aaaammjj(date_fin)
        if not d2:
            dd = date(int(d1[:4]), int(d1[4:6]), int(d1[6:8])) + timedelta(days=6)
            d2 = dd.strftime("%Y%m%d")
        profs = _liens(conn, "VS_EDT_PROF", "IDPERSONNEL")
        sals = _liens(conn, "VS_EDT_SALLE", "IDSALLE")
        cours = []
        if table_existe(conn, "VS_EDT_COURS"):
            for r in conn.execute(
                "SELECT IDCOURS, DATE, HEURE_DEBUT, HEURE_FIN, CODE_MATIERE, ANNULE, MODIFIE "
                "FROM VS_EDT_COURS WHERE IDCLASSE = ? AND DATE BETWEEN ? AND ? ORDER BY DATE, HEURE_DEBUT",
                (idc, d1, d2),
            ):
                cours.append(
                    {
                        "date": _iso(r[1]),
                        "debut": _hhmm(r[2]),
                        "fin": _hhmm(r[3]),
                        "matiere": r[4] or None,
                        "matiere_libelle": mats.get(r[4]) if r[4] else None,
                        "enseignants": [pers.get(p, p) for p in profs.get(str(r[0]), [])],
                        "salles": [salles.get(s, s) for s in sals.get(str(r[0]), [])],
                        "annule": str(r[5]) not in ("", "0", "None"),
                        "modifie": str(r[6]) not in ("", "0", "None"),
                    }
                )
        alternances = {}
        if table_existe(conn, "VS_EDT_ALTERNANCES"):
            for r in conn.execute(
                "SELECT SE_DEBUT, SE_ALTERNANCE FROM VS_EDT_ALTERNANCES WHERE SE_DEBUT BETWEEN ? AND ?",
                (_shift(d1, -6), d2),
            ):
                alternances[_iso(r[0])] = r[1]
        res["cours_generes"] = {
            "du": _iso(d1),
            "au": _iso(d2),
            "nb": len(cours),
            "semaines_alternance": alternances,
            "cours": cours,
        }
    return res


def _shift(aaaammjj: str, jours: int) -> str:
    d = date(int(aaaammjj[:4]), int(aaaammjj[4:6]), int(aaaammjj[6:8])) + timedelta(days=jours)
    return d.strftime("%Y%m%d")


def appels_enseignants(
    conn: sqlite3.Connection,
    date_debut: str | None = None,
    date_fin: str | None = None,
    classe: str | None = None,
    detail_absences: bool = False,
) -> dict:
    """Appels saisis dans EcoleDirecte et integres dans Charlemagne (VS_APPEL_PROF),
    par classe et par demi-journee, avec le nombre d'absents.

    detail_absences : ajoute, par demi-journee, les eleves absents d'apres
        VS_ABSENCE_JOUR (nom, prenom) - a n'utiliser que pour un controle cible.
    """
    if not table_existe(conn, "VS_APPEL_PROF"):
        return {}
    pers = _personnels(conn)
    classes = {str(r[0]): (r[1], r[2]) for r in conn.execute("SELECT IDCLASSE, CL_CODE, CL_LIBELLE FROM COM_CLASSES")}
    q = (
        "SELECT IDCLASSE, IDPERSONNEL, AP_COURS_DATE, AP_COURS_HEURE_DEBUT, AP_COURS_HEURE_FIN, "
        "AP_EFFECTIF, AP_NB_ABSENCE, AP_NB_RETARD, AP_TOUSPRESENTS, AP_DATE, AP_DATE_INTEGRATION "
        "FROM VS_APPEL_PROF WHERE 1=1"
    )
    p: list[str] = []
    d1, d2 = _aaaammjj(date_debut), _aaaammjj(date_fin)
    if d1:
        q += " AND AP_COURS_DATE >= ?"
        p.append(d1)
    if d2:
        q += " AND AP_COURS_DATE <= ?"
        p.append(d2)
    if classe:
        cl = _classe(conn, classe)
        if cl is None:
            return {"error": f"Classe introuvable : {classe}"}
        q += " AND IDCLASSE = ?"
        p.append(cl["id_classe"])
    q += " ORDER BY AP_COURS_DATE, IDCLASSE, AP_COURS_HEURE_DEBUT"

    absents: dict[tuple, list[str]] = {}
    if detail_absences and table_existe(conn, "VS_ABSENCE_JOUR") and table_existe(conn, "COM_ELEVES"):
        noms = {
            str(r[0]): (f"{r[1]} {r[2]}", str(r[3]))
            for r in conn.execute("SELECT IDELEVE, EL_NOM1, EL_PRENOM1, EL_IDCLASSE FROM COM_ELEVES")
        }
        for r in conn.execute("SELECT IDELEVE, AJ_DATE, AJ_DEMIJ_AM, AJ_DEMIJ_PM FROM VS_ABSENCE_JOUR"):
            nom, idc = noms.get(str(r[0]), (str(r[0]), None))
            if str(r[2]) == "1":
                absents.setdefault((idc, r[1], "matin"), []).append(nom)
            if str(r[3]) == "1":
                absents.setdefault((idc, r[1], "apres-midi"), []).append(nom)

    appels = []
    par_classe: dict[str, dict] = {}
    for r in conn.execute(q, p):
        code, lib = classes.get(str(r[0]), (str(r[0]), None))
        demi = "matin" if (r[3] or "0000") < "1200" else "apres-midi"
        a = {
            "classe": code,
            "date": _iso(r[2]),
            "demi_journee": demi,
            "enseignant": pers.get(str(r[1]), str(r[1])),
            "effectif": int(r[5] or 0),
            "absents": int(r[6] or 0),
            "retards": int(r[7] or 0),
            "tous_presents": str(r[8]) == "1",
            "saisi_le": _iso(str(r[9])[:8]) if r[9] else None,
            "integre_le": _iso(str(r[10])[:8]) if r[10] else None,
        }
        if detail_absences:
            a["eleves_absents"] = sorted(absents.get((str(r[0]), r[2], demi), []))
        appels.append(a)
        s = par_classe.setdefault(code, {"demi_journees": 0, "demi_journees_absence": 0})
        s["demi_journees"] += 1
        s["demi_journees_absence"] += a["absents"]
    return {
        "nb_appels": len(appels),
        "par_classe": par_classe,
        "appels": appels,
    }
