"""Outils MCP - encaissements et impayes des familles (Charlemagne Comptabilite).

Source : le FEC du module Comptabilite charge par ``loader/load_fec.py`` dans une
base a part (``CHARLEMAGNE_COMPTA_DB``), attachee sous le schema ``compta`` a la base
Administratif (voir ``db.connection.get_compta_connection``). Les deux mondes se
rejoignent par le compte de la famille : ``COM_RESPONSABLES.RE_CODE_COMPTABLE`` =
compte auxiliaire 411 du FEC (``CPT_ECRITURE.compte_aux``).

Constats sur les donnees reelles (cartographie compta du projet, par. 9) qui fondent
le calcul :

- les comptes familles ne sont PAS lettres : le statut se deduit du solde, pas du
  lettrage ;
- un exercice non encore ouvert n'a pas d'a-nouveaux : le solde est cumule depuis
  le debut de l'exercice ouvert, report de l'annee precedente compris - comme le
  solde repris dans la premiere facture de l'annee (``HF_ORI_SOLDE``), qui fait
  partie de l'echeancier ;
- un impaye est saisi a la main en banque : debit du 411 de la famille, libelle
  « Impaye <mois> » (graphies variables), et des frais refactures (debit 411 /
  credit 758 dans la meme piece).

Retard d'une famille a une date de reference = solde du compte 411 - echeances
encore a venir (echeancier de sa derniere facture validee, ``FAC_HISTO_FAMILLE``).
Une echeance n'est consideree comme echue que ``delai_jours`` apres sa date, le
temps que la remise de prelevement soit comptabilisee (constate : echeance du 29/09
passee en comptabilite le 01/10).

Lecture seule. Aucune donnee bancaire : le FEC n'en contient pas.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

MAX_ELEMENTS = 80
MAX_MOUVEMENTS = 200

MOTIF_IMPAYE = re.compile(r"impay|rejet|repr[ée]sent", re.I)
MOTIF_FRAIS = re.compile(r"\bfrais\b|\bfrs\b", re.I)
COMPTES_FRAIS = ("758",)          # produits divers de gestion courante : frais d'impaye refactures
PREFIXE_FAMILLES = "411"

MODES = [
    ("prelevement", re.compile(r"^PA\b|\bPRLV|PR[EÉ]L|\bPLV\b", re.I)),
    ("virement", re.compile(r"\bVIR", re.I)),
    ("carte", re.compile(r"\bCB\b|CARTE|EN LIGNE|PAIEMENT LIGNE", re.I)),
    ("cheque", re.compile(r"\bCH(Q|EQUE|ÈQUE)?\b|CH[EÈ]QUE", re.I)),
    ("especes", re.compile(r"ESP[EÈ]CE", re.I)),
]


# ------------------------------------------------------------------ outils communs

def _d(aaaammjj: str | None) -> date | None:
    if not aaaammjj or len(aaaammjj) != 8 or not aaaammjj.isdigit():
        return None
    return date(int(aaaammjj[:4]), int(aaaammjj[4:6]), int(aaaammjj[6:]))


def _iso(aaaammjj: str | None) -> str | None:
    d = _d(aaaammjj)
    return d.isoformat() if d else None


def _parse_date(valeur: str | None) -> str | None:
    """Accepte AAAA-MM-JJ ou AAAAMMJJ, renvoie AAAAMMJJ."""
    if valeur in (None, ""):
        return None
    v = valeur.strip().replace("-", "").replace("/", "")
    if len(v) != 8 or not v.isdigit():
        raise ValueError(f"Date invalide : {valeur!r} (attendu AAAA-MM-JJ)")
    try:
        datetime.strptime(v, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Date invalide : {valeur!r}") from exc
    return v


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def meta(conn: sqlite3.Connection) -> dict:
    try:
        row = conn.execute("SELECT fichier, charge_le, periode_debut, periode_fin, nb_lignes "
                           "FROM compta.CPT_EXPORT").fetchone()
    except sqlite3.OperationalError as exc:
        raise ValueError("Base comptable absente ou vide : charger un FEC avec loader/load_fec.py "
                         "(variable CHARLEMAGNE_COMPTA_DB).") from exc
    if not row:
        raise ValueError("Base comptable vide : charger un FEC avec loader/load_fec.py.")
    return {"fichier": row[0], "charge_le": row[1], "periode_debut": row[2], "periode_fin": row[3],
            "nb_lignes": row[4]}


def _responsables(conn) -> tuple[dict[str, dict], dict[int, str]]:
    """compte 411 -> responsable, et IDRESPONSABLE -> compte."""
    par_compte, par_id = {}, {}
    for rid, code, nom, prenom in conn.execute(
            "SELECT IDRESPONSABLE, RE_CODE_COMPTABLE, RE_NOM1, RE_PRENOM1 FROM COM_RESPONSABLES"):
        if not code:
            continue
        r = {"id_responsable": int(rid), "responsable": " ".join(x for x in (nom, prenom) if x)}
        par_compte[code] = r
        par_id[int(rid)] = code
    return par_compte, par_id


def _echeanciers(conn) -> dict[int, dict]:
    """Echeancier de la derniere facture validee de chaque responsable."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(FAC_HISTO_FAMILLE)")]
    except sqlite3.OperationalError:
        return {}
    if not cols:
        return {}
    res: dict[int, dict] = {}
    for row in conn.execute("SELECT * FROM FAC_HISTO_FAMILLE ORDER BY CAST(IDVALIDATION AS INTEGER)"):
        f = dict(zip(cols, row))
        ech = sorted(((f.get(f"HF_ECHE_DATE{k}"), _num(f.get(f"HF_ECHE_PRIX{k}"))) for k in range(1, 13)),
                     key=lambda x: x[0] or "")
        ech = [(d_, m) for d_, m in ech if d_ and m]
        res[int(f["IDRESPONSABLE"])] = {"mode_reglement": f.get("HF_MODE_REGLEMENT"),
                                        "date_facture": f.get("HF_DATE_FACTURE"),
                                        "echeances": ech}
    return res


