"""Moteur commun « ce que la facturation devrait contenir » d'apres les donnees
sources et les regles tarifaires de l'etablissement.

Partage par audit_de_facturation (controle d'une facturation) et par les outils
de suivi en cours d'annee (regularisations_a_preparer, suivi_echeanciers) :
une seule lecture des eleves, liens payeurs, informations complementaires,
activites et quotients, et une seule traduction des regles en lignes attendues.

Les regles viennent d'un fichier JSON (CHARLEMAGNE_REGLES_FACTURATION, format :
docs/regles_facturation.exemple.json), jamais du code. Lecture seule.
"""

import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path


def charger_regles(chemin: str | None = None) -> dict:
    p = chemin or os.environ.get("CHARLEMAGNE_REGLES_FACTURATION")
    if not p:
        raise ValueError("Aucun fichier de regles : definir CHARLEMAGNE_REGLES_FACTURATION.")
    if not Path(p).exists():
        raise ValueError(f"Fichier de regles introuvable : {p}")
    return json.loads(Path(p).read_text(encoding="utf-8"))


def num(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------- prorata au mois

def prorata_regles(regles: dict) -> tuple[int, int]:
    """(premier mois de l'annee scolaire, nombre de mois factures) - 9 et 10 par defaut :
    septembre -> juin, tout mois commence est du."""
    p = regles.get("prorata", {})
    return int(p.get("premier_mois", 9)), int(p.get("nb_mois", 10))


def indice_mois(d: date | str | None, regles: dict) -> int | None:
    """Rang du mois de la date dans l'annee scolaire (1 = premier mois facture, ...).
    None si la date tombe hors des mois factures (ete) ou est vide."""
    if d in (None, ""):
        return None
    if isinstance(d, str):
        s = d.replace("-", "")
        if len(s) < 6 or not s[:6].isdigit():
            return None
        mois = int(s[4:6])
    else:
        mois = d.month
    premier, nb = prorata_regles(regles)
    idx = (mois - premier) % 12 + 1
    return idx if idx <= nb else None


def mois_restants(idx: int | None, regles: dict) -> int:
    """Nombre de mois dus a partir du mois d'indice idx inclus (0 hors annee)."""
    _, nb = prorata_regles(regles)
    return 0 if idx is None else max(0, nb - idx + 1)


def libelle_mois(idx: int, regles: dict) -> str:
    premier, _ = prorata_regles(regles)
    noms = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
            "septembre", "octobre", "novembre", "decembre"]
    return noms[(premier - 1 + idx - 1) % 12]


def colonne(conn, table: str, col: str, alias: str = "", defaut: str = "''") -> str:
    """`alias.col` si la colonne existe dans la table (exports anciens ou fixtures
    de test sans cette colonne), sinon une constante."""
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    return f"{alias}{col}" if col in cols else defaut


# ------------------------------------------------------------------- contexte