def _enfants(conn) -> dict[int, list[str]]:
    res = defaultdict(list)
    try:
        rows = conn.execute(
            "SELECT l.IDRESPONSABLE, e.EL_PRENOM1, e.EL_NOM1, c.CL_LIBELLE, e.EL_DATE_SORTIE "
            "FROM COM_LIENER l JOIN COM_ELEVES e ON e.IDELEVE = l.IDELEVE "
            "LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE").fetchall()
    except sqlite3.OperationalError:
        return {}
    for rid, prenom, nom, classe, sortie in rows:
        if sortie and sortie.strip("0"):
            continue
        res[int(rid)].append(" ".join(x for x in (prenom, nom) if x) + (f" ({classe})" if classe else ""))
    return res


def _journaux_speciaux(conn) -> tuple[set[str], set[str]]:
    """(journaux de facturation, journaux d'a-nouveaux), reconnus a leur libelle."""
    fact, an = set(), set()
    for code, lib in conn.execute("SELECT DISTINCT journal, journal_lib FROM compta.CPT_ECRITURE"):
        l = (lib or "").upper()
        if "NOUVEAU" in l:
            an.add(code)
        elif "FACTUR" in l or "VENTE" in l:
            fact.add(code)
    return fact, an


def _pieces_frais(conn) -> set[tuple]:
    """(journal, piece, date, montant) des credits de frais refactures (comptes 758)."""
    q = " OR ".join("compte LIKE ?" for _ in COMPTES_FRAIS)
    return {(j, p, d_, round(c, 2)) for j, p, d_, c in conn.execute(
        f"SELECT journal, piece_ref, date_ecriture, credit FROM compta.CPT_ECRITURE WHERE credit > 0 AND ({q})",
        [f"{x}%" for x in COMPTES_FRAIS])}


def _mode(libelle: str, piece: str) -> str:
    for nom, motif in MODES:
        if motif.search(libelle or "") or motif.search(piece or ""):
            return nom
    return "autre"


def classer(e: dict, fact: set, an: set, frais: set) -> str:
    """Nature d'une ecriture sur un compte famille."""
    if e["journal"] in an:
        return "a_nouveau"
    if e["journal"] in fact:
        return "facture" if e["debit"] >= e["credit"] else "avoir"
    if e["debit"] > 0:
        if (e["journal"], e["piece_ref"], e["date_ecriture"], round(e["debit"], 2)) in frais:
            return "frais_impaye"
        if MOTIF_IMPAYE.search(e["libelle"] or ""):
            return "frais_impaye" if MOTIF_FRAIS.search(e["libelle"]) else "impaye"
        return "autre_debit"
    return "reglement"


def _mouvements(conn, comptes: list[str] | None = None) -> dict[str, list[dict]]:
    sql = ("SELECT rang, journal, journal_lib, date_ecriture, compte_aux, piece_ref, libelle, debit, credit "
           "FROM compta.CPT_ECRITURE WHERE compte LIKE ? AND compte_aux <> ''")
    args: list = [f"{PREFIXE_FAMILLES}%"]
    if comptes is not None:
        sql += f" AND compte_aux IN ({', '.join('?' * len(comptes))})"
        args += comptes
    res = defaultdict(list)
    for row in conn.execute(sql + " ORDER BY date_ecriture, rang", args):
        e = dict(zip(("rang", "journal", "journal_lib", "date_ecriture", "compte_aux", "piece_ref", "libelle",
                      "debit", "credit"), row))
        res[e["compte_aux"]].append(e)
    return res


def _date_ref(m: dict, date_reference: str | None) -> str:
    return _parse_date(date_reference) or m["periode_fin"]


def situation(mouvements: list[dict], echeancier: dict | None, date_ref: str, delai_jours: int,
              fact: set, an: set, frais: set) -> dict:
    """Solde, retard et statut des echeances d'un compte famille a date_ref."""
    mvts = [e for e in mouvements if e["date_ecriture"] <= date_ref]
    totaux = Counter()
    for e in mvts:
        e["nature"] = classer(e, fact, an, frais)
        totaux[e["nature"]] += e["debit"] - e["credit"]
    solde = round(sum(e["debit"] - e["credit"] for e in mvts), 2)
    limite = (_d(date_ref) - timedelta(days=delai_jours)).strftime("%Y%m%d")
    ech = (echeancier or {}).get("echeances", [])
    echues = [(d_, m) for d_, m in ech if d_ <= limite]
    a_venir = [(d_, m) for d_, m in ech if d_ > limite]
    reste_a_venir = round(sum(m for _, m in a_venir), 2)
    retard = round(solde - reste_a_venir, 2) if echeancier else solde
    # echeances non couvertes : les plus recentes d'abord (un reglement solde les plus anciennes)
    non_couvertes, a_couvrir = [], retard
    for d_, m in reversed(echues):
        if a_couvrir <= 0.005:
            break
        non_couvertes.append((d_, round(min(m, a_couvrir), 2)))
        a_couvrir -= m
    non_couvertes.reverse()
    nc = {d_ for d_, _ in non_couvertes}
    statut_ech = ([{"date": _iso(d_), "montant": round(m, 2), "statut": "non couverte" if d_ in nc else "couverte"}
                   for d_, m in echues]
                  + [{"date": _iso(d_), "montant": round(m, 2), "statut": "a venir"} for d_, m in a_venir])
    impayes = [e for e in mvts if e["nature"] == "impaye"]
    reglements = [e for e in mvts if e["nature"] == "reglement"]
    return {
        "solde": solde,
        "reste_a_venir": reste_a_venir,
        "retard": retard,
        "echeances": statut_ech,
        "echeances_non_couvertes": [{"date": _iso(d_), "montant": m} for d_, m in non_couvertes],
        "totaux": {k: round(v, 2) for k, v in totaux.items()},
        "impayes": impayes,
        "reglements": reglements,
        "mouvements": mvts,
    }


def _ligne(e: dict) -> dict:
    return {"date": _iso(e["date_ecriture"]), "journal": e["journal_lib"] or e["journal"], "piece": e["piece_ref"],
            "libelle": e["libelle"], "debit": round(e["debit"], 2), "credit": round(e["credit"], 2),
            "nature": e.get("nature"),
            **({"mode": _mode(e["libelle"], e["piece_ref"])} if e.get("nature") == "reglement" else {})}


def _note(m: dict, date_ref: str, delai_jours: int) -> str:
    return (f"Comptabilite a la date du dernier FEC charge ({m['fichier']}, ecritures du {_iso(m['periode_debut'])} "
            f"au {_iso(m['periode_fin'])}, charge le {m['charge_le']}). Reference : {_iso(date_ref)} ; une echeance "
            f"n'est comptee echue que {delai_jours} jours apres sa date (delai de comptabilisation des remises). "
            "Retard = solde du compte famille - echeances a venir. Un reglement recu mais pas encore saisi en "
            "comptabilite (cheque en attente de remise) apparait comme un retard. Les impayes sont reconnus a leur "
            "libelle (impaye, rejet) : verifier dans Charlemagne avant toute relance.")