class Contexte:
    """Donnees sources necessaires au calcul des lignes attendues (une lecture)."""

    def __init__(self, conn, regles: dict):
        self.regles = regles
        q = lambda s, p=(): conn.execute(s, p).fetchall()
        self.q = q
        rentree = regles.get("date_rentree", "00000000")
        # eleves actifs : affectes a une classe, non sortis avant la rentree
        entree = colonne(conn, "COM_ELEVES", "EL_DATE_ENTREE", "e.")
        self.el = {int(r[0]): tuple(r[1:]) for r in q(
            f"""SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, c.CL_LIBELLE, e.EL_IDREGIME,
                       e.EL_REPASMIDI1||e.EL_REPASMIDI2||e.EL_REPASMIDI4||e.EL_REPASMIDI5,
                       COALESCE({entree},''), COALESCE(e.EL_DATE_SORTIE,'')
                FROM COM_ELEVES e JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
                WHERE e.EL_IDCLASSE <> '' AND (COALESCE(e.EL_DATE_SORTIE,'') = '' OR e.EL_DATE_SORTIE > ?)""",
            (rentree,))}
        self.rn = {int(r[0]): f"{r[1]} {r[2]}" for r in q(
            "SELECT IDRESPONSABLE, RE_NOM1, RE_PRENOM1 FROM COM_RESPONSABLES")}
        self.pay, self.princ = defaultdict(dict), {}
        for eid, rid, typ, v, pct in q(
                "SELECT IDELEVE, IDRESPONSABLE, LER_TYPE_RESP, LER_VERSQUI, LER_POURCENTAGE FROM COM_LIENER"):
            eid, rid = int(eid), int(rid)
            if eid not in self.el:
                continue
            if str(typ) == "1":
                self.princ[eid] = rid
            if str(v) == "1" and num(pct):
                self.pay[eid][rid] = num(pct)
        self.enf = defaultdict(set)          # responsable principal -> enfants a l'ecole
        for e, r in self.princ.items():
            self.enf[r].add(e)
        self.icr = defaultdict(dict)
        for rid, lib, v in q("""SELECT s.IDRESPONSABLE, i.ICR_LIBELLE, COALESCE(s.ICRS_SAISIE_NBRE, s.ICRS_SAISIE_TEXTE)
                                FROM ADM_ICR_SAISIE s JOIN ADM_ICR i ON i.ID_ICR = s.ID_ICR"""):
            self.icr[int(rid)][str(lib).lower()] = str(v).replace(".0", "")
        self.q2 = {int(r[0]): r[1] for r in q(
            "SELECT IDRESPONSABLE, RE_QUOTIENT2 FROM COM_RESPONSABLES WHERE COALESCE(RE_QUOTIENT2,'') <> ''")}
        self.act = defaultdict(dict)
        for code, idp, *j in q("SELECT SI_CODE, IDPASSANT, JOUR1, JOUR2, JOUR4, JOUR5 FROM PA_SUIVI_CONSOMMATEUR"):
            self.act[int(idp)][code] = sum(1 for x in j if str(x) == "1")
        self.ices = {x["code_ice"]: self._ice(x["code_ice"]) for x in regles.get("informations_complementaires", [])}
        self.perso_codes = set(regles.get("codes_personnel", []))
        self.foyer_apel = {int(r[0]): r[1] for r in q(
            """SELECT r.IDRESPONSABLE, f.COT_APEL FROM COM_RESPONSABLES r JOIN COM_FOYER f ON f.IDFOYER = r.IDFOYER""")}
        self.mode = {int(r[0]): (r[1], bool((r[2] or "").strip())) for r in q(
            "SELECT IDRESPONSABLE, RE_MODE_REGLEMENT, RE_IBAN FROM COM_RESPONSABLES")}

    def _ice(self, code):
        return {int(r[0]): num(r[1]) for r in self.q(
            """SELECT s.IDELEVE, COALESCE(s.ICES_SAISIE_NBRE, s.ICES_SAISIE_TEXTE)
               FROM ADM_ICE_SAISIE s JOIN ADM_ICE i ON i.ID_ICE = s.ID_ICE WHERE i.ICE_CODE = ?""", (code,))}

    # --- acces
    def nom(self, i: int) -> str:
        return f"{self.el[i][0]} {self.el[i][1]} ({self.el[i][2]})" if i in self.el else f"eleve {i}"

    def classe(self, i: int):
        return self.el[i][2] if i in self.el else None

    def entree(self, i: int) -> str:
        return self.el[i][5] if i in self.el else ""

    def sortie(self, i: int) -> str:
        return self.el[i][6] if i in self.el else ""

    def info(self, rid: int, debut: str):
        return next((v for k, v in self.icr[rid].items() if k.startswith(debut.lower())), None)

    def est_perso(self, i: int) -> bool:
        return any(self.q2.get(r) in self.perso_codes for r in self.pay[i])

    # --- lignes attendues
    def prefixes_controles(self) -> set[str]:
        """Debuts de codes de lignes que le moteur sait calculer."""
        R = self.regles
        c = set()
        can, gar = R.get("cantine", {}), R.get("garderie", {})
        if can:
            c |= {can["ligne"].split("{")[0], can["ligne_panier"].split("{")[0]}
        if gar:
            c |= {gar["ligne_etude"].split("{")[0], gar["ligne_matin"], gar.get("ligne_forfait", "")}
        c |= {x["ligne"] for x in R.get("activites", [])}
        c |= {x["ligne"] for x in R.get("informations_complementaires", [])}
        c.discard("")
        return c

    def attendu_eleve(self, i: int) -> tuple[dict, list]:
        """Lignes attendues (code -> tarif annuel) pour un eleve, et anomalies de
        donnees sources (externe avec jours de cantine, demi-pensionnaire sans jour)."""
        R = self.regles
        _, _, _, reg, midi, *_ = self.el[i]
        a, nb = self.act.get(i, {}), str(midi).count("1")
        att, anomalies = {}, []
        can, gar = R.get("cantine", {}), R.get("garderie", {})
        if can:
            if str(reg) == str(can.get("regime_panier")) and nb:
                att[can["ligne_panier"].format(n=nb)] = can["tarifs_panier"][str(nb)]
            elif nb:
                att[can["ligne"].format(n=nb)] = can["tarifs"][str(nb)]
            if str(reg) == str(can.get("regime_externe")) and nb:
                anomalies.append("externe_avec_jours_de_cantine")
            if str(reg) not in (str(can.get("regime_externe")), str(can.get("regime_panier"))) and not nb:
                anomalies.append("demi_pensionnaire_sans_jour")
        if gar:
            ne, nmat = a.get(gar["activite_etude"], 0), a.get(gar["activite_matin"], 0)
            if ne == gar.get("jours_forfait", 4) and nmat and gar.get("ligne_forfait"):
                att[gar["ligne_forfait"]] = gar["tarif_forfait"]
            else:
                if ne:
                    att[gar["ligne_etude"].format(n=ne)] = gar["tarifs_etude"][str(ne)]
                if nmat:
                    att[gar["ligne_matin"]] = gar["tarif_matin"]
        for x in R.get("activites", []):
            if a.get(x["activite"]):
                att[x["ligne"]] = x["tarif"]
        for x in R.get("informations_complementaires", []):
            if self.ices[x["code_ice"]].get(i) == x.get("valeur", 1):
                att[x["ligne"]] = x["tarif"]
        return att, anomalies

    def fratrie_attendue(self, i: int) -> dict | None:
        """Reduction fratrie attendue pour un eleve (None si les regles n'en ont pas).
        -> {montant, a_l_ecole, exterieurs, justifie, personnel}"""
        fr = self.regles.get("fratrie")
        if not fr:
            return None
        if self.est_perso(i):
            return {"montant": 0.0, "personnel": True, "a_l_ecole": 0, "exterieurs": 0, "justifie": False, "seuil": None}
        mt = {int(k): v for k, v in fr["montants"].items()}
        r = self.princ.get(i)
        n = len(self.enf[r]) if r is not None else 0
        ext = int(num(self.info(r, fr["info_nb_exterieurs"]))) if r is not None else 0
        j = (self.info(r, fr["info_justificatif"]) == "1") if r is not None else False
        total = n + (ext if j else 0)
        seuil = max((k for k in mt if total >= k >= 3), default=None)
        if not seuil and n == 2 and 2 in mt:
            seuil = 2
        montant = mt[seuil] if seuil else 0
        return {"montant": float(montant), "personnel": False, "a_l_ecole": n, "exterieurs": ext, "justifie": j,
                "seuil": seuil}

    def apel_attendue(self, rid: int) -> float | None:
        ap = self.regles.get("apel")
        if not ap:
            return None
        v = self.foyer_apel.get(rid)
        att = ap["tarifs"].get(str(v), 0)
        if v == ap.get("valeur_exterieur") and self.info(rid, ap["info_justificatif"]) == "1":
            att = ap["tarif_exterieur_justifie"]
        if ap.get("info_foyer_separe") and self.info(rid, ap["info_foyer_separe"]) == "1":
            att = att / 2
        return float(att)