# ------------------------------------------------------------------ outils

def encaissements_famille(conn, id_responsable: str | None = None, id_eleve: str | None = None,
                          compte: str | None = None, date_reference: str | None = None,
                          delai_jours: int = 5) -> dict:
    """Compte 411 d'une famille : solde, factures, reglements, impayes, echeances et retard."""
    m = meta(conn)
    date_ref = _date_ref(m, date_reference)
    par_compte, par_id = _responsables(conn)
    comptes: list[str] = []
    if compte:
        comptes = [compte.strip()]
    elif id_responsable not in (None, ""):
        rid = int(id_responsable)
        if rid not in par_id:
            raise ValueError(f"Responsable inconnu ou sans code comptable : IDRESPONSABLE={id_responsable!r}")
        comptes = [par_id[rid]]
    elif id_eleve not in (None, ""):
        rids = [int(r[0]) for r in conn.execute("SELECT IDRESPONSABLE FROM COM_LIENER WHERE IDELEVE = ?",
                                                (str(id_eleve),))]
        if not rids:
            raise ValueError(f"Aucun responsable pour IDELEVE={id_eleve!r}")
        comptes = sorted({par_id[r] for r in rids if r in par_id})
    else:
        raise ValueError("Indiquer id_responsable, id_eleve ou compte.")
    mvts = _mouvements(conn, comptes)
    fact, an = _journaux_speciaux(conn)
    frais = _pieces_frais(conn)
    ech = _echeanciers(conn)
    enfants = _enfants(conn)
    familles = []
    for c in comptes:
        resp = par_compte.get(c)
        rid = resp["id_responsable"] if resp else None
        s = situation(mvts.get(c, []), ech.get(rid), date_ref, delai_jours, fact, an, frais)
        if not s["mouvements"] and not (rid in ech):
            familles.append({"compte": c, **(resp or {}), "message": "aucune ecriture sur ce compte dans le FEC"})
            continue
        dernier = s["reglements"][-1] if s["reglements"] else None
        familles.append({
            "compte": c,
            **(resp or {"responsable": None}),
            "enfants": enfants.get(rid, []),
            "mode_reglement": (ech.get(rid) or {}).get("mode_reglement"),
            "solde": s["solde"],
            "retard": max(s["retard"], 0.0),
            "en_avance": round(-s["retard"], 2) if s["retard"] < -0.005 else 0.0,
            "reste_a_venir": s["reste_a_venir"],
            "totaux": s["totaux"],
            "dernier_reglement": _ligne(dernier) if dernier else None,
            "impayes": [_ligne(e) for e in s["impayes"]],
            "echeances": s["echeances"],
            "mouvements": [_ligne(e) for e in s["mouvements"][-MAX_MOUVEMENTS:]],
        })
    return {"date_reference": _iso(date_ref), "familles": familles, "note": _note(m, date_ref, delai_jours)}


def impayes_et_retards(conn, date_reference: str | None = None, seuil: float = 1.0, classe: str | None = None,
                       mode_reglement: str | None = None, delai_jours: int = 5) -> dict:
    """Familles en retard de paiement ou avec un impaye saisi, a la date de reference."""
    m = meta(conn)
    date_ref = _date_ref(m, date_reference)
    par_compte, par_id = _responsables(conn)
    mvts = _mouvements(conn)
    fact, an = _journaux_speciaux(conn)
    frais = _pieces_frais(conn)
    ech = _echeanciers(conn)
    enfants = _enfants(conn)
    comptes = set(mvts) | {par_id[r] for r in ech if r in par_id}
    en_retard, regularises, en_avance, inconnus, tous_impayes = [], [], [], [], []
    for c in sorted(comptes):
        resp = par_compte.get(c)
        rid = resp["id_responsable"] if resp else None
        s = situation(mvts.get(c, []), ech.get(rid), date_ref, delai_jours, fact, an, frais)
        mode = (ech.get(rid) or {}).get("mode_reglement")
        kids = enfants.get(rid, [])
        if classe and not any(classe.lower() in k.lower() for k in kids):
            continue
        if mode_reglement and (mode or "").lower() != mode_reglement.lower():
            continue
        imp = s["impayes"]
        tous_impayes += imp
        base = {"compte": c, **(resp or {"responsable": None}), "enfants": kids, "mode_reglement": mode}
        if s["retard"] > seuil:
            nc = s["echeances_non_couvertes"]
            plus_ancienne = nc[0]["date"] if nc else None
            jours = (_d(date_ref) - date.fromisoformat(plus_ancienne)).days if plus_ancienne else None
            dernier = s["reglements"][-1] if s["reglements"] else None
            en_retard.append({
                **base, "retard": s["retard"], "solde": s["solde"], "reste_a_venir": s["reste_a_venir"],
                "sans_echeancier": rid not in ech,
                "echeances_non_couvertes": nc, "plus_ancienne_non_couverte": plus_ancienne,
                "anciennete_jours": jours,
                "impayes_saisis": {"nombre": len(imp), "montant": round(sum(e["debit"] for e in imp), 2),
                                   "dernier": _iso(imp[-1]["date_ecriture"]) if imp else None},
                "frais_impayes": s["totaux"].get("frais_impaye", 0.0),
                "dernier_reglement": ({"date": _iso(dernier["date_ecriture"]), "montant": round(dernier["credit"], 2),
                                       "mode": _mode(dernier["libelle"], dernier["piece_ref"])} if dernier else None),
            })
            if resp is None:
                inconnus.append(c)
        elif imp:
            regularises.append({**base, "impayes_saisis": len(imp), "dernier_impaye": _iso(imp[-1]["date_ecriture"]),
                                "solde": s["solde"]})
        if s["retard"] < -seuil:
            en_avance.append({"compte": c, "responsable": (resp or {}).get("responsable"), "avance": round(-s["retard"], 2)})
    en_retard.sort(key=lambda x: -x["retard"])

    def tranche(j):
        if j is None:
            return "sans echeance identifiee"
        return "0-30 j" if j <= 30 else "31-60 j" if j <= 60 else "61-90 j" if j <= 90 else "plus de 90 j"

    par_mode = defaultdict(lambda: {"familles": 0, "montant": 0.0})
    par_tranche = defaultdict(lambda: {"familles": 0, "montant": 0.0})
    for f in en_retard:
        for d_, k in ((par_mode, f["mode_reglement"] or "inconnu"), (par_tranche, tranche(f["anciennete_jours"]))):
            d_[k]["familles"] += 1
            d_[k]["montant"] = round(d_[k]["montant"] + f["retard"], 2)
    return {
        "date_reference": _iso(date_ref),
        "resume": {
            "familles_en_retard": len(en_retard),
            "montant_en_retard": round(sum(f["retard"] for f in en_retard), 2),
            "par_mode_reglement": dict(par_mode),
            "par_anciennete": dict(par_tranche),
            "impayes_saisis_sur_la_periode": {"lignes": len(tous_impayes),
                                              "familles": len({e["compte_aux"] for e in tous_impayes}),
                                              "montant": round(sum(e["debit"] for e in tous_impayes), 2)},
            "familles_impaye_regularise": len(regularises),
            "familles_en_avance": len(en_avance),
            "montant_en_avance": round(sum(x["avance"] for x in en_avance), 2),
        },
        "familles_en_retard": en_retard[:MAX_ELEMENTS],
        "impayes_regularises": regularises[:MAX_ELEMENTS],
        "comptes_sans_responsable": inconnus,
        "note": _note(m, date_ref, delai_jours),
    }


# ------------------------------------------------------------------ remises de prelevement

def _factures(conn) -> dict[int, list[dict]]:
    """Toutes les factures validees de chaque responsable, dans l'ordre (echeancier de chacune)."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(FAC_HISTO_FAMILLE)")]
    except sqlite3.OperationalError:
        return {}
    res = defaultdict(list)
    for row in conn.execute("SELECT * FROM FAC_HISTO_FAMILLE ORDER BY CAST(IDVALIDATION AS INTEGER)"):
        f = dict(zip(cols, row))
        ech = [(f.get(f"HF_ECHE_DATE{k}"), _num(f.get(f"HF_ECHE_PRIX{k}"))) for k in range(1, 13)]
        res[int(f["IDRESPONSABLE"])].append({"date": f.get("HF_DATE_FACTURE") or "", "mode": f.get("HF_MODE_REGLEMENT"),
                                             "echeances": [(d_, m) for d_, m in ech if d_ and m]})
    return res


def _attendus(factures: dict, date_ech: str, mode_prel: str) -> dict[int, float]:
    """Montant de prelevement attendu a date_ech, d'apres la facture en vigueur a cette date."""
    att = {}
    for rid, fs in factures.items():
        en_vigueur = [f for f in fs if f["date"] <= date_ech]
        if not en_vigueur or en_vigueur[-1]["mode"] != mode_prel:
            continue
        m = sum(mm for d_, mm in en_vigueur[-1]["echeances"] if d_ == date_ech)
        if m:
            att[rid] = round(m, 2)
    return att


def controle_prelevements(conn, date_echeance: str | None = None, fenetre_jours: int = 15,
                          mode_prelevement: str = "Prélèvement") -> dict:
    """Compare une echeance de prelevement aux prelevements comptabilises et aux rejets qui ont suivi."""
    m = meta(conn)
    factures = _factures(conn)
    if not factures:
        raise ValueError("Aucune facture validee dans la base Administratif (FAC_HISTO_FAMILLE).")
    dates = sorted({d_ for fs in factures.values() for f in fs if f["mode"] == mode_prelevement
                    for d_, _ in f["echeances"]})
    if not dates:
        raise ValueError(f"Aucune echeance de mode {mode_prelevement!r} dans les factures.")
    d_ech = _parse_date(date_echeance)
    if d_ech is None:
        passees = [d_ for d_ in dates if d_ <= m["periode_fin"]]
        if not passees:
            raise ValueError("Aucune echeance de prelevement anterieure a la derniere ecriture du FEC.")
        d_ech = passees[-1]
    elif d_ech not in dates:
        raise ValueError(f"Pas d'echeance de prelevement le {_iso(d_ech)} ; echeances : "
                         + ", ".join(_iso(x) for x in dates))
    fin = (_d(d_ech) + timedelta(days=fenetre_jours)).strftime("%Y%m%d")
    suivantes = [d_ for d_ in dates if d_ > d_ech]
    borne_rejets = suivantes[0] if suivantes else "99999999"   # rejets imputes a cette echeance
    par_compte, par_id = _responsables(conn)
    att = _attendus(factures, d_ech, mode_prelevement)
    fact, an = _journaux_speciaux(conn)
    frais = _pieces_frais(conn)
    preleve, dates_cpta, rejets = defaultdict(float), Counter(), defaultdict(list)
    for c, es in _mouvements(conn).items():
        for e in es:
            if not (d_ech <= e["date_ecriture"]):
                continue
            nature = classer(e, fact, an, frais)
            if (e["date_ecriture"] <= fin and nature == "reglement"
                    and _mode(e["libelle"], e["piece_ref"]) == "prelevement"):
                preleve[c] += e["credit"]
                dates_cpta[_iso(e["date_ecriture"])] += 1
            elif nature == "impaye" and e["date_ecriture"] < borne_rejets:
                rejets[c].append(e)
    rid_de = {c: r["id_responsable"] for c, r in par_compte.items()}
    nom = lambda c: (par_compte.get(c) or {}).get("responsable")  # noqa: E731
    attendus_c = {par_id[r]: v for r, v in att.items() if r in par_id}
    manquants = [{"compte": c, "responsable": nom(c), "id_responsable": rid_de.get(c), "attendu": v}
                 for c, v in sorted(attendus_c.items()) if c not in preleve]
    ecarts = [{"compte": c, "responsable": nom(c), "id_responsable": rid_de.get(c), "attendu": v,
               "preleve": round(preleve[c], 2), "ecart": round(preleve[c] - v, 2)}
              for c, v in sorted(attendus_c.items()) if c in preleve and abs(preleve[c] - v) > 0.01]
    sans = [{"compte": c, "responsable": nom(c), "id_responsable": rid_de.get(c), "preleve": round(v, 2)}
            for c, v in sorted(preleve.items()) if c not in attendus_c]
    rej = [{"compte": c, "responsable": nom(c), "id_responsable": rid_de.get(c),
            "rejets": [{"date": _iso(e["date_ecriture"]), "montant": round(e["debit"], 2), "libelle": e["libelle"]}
                       for e in es]}
           for c, es in sorted(rejets.items()) if c in preleve]
    total_rej = round(sum(x["montant"] for r in rej for x in r["rejets"]), 2)
    prochaine = None
    if suivantes:
        a2 = _attendus(factures, suivantes[0], mode_prelevement)
        prochaine = {"date": _iso(suivantes[0]), "familles": len(a2), "montant": round(sum(a2.values()), 2)}
    if not preleve:   # remise pas encore passee en comptabilite : lister les 251 familles n'apprendrait rien
        manquants = []
    statut = ("remise non encore comptabilisee" if not preleve else
              "conforme" if not (manquants or ecarts or sans) else "ecarts a examiner")
    return {
        "date_echeance": _iso(d_ech),
        "statut": statut,
        "attendu": {"familles": len(attendus_c), "montant": round(sum(attendus_c.values()), 2)},
        "preleve": {"familles": len(preleve), "montant": round(sum(preleve.values()), 2),
                    "comptabilise_le": dict(sorted(dates_cpta.items()))},
        "rejets_saisis": {"familles": len(rej), "montant": total_rej},
        "encaisse_net": round(sum(preleve.values()) - total_rej, 2),
        "manquants": manquants[:MAX_ELEMENTS],
        "ecarts_de_montant": ecarts[:MAX_ELEMENTS],
        "preleves_sans_echeance_attendue": sans[:MAX_ELEMENTS],
        "rejets": rej[:MAX_ELEMENTS],
        "prochaine_echeance": prochaine,
        "echeances_de_l_annee": [_iso(x) for x in dates],
        "note": (f"Attendu : echeance du {_iso(d_ech)} de la facture en vigueur a cette date, familles en "
                 f"{mode_prelevement} sur la facture. Preleve : reglements « prelevement » sur les comptes 411 "
                 f"comptabilises du {_iso(d_ech)} au {_iso(fin)} (FEC charge le {m['charge_le']}, ecritures jusqu'au "
                 f"{_iso(m['periode_fin'])}). Rejets : impayes saisis entre cette echeance et la suivante. Le fichier de remise SEPA "
                 "lui-meme n'est pas lu."),
    }


# ------------------------------------------------------------------ pont facturation -> comptabilite

def pont_facturation_comptabilite(conn, validation: str | None = None) -> dict:
    """Chaque validation de facturation est-elle passee en comptabilite, a l'euro pres ?"""
    m = meta(conn)
    try:
        vals = conn.execute("SELECT IDVALIDATION, VA_TYPE_FACTURE, VA_NB_FACTURES, VA_NUMERO_DEBUT, VA_NUMERO_FIN, "
                            "VA_DATE_HEURE FROM FAC_VALIDATION").fetchall()
        factures = conn.execute("SELECT IDVALIDATION, IDRESPONSABLE, HF_NUMERO_FACTURE, HF_APAYER_FACTURE, "
                                "HF_DATE_FACTURE FROM FAC_HISTO_FAMILLE").fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError("Tables de facturation absentes de la base Administratif.") from exc
    if not factures:
        raise ValueError("Aucune facture validee dans la base Administratif.")
    par_compte, par_id = _responsables(conn)
    fact_j, _an = _journaux_speciaux(conn)
    if not fact_j:
        raise ValueError("Aucun journal de facturation reconnu dans le FEC (libelle contenant FACTUR ou VENTE).")
    num = lambda x: str(int(_num(x))) if x not in (None, "") else ""  # noqa: E731
    debut = min(f[4] for f in factures if f[4])[:6] + "01"          # 1er jour du mois de la premiere facture
    q = ",".join("?" * len(fact_j))
    lignes = conn.execute(
        f"SELECT journal, date_ecriture, compte, compte_aux, piece_ref, debit, credit FROM compta.CPT_ECRITURE "
        f"WHERE journal IN ({q}) AND date_ecriture >= ?", [*fact_j, debut]).fetchall()
    cpta_fact = defaultdict(float)                 # (piece, compte 411) -> montant
    cpta_prod = defaultdict(float)                 # (date, compte) -> credit net
    for j, d_, cpt, aux, piece, deb, cre in lignes:
        if cpt.startswith(PREFIXE_FAMILLES):
            cpta_fact[(piece, aux)] += deb - cre
        else:
            cpta_prod[(d_, cpt)] += cre - deb
    try:
        attendu_prod = defaultdict(float)
        for v, cpt, deb, cre, d_ in conn.execute(
                "SELECT IDVALIDATION, CG_COMPTE, CG_DEBIT, CG_CREDIT, CG_DATE_FACTURE FROM FAC_COMPTA_GENERAL"):
            attendu_prod[(d_, cpt)] += _num(cre) - _num(deb)
    except sqlite3.OperationalError:
        attendu_prod = None
    vus = set()
    res_vals = []
    for v, typ, nb, n1, n2, quand in sorted(vals, key=lambda r: int(_num(r[0]))):
        if validation not in (None, "") and str(v) != str(validation):
            continue
        fs = [f for f in factures if str(f[0]) == str(v)]
        absentes, ecarts, trouvees, montant_cpta = [], [], 0, 0.0
        for _v, rid, n, montant, d_ in fs:
            code = par_id.get(int(rid))
            cle = (num(n), code)
            vus.add(cle)
            ligne = {"facture": num(n), "responsable": (par_compte.get(code) or {}).get("responsable"),
                     "id_responsable": int(rid), "montant_facture": round(_num(montant), 2)}
            if cle not in cpta_fact:
                absentes.append(ligne)
                continue
            trouvees += 1
            montant_cpta += cpta_fact[cle]
            if abs(cpta_fact[cle] - _num(montant)) > 0.01:
                ecarts.append({**ligne, "montant_comptabilite": round(cpta_fact[cle], 2)})
        dates = sorted({f[4] for f in fs if f[4]})
        statut = ("non passee en comptabilite" if fs and not trouvees else
                  "passee, avec ecarts" if absentes or ecarts else "passee en comptabilite")
        res_vals.append({
            "validation": int(_num(v)), "type": typ, "validee": quand, "date_facture": [_iso(x) for x in dates],
            "numeros": f"{num(n1)} a {num(n2)}", "statut": statut,
            "factures": {"nombre": len(fs), "montant": round(sum(_num(f[3]) for f in fs), 2),
                         "retrouvees": trouvees, "montant_comptabilite": round(montant_cpta, 2)},
            "factures_absentes": absentes[:MAX_ELEMENTS], "ecarts_de_montant": ecarts[:MAX_ELEMENTS],
        })
    # produits par date de facture (plusieurs validations le meme jour sont additionnees)
    produits = []
    if attendu_prod is not None:
        dates_v = {d_ for r in res_vals for d_ in (x.replace("-", "") for x in r["date_facture"])}
        for d_ in sorted(dates_v):
            comptes = sorted({c for (dd, c) in attendu_prod if dd == d_} | {c for (dd, c) in cpta_prod if dd == d_})
            ec = [{"compte": c, "facturation": round(attendu_prod.get((d_, c), 0.0), 2),
                   "comptabilite": round(cpta_prod.get((d_, c), 0.0), 2)}
                  for c in comptes if abs(attendu_prod.get((d_, c), 0.0) - cpta_prod.get((d_, c), 0.0)) > 0.01]
            produits.append({"date_facture": _iso(d_), "comptes": len(comptes),
                             "total_facturation": round(sum(v for (dd, _), v in attendu_prod.items() if dd == d_), 2),
                             "total_comptabilite": round(sum(v for (dd, _), v in cpta_prod.items() if dd == d_), 2),
                             "ecarts": ec})
    sans_facture = []
    if validation in (None, ""):
        for (piece, aux), montant in sorted(cpta_fact.items()):
            if (piece, aux) not in vus and abs(montant) > 0.005:
                sans_facture.append({"piece": piece, "compte": aux, "responsable": (par_compte.get(aux) or {}).get("responsable"),
                                     "montant": round(montant, 2)})
    if validation not in (None, "") and not res_vals:
        raise ValueError(f"Validation inconnue : {validation!r}")
    return {
        "validations": res_vals,
        "produits_par_date": produits,
        "ecritures_familles_sans_facture": sans_facture[:MAX_ELEMENTS],
        "note": (f"Facturation : FAC_HISTO_FAMILLE / FAC_COMPTA_GENERAL de la base Administratif. Comptabilite : journal "
                 f"de facturation du FEC ({', '.join(sorted(fact_j))}) depuis le {_iso(debut)}, ecritures jusqu'au "
                 f"{_iso(m['periode_fin'])} (charge le {m['charge_le']}). Une facture est retrouvee par son numero "
                 "(piece) et le compte 411 de la famille ; les produits sont compares par compte et par date de facture."),
    }
