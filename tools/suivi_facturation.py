"""Outils MCP - suivi de la facturation en cours d'annee.

Apres la facturation initiale, les fiches changent (jours de cantine, etude,
garderie, regime, justificatifs de fratrie ou d'APEL, arrivees, departs, mode
de reglement). Charlemagne ne recalcule pas les factures validees : on passe
par une facture complementaire (ou un avoir) manuelle, qui reprend le solde
restant et re-etale l'echeancier (formation Aplim CFP12). Ces outils preparent
ce travail a partir du dernier export :

- regularisations_a_preparer : compare, eleve par eleve, le cumul facture (toutes
  validations) a ce que donnent les donnees sources actuelles et les regles, et
  propose les lignes a saisir en facture manuelle (code, quantite, prix plein,
  prix au prorata, libelle, quote-part de chaque payeur).
- suivi_echeanciers : etat des echeanciers famille par famille (factures,
  echeances a venir, coherence, mode de reglement ou payeur modifies depuis la
  facturation, prelevement sans IBAN).

Modele du prorata (regles["prorata"], defaut : 10 mois de septembre a juin, tout
mois commence est du) : une ligne de la facturation initiale couvre l'annee ;
une ligne d'une facture complementaire couvre les mois a partir du mois de la
facture - sauf si son montant est le tarif annuel entier, auquel cas elle est
consideree comme couvrant l'annee (choix constate : complement facture plein
pour une prestation suivie depuis la rentree). La regularisation proposee porte
sur les mois a partir de `date_effet` : attendu x mois restants / nb mois, moins
ce qui est deja couvert pour ces mois.

Lecture seule. Aucune donnee bancaire n'est renvoyee.
"""

import sqlite3
from collections import Counter, defaultdict
from datetime import date

from tools.regles_facturation import (
    Contexte,
    colonne,
    indice_mois,
    libelle_mois,
    mois_restants,
    num,
    prorata_regles,
)

MAX_ELEMENTS = 80


# ------------------------------------------------------------------ lecture commune

def _validations(conn) -> dict[int, dict]:
    """id -> {type, nb_factures, date_heure, date (AAAAMMJJ de la premiere facture)}."""
    v = {}
    try:
        rows = conn.execute("""SELECT IDVALIDATION, VA_TYPE_FACTURE, VA_NB_FACTURES, VA_NUMERO_DEBUT, VA_NUMERO_FIN,
                               VA_DATE_HEURE FROM FAC_VALIDATION""").fetchall()
    except sqlite3.Error:
        rows = []
    for r in rows:
        v[int(r[0])] = {"id": int(r[0]), "type": r[1], "nb_factures": r[2], "numeros": f"{r[3]}-{r[4]}",
                        "date_heure": r[5], "date": None}
    for vid, d in conn.execute("""SELECT IDVALIDATION, MIN(HF_DATE_FACTURE) FROM FAC_HISTO_FAMILLE
                                  GROUP BY IDVALIDATION""").fetchall():
        v.setdefault(int(vid), {"id": int(vid), "type": None, "nb_factures": None, "numeros": None, "date_heure": None})
        v[int(vid)]["date"] = d
    return v


def _lignes(conn) -> list[dict]:
    """Lignes facturees de toutes les validations, hors lignes de regroupement
    (CONTRIBUTION = somme de CONTRIB, DDEC... : les additionner compterait deux fois)."""
    lib = colonne(conn, "FAC_HISTO_LIGNE", "HL_LIBELLE_LIGNE")
    regr = colonne(conn, "FAC_HISTO_LIGNE", "HL_REGROUPEMENT", defaut="'0'")
    rows = conn.execute(f"""SELECT IDVALIDATION, IDELEVE, IDRESPONSABLE, HL_CODE_LIGNE, HL_TOTAL, HL_QUANTITE, HL_PRIX,
                                   {lib}, {regr}, COALESCE(HL_REMISE_MT_FAMILLE,0), COALESCE(HL_REMISE_MT_ELEVE,0)
                            FROM FAC_HISTO_LIGNE""").fetchall()
    out = []
    for v, e, r, code, t, qte, prix, libl, reg, rf, re_ in rows:
        if str(reg) == "1":
            continue
        t = num(t)
        if not t and not num(rf) and not num(re_):
            continue
        out.append({"validation": int(v or 1), "eleve": int(e or 0), "responsable": int(r or 0), "code": code,
                    "total": t, "quantite": num(qte), "prix": num(prix), "libelle": libl,
                    "remise_famille": num(rf), "remise_eleve": num(re_)})
    return out


def _tarifs_annuels(ctx: Contexte) -> dict[str, float]:
    """code de ligne -> tarif annuel plein, pour toutes les lignes que les regles connaissent."""
    R, t = ctx.regles, {}
    can, gar = R.get("cantine", {}), R.get("garderie", {})
    for n, v in can.get("tarifs", {}).items():
        t[can["ligne"].format(n=n)] = float(v)
    for n, v in can.get("tarifs_panier", {}).items():
        t[can["ligne_panier"].format(n=n)] = float(v)
    for n, v in gar.get("tarifs_etude", {}).items():
        t[gar["ligne_etude"].format(n=n)] = float(v)
    if gar.get("ligne_matin"):
        t[gar["ligne_matin"]] = float(gar["tarif_matin"])
    if gar.get("ligne_forfait"):
        t[gar["ligne_forfait"]] = float(gar["tarif_forfait"])
    for x in R.get("activites", []) + R.get("informations_complementaires", []):
        t[x["ligne"]] = float(x["tarif"])
    fr = R.get("fratrie")
    if fr:
        for k, v in fr["montants"].items():
            t[f"{fr['prefixe_lignes']}{k}"] = float(v)
    return t


def _couverture(lignes: list[dict], validations: dict, tarifs: dict, regles: dict) -> dict:
    """(eleve, code) -> liste de (responsable, mois_debut, montant_par_mois, total, validation).
    Voir le modele du prorata en tete de module."""
    _, nb = prorata_regles(regles)
    premiere = min(validations) if validations else 1
    cov = defaultdict(list)
    for l in lignes:
        if not l["eleve"]:
            continue
        v, code, t = l["validation"], l["code"], l["total"]
        debut = 1
        if v != premiere:
            plein = tarifs.get(code)
            if plein is None or abs(abs(t) - abs(plein)) > .02:
                debut = indice_mois(validations.get(v, {}).get("date"), regles) or 1
        par_mois = t / (nb - debut + 1)
        cov[(l["eleve"], code)].append((l["responsable"], debut, par_mois, t, v))
    return cov


def _couvert_depuis(entrees: list, m0: int, nb: int) -> float:
    """Montant deja facture pour les mois m0..nb (par la couverture mensuelle)."""
    return sum(pm * max(0, nb - max(m0, debut) + 1) for _, debut, pm, _, _ in entrees)


def _contribution_classe(lignes: list[dict], ctx: Contexte, premiere: int) -> dict[str, dict[str, float]]:
    """classe -> {code de contribution : montant} le plus frequent sur la facturation initiale,
    pour chiffrer un nouvel eleve (la contribution n'est pas dans les regles, elle est identique
    pour toute une classe : controle de audit_de_facturation)."""
    rg = set(ctx.regles.get("lignes_regroupement_contribution", []))
    if not rg:
        return {}
    par_eleve = defaultdict(dict)
    for l in lignes:
        if l["validation"] == premiere and l["code"] in rg and l["eleve"] in ctx.el:
            par_eleve[l["eleve"]][l["code"]] = par_eleve[l["eleve"]].get(l["code"], 0) + l["total"]
    par_classe = defaultdict(Counter)
    for e, d in par_eleve.items():
        par_classe[ctx.classe(e)][tuple(sorted((c, round(v, 2)) for c, v in d.items()))] += 1
    return {cl: dict(c.most_common(1)[0][0]) for cl, c in par_classe.items() if c}


def _lignes_manuelles_en_attente(conn, ctx: Contexte) -> list[dict]:
    """Lignes deja saisies dans la preparation manuelle de Charlemagne (FAC_GESTION_HISTO),
    pas encore validees."""
    try:
        rows = conn.execute("""SELECT IDRESPONSABLE, IDELEVE, GH_CODE_LIGNE, GH_QTE, GH_LIBELLE, GH_PRIX
                               FROM FAC_GESTION_HISTO""").fetchall()
    except sqlite3.Error:
        return []
    return [{"responsable": ctx.rn.get(int(r or 0)), "eleve": ctx.nom(int(e or 0)) if e and int(e) else "(ligne famille)",
             "id_eleve": int(e or 0), "code": c, "quantite": num(q), "prix": num(p), "montant": round(num(q) * num(p), 2),
             "libelle": lib} for r, e, c, q, lib, p in rows]


def _pieces_recues(conn) -> dict[tuple[str, str], str]:
    """(id personne, libelle de la piece) -> etat, pour les listes de type F (responsables)
    et E (eleves). Tables absentes -> vide."""
    try:
        pieces = {str(r[0]): r[1] for r in conn.execute("SELECT IDPIECE_DOSSIER, LIBELLE FROM INS_PIECES_DOSSIER")}
        liens_liste = {str(r[0]): pieces.get(str(r[1]), r[1]) for r in conn.execute(
            "SELECT ID_LIEN_PIECE_LISTE, IDPIECE_DOSSIER FROM COM_LIEN_PIECE_LISTE")}
        personnes = {str(r[0]): str(r[1]) for r in conn.execute(
            "SELECT ID_LIEN_PIECE_PERSONNE, ID_PERSONNE FROM COM_LIEN_PIECE_PERSONNE")}
        out = {}
        for lp, ll, etat in conn.execute("SELECT ID_LIEN_PIECE_PERSONNE, ID_LIEN_PIECE_LISTE, ETAT FROM COM_PIECE_RECU"):
            out[(personnes.get(str(lp), ""), liens_liste.get(str(ll), ""))] = etat
        return out
    except sqlite3.Error:
        return {}


# --------------------------------------------------------- regularisations a preparer

def regularisations_a_preparer(conn, regles: dict, date_effet: str | None = None,
                               id_eleve: str | None = None, aujourd_hui: date | None = None) -> dict:
    if not conn.execute("SELECT COUNT(*) FROM FAC_HISTO_LIGNE").fetchone()[0]:
        raise ValueError("Aucune facturation validee dans l'export : rien a regulariser "
                         "(utiliser audit_de_facturation sur la preparation).")
    ctx = Contexte(conn, regles)
    _, nb = prorata_regles(regles)
    auj = aujourd_hui or date.today()  # noqa: DTZ011 - date locale du poste, comme Charlemagne
    d_effet = date.fromisoformat(date_effet) if date_effet else auj
    m0 = indice_mois(d_effet, regles)
    if m0 is None:
        raise ValueError(f"date_effet {d_effet.isoformat()} hors des mois factures : indiquer une date entre "
                         f"le premier et le dernier mois de l'annee scolaire.")
    restants = mois_restants(m0, regles)
    validations = _validations(conn)
    premiere = min(validations) if validations else 1
    lignes = _lignes(conn)
    tarifs = _tarifs_annuels(ctx)
    cov = _couverture(lignes, validations, tarifs, regles)
    lib_lignes = {r[0]: r[1] for r in conn.execute("SELECT LI_CODE, LI_LIBELLE FROM FAC_LIGNE")}
    contrib_classe = _contribution_classe(lignes, ctx, premiere)
    en_attente = _lignes_manuelles_en_attente(conn, ctx)
    attente = defaultdict(float)
    for a in en_attente:
        attente[(a["id_eleve"], a["code"])] += a["montant"]
    factures = {l["eleve"] for l in lignes if l["eleve"]}
    controles = ctx.prefixes_controles()
    fr_r = regles.get("fratrie")
    if fr_r:
        controles.add(fr_r["prefixe_lignes"])
    periode = f"{libelle_mois(m0, regles)} -> {libelle_mois(nb, regles)} ({restants}/{nb})"
    cibles = [int(id_eleve)] if id_eleve not in (None, "") else sorted(ctx.el)
    if id_eleve not in (None, "") and int(id_eleve) not in ctx.el:
        raise ValueError(f"Aucun eleve actif avec IDELEVE={id_eleve!r}")

    regularisations, departs, anomalies_sources = [], [], []

    def ligne_proposee(i, code, tarif, deja, couvert, m_eff, motif):
        rest = mois_restants(m_eff, regles)
        plein = round(tarif - deja, 2)
        prorata = round(tarif * rest / nb - couvert, 2)
        sens = "complement" if prorata > 0 or (prorata == 0 and plein > 0) else "avoir"
        quote = {ctx.rn.get(r, str(r)): round(prorata * p / 100, 2) for r, p in ctx.pay[i].items()} if ctx.pay[i] else {}
        periode_l = f"{libelle_mois(m_eff, regles)} -> {libelle_mois(nb, regles)} ({rest}/{nb})"
        libelle = f"{lib_lignes.get(code, code)} - {'complement' if sens == 'complement' else 'avoir'} {periode_l}"
        d = {"code": code, "libelle_ligne": lib_lignes.get(code, code), "motif": motif, "sens": sens,
             "tarif_annuel": tarif, "deja_facture": round(deja, 2), "couvert_sur_periode": round(couvert, 2),
             "montant_plein": plein, "montant_prorata": prorata, "periode": periode_l,
             "saisie_proposee": {"quantite": 1, "prix": prorata, "libelle": libelle},
             "quote_part_payeurs": quote}
        if attente.get((i, code)):
            d["deja_en_preparation_manuelle"] = round(attente[(i, code)], 2)
        return d

    for i in cibles:
        sortie = ctx.sortie(i)
        if sortie:
            # depart en cours d'annee : avoir sur les mois suivant le mois de sortie, toutes lignes
            ms = indice_mois(sortie, regles)
            if ms is None or ms >= nb:
                continue
            lignes_d = []
            for (e, code), entrees in cov.items():
                if e != i:
                    continue
                couvert = _couvert_depuis(entrees, ms + 1, nb)
                if abs(couvert) > .02:
                    lignes_d.append({"code": code, "libelle_ligne": lib_lignes.get(code, code), "sens": "avoir",
                                     "montant_prorata": round(-couvert, 2), "deja_facture": round(sum(x[3] for x in entrees), 2),
                                     "periode": f"{libelle_mois(ms + 1, regles)} -> {libelle_mois(nb, regles)} ({nb - ms}/{nb})",
                                     "saisie_proposee": {"quantite": 1, "prix": round(-couvert, 2),
                                                         "libelle": f"{lib_lignes.get(code, code)} - avoir depart le {sortie}"}})
            if lignes_d:
                departs.append({"id_eleve": i, "eleve": ctx.nom(i), "sorti_le": sortie, "lignes": lignes_d,
                                "net_prorata": round(sum(x["montant_prorata"] for x in lignes_d), 2),
                                "note": "Tout mois commence est du ; a confirmer avec la direction (reglement financier)."})
            continue
        att, anos = ctx.attendu_eleve(i)
        for a in anos:
            anomalies_sources.append({"eleve": ctx.nom(i), "anomalie": a})
        f_att = ctx.fratrie_attendue(i)
        if f_att and not f_att["personnel"] and f_att["montant"]:
            att[f"{fr_r['prefixe_lignes']}{f_att['seuil']}"] = f_att["montant"]
        nouveau = i not in factures
        m_eff = m0
        if nouveau:
            me = indice_mois(ctx.entree(i), regles)
            m_eff = max(m0, me) if me else m0
            for code, v in contrib_classe.get(ctx.classe(i), {}).items():
                att[code] = v
        codes = set(att) | {c for (e, c) in cov if e == i and (any(c.startswith(k) for k in controles) or nouveau)}
        lignes_r = []
        for code in sorted(codes):
            tarif = float(att.get(code, 0))
            entrees = cov.get((i, code), [])
            deja = sum(x[3] for x in entrees)
            couvert = _couvert_depuis(entrees, m_eff, nb)
            if abs(tarif * mois_restants(m_eff, regles) / nb - couvert) <= .02 and abs(tarif - deja) <= .02:
                continue
            motif = ("nouvel eleve" if nouveau else "reduction fratrie" if fr_r and code.startswith(fr_r["prefixe_lignes"])
                     else "forfait ou activite modifie")
            lignes_r.append(ligne_proposee(i, code, tarif, deja, couvert, m_eff, motif))
        if lignes_r:
            regularisations.append({
                "id_eleve": i, "eleve": ctx.nom(i), "classe": ctx.classe(i),
                "nouvel_eleve": nouveau, **({"entre_le": ctx.entree(i)} if nouveau else {}),
                "payeurs": {ctx.rn.get(r, str(r)): p for r, p in ctx.pay[i].items()},
                "lignes": lignes_r,
                "net_prorata": round(sum(x["montant_prorata"] for x in lignes_r), 2),
                "net_plein": round(sum(x["montant_plein"] for x in lignes_r), 2),
            })

    # APEL par responsable (pas de prorata : cotisation annuelle)
    apel = []
    ap_r = regles.get("apel")
    if ap_r and id_eleve in (None, ""):
        cumul = defaultdict(float)
        for l in lignes:
            if l["code"] == ap_r["ligne"]:
                cumul[l["responsable"]] += l["total"]
        rids = {r for i in ctx.el for r in ctx.pay[i]}
        for rid in sorted(rids | set(cumul)):
            att = ctx.apel_attendue(rid)
            delta = round(att - cumul.get(rid, 0), 2)
            if abs(delta) > .01:
                apel.append({"responsable": ctx.rn.get(rid, str(rid)), "foyer": ctx.foyer_apel.get(rid),
                             "deja_facture": round(cumul.get(rid, 0), 2), "attendu": att, "montant": delta,
                             "sens": "complement" if delta > 0 else "avoir",
                             "saisie_proposee": {"ligne": ap_r["ligne"], "quantite": 1, "prix": delta,
                                                 "libelle": f"{lib_lignes.get(ap_r['ligne'], 'APEL')} - "
                                                            f"{'complement' if delta > 0 else 'avoir'} (justificatif / situation du foyer)"}})

    # remise personnel absente (montant non chiffre : remise famille parametree dans Charlemagne)
    remise_absente = []
    if id_eleve in (None, ""):
        avec_remise = {l["eleve"] for l in lignes if l["remise_famille"]}
        for i in sorted(ctx.el):
            if ctx.est_perso(i) and i not in avec_remise and i in factures:
                remise_absente.append({"eleve": ctx.nom(i), "quotient2": [ctx.q2.get(r) for r in ctx.pay[i]]})

    # justificatifs : piece recue mais information non saisie, et l'inverse
    a_saisir, sans_piece = [], []
    pj = regles.get("pieces_justificatifs", [])
    if pj and id_eleve in (None, ""):
        recues = _pieces_recues(conn)
        rids = {r for i in ctx.el for r in ctx.pay[i]} | {r for i in ctx.el if (r := ctx.princ.get(i)) is not None}
        for rid in sorted(rids):
            for regle in pj:
                recue = recues.get((str(rid), regle["piece"]))
                if "quotient2_parmi" in regle:
                    saisie = ctx.q2.get(rid) in set(regle["quotient2_parmi"])
                    attendu = f"quotient 2 parmi {regle['quotient2_parmi']}"
                else:
                    saisie = str(ctx.info(rid, regle["info_responsable"]) or "") == str(regle.get("valeur", 1))
                    attendu = f"« {regle['info_responsable']} » = {regle.get('valeur', 1)}"
                if recue and not saisie:
                    a_saisir.append({"responsable": ctx.rn.get(rid, str(rid)), "piece": regle["piece"], "etat": recue,
                                     "a_saisir": attendu, "enfants": [ctx.nom(e) for e in sorted(ctx.enf.get(rid, ()))]})
                elif saisie and not recue and regle.get("piece_obligatoire", True):
                    sans_piece.append({"responsable": ctx.rn.get(rid, str(rid)), "piece": regle["piece"],
                                       "information_saisie": attendu})

    # controle des lignes manuelles en attente : la ligne complete-t-elle bien ce qui manque ?
    for a in en_attente:
        i, code = a["id_eleve"], a["code"]
        if i not in ctx.el:
            a["controle"] = "eleve non actif ou ligne famille : non controle"
            continue
        att, _ = ctx.attendu_eleve(i)
        f_att = ctx.fratrie_attendue(i)
        if f_att and not f_att["personnel"] and f_att["montant"]:
            att[f"{fr_r['prefixe_lignes']}{f_att['seuil']}"] = f_att["montant"]
        if code not in tarifs and code not in att:
            a["controle"] = "ligne hors regles (retard, passage...) : non controlee"
            continue
        tarif, deja, pend = float(att.get(code, 0)), sum(x[3] for x in cov.get((i, code), [])), attente[(i, code)]
        if abs(tarif - deja) <= .02:
            a["controle"] = (f"ATTENTION : le cumul deja facture ({deja:.2f}) est deja conforme a l'attendu ({tarif:.2f}) ; "
                             f"cette ligne ferait depasser de {pend:.2f}")
        elif abs(tarif - deja - pend) <= .02:
            a["controle"] = f"conforme : porte le cumul de {deja:.2f} a l'attendu {tarif:.2f} (plein, sans prorata)"
        elif abs(tarif * restants / nb - _couvert_depuis(cov.get((i, code), []), m0, nb) - pend) <= .02:
            a["controle"] = f"conforme au prorata {restants}/{nb}"
        else:
            a["controle"] = f"a verifier : attendu {tarif:.2f}, deja facture {deja:.2f}, en attente {pend:.2f}"

    total_c = sum(x["net_prorata"] for x in regularisations if x["net_prorata"] > 0)
    total_a = sum(x["net_prorata"] for x in regularisations if x["net_prorata"] < 0)
    return {
        "date_effet": d_effet.isoformat(), "periode_regularisee": periode, "mois_restants": restants,
        "coefficient_prorata": round(restants / nb, 3),
        "validations": [validations[k] for k in sorted(validations)],
        "resume": {"eleves_controles": len(cibles), "eleves_a_regulariser": len(regularisations),
                   "nouveaux_eleves": sum(1 for x in regularisations if x["nouvel_eleve"]),
                   "departs": len(departs), "complements_prorata": round(total_c, 2), "avoirs_prorata": round(total_a, 2),
                   "apel_a_regulariser": len(apel), "lignes_manuelles_en_attente": len(en_attente),
                   "justificatifs_a_saisir": len(a_saisir)},
        "regularisations": regularisations[:MAX_ELEMENTS],
        "departs": departs[:MAX_ELEMENTS],
        "apel": apel[:MAX_ELEMENTS],
        "remise_personnel_absente": remise_absente[:MAX_ELEMENTS],
        "lignes_manuelles_en_attente": en_attente,
        "a_saisir_avant_de_facturer": a_saisir[:MAX_ELEMENTS],
        "information_saisie_sans_piece": sans_piece[:MAX_ELEMENTS],
        "anomalies_donnees_sources": anomalies_sources[:MAX_ELEMENTS],
        "note": ("Donnees a la date du dernier export. montant_prorata = tarif x mois restants / nb mois, moins ce qui "
                 "est deja couvert pour ces mois ; montant_plein = tarif - deja facture (sans prorata). Une ligne "
                 "negative est un avoir. A saisir dans Charlemagne en facture complementaire manuelle (la validation "
                 "reprend le solde restant et re-etale l'echeancier) ; les reductions et l'APEL sont des decisions de "
                 "la direction : le prorata n'est qu'une proposition. Mettre d'abord les fiches a jour "
                 "(a_saisir_avant_de_facturer), relancer un export, puis refaire ce calcul."),
    }


# ----------------------------------------------------------------- suivi des echeanciers

def suivi_echeanciers(conn, regles: dict, id_responsable: str | None = None, aujourd_hui: date | None = None) -> dict:
    if not conn.execute("SELECT COUNT(*) FROM FAC_HISTO_FAMILLE").fetchone()[0]:
        raise ValueError("Aucune facturation validee dans l'export.")
    ctx = Contexte(conn, regles)
    auj = (aujourd_hui or date.today()).strftime("%Y%m%d")  # noqa: DTZ011
    validations = _validations(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(FAC_HISTO_FAMILLE)")]
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT * FROM FAC_HISTO_FAMILLE ORDER BY CAST(IDVALIDATION AS INTEGER)").fetchall()]
    par_resp = defaultdict(list)
    for f in rows:
        par_resp[int(f["IDRESPONSABLE"])].append(f)
    if id_responsable not in (None, ""):
        rid = int(id_responsable)
        if rid not in par_resp:
            raise ValueError(f"Aucune facture pour IDRESPONSABLE={id_responsable!r}")
        par_resp = {rid: par_resp[rid]}
    # payeurs factures par eleve (toutes validations) vs payeurs actuels
    payeurs_factures = defaultdict(set)
    for l in _lignes(conn):
        if l["eleve"] and l["total"]:
            payeurs_factures[l["eleve"]].add(l["responsable"])
    mode_prel = regles.get("echeances", {}).get("mode_prelevement", "Prélèvement")
    A = defaultdict(list)
    familles = []
    reste_total = 0.0
    for rid, fs in sorted(par_resp.items()):
        d = fs[-1]
        factures = [{"validation": int(f["IDVALIDATION"]), "type": validations.get(int(f["IDVALIDATION"]), {}).get("type"),
                     "numero": f.get("HF_NUMERO_FACTURE"), "date": f.get("HF_DATE_FACTURE"),
                     "montant": num(f.get("HF_APAYER_FACTURE")), "solde_origine": num(f.get("HF_ORI_SOLDE"))} for f in fs]
        total = round(sum(x["montant"] for x in factures), 2)
        ech = [(d.get(f"HF_ECHE_DATE{k}"), num(d.get(f"HF_ECHE_PRIX{k}"))) for k in range(1, 13)]
        ech = sorted((x for x in ech if x[1] and x[0]), key=lambda x: x[0])
        a_venir = [{"date": x[0], "montant": round(x[1], 2)} for x in ech if x[0] >= auj]
        passees = [{"date": x[0], "montant": round(x[1], 2)} for x in ech if x[0] < auj]
        somme = round(sum(x[1] for x in ech), 2)
        attendu = round(num(d.get("HF_APAYER_FACTURE")) + num(d.get("HF_ORI_SOLDE")), 2)
        alertes = []
        if abs(somme - attendu) > .05:
            alertes.append({"type": "echeancier_incoherent", "somme_echeances": somme, "facture_plus_solde": attendu})
        mode_actuel, iban = ctx.mode.get(rid, (None, False))
        if mode_actuel and d.get("HF_MODE_REGLEMENT") and mode_actuel != d.get("HF_MODE_REGLEMENT"):
            alertes.append({"type": "mode_reglement_modifie", "facture": d.get("HF_MODE_REGLEMENT"), "fiche": mode_actuel,
                            "action": "reactualiser l'echeancier dans Charlemagne"})
        if mode_actuel == mode_prel and not iban:
            alertes.append({"type": "prelevement_sans_iban"})
        if mode_actuel == mode_prel and len(a_venir) >= 3:
            m = [x["montant"] for x in a_venir]
            if max(m[:-1]) - min(m[:-1]) > .05:
                alertes.append({"type": "echeances_irregulieres", "montants": m})
        enfants = sorted(e for e, rs in payeurs_factures.items() if rid in rs and e in ctx.el)
        for e in enfants:
            actuels = set(ctx.pay[e])
            if actuels and actuels != payeurs_factures[e]:
                alertes.append({"type": "payeur_modifie_depuis_facturation", "eleve": ctx.nom(e),
                                "factures_a": [ctx.rn.get(r, str(r)) for r in sorted(payeurs_factures[e])],
                                "payeurs_actuels": {ctx.rn.get(r, str(r)): p for r, p in ctx.pay[e].items()}})
        for e in ctx.el:
            if rid in ctx.pay[e] and e not in payeurs_factures and e not in enfants:
                alertes.append({"type": "enfant_non_facture", "eleve": ctx.nom(e)})
        for a in alertes:
            A[a["type"]].append({"responsable": ctx.rn.get(rid, str(rid)), **{k: v for k, v in a.items() if k != "type"}})
        fam = {"id_responsable": rid, "responsable": ctx.rn.get(rid, str(rid)), "mode_reglement": mode_actuel,
               "factures": factures, "total_facture": total, "echeances_passees": passees, "echeances_a_venir": a_venir,
               "reste_a_prelever": round(sum(x["montant"] for x in a_venir), 2), "alertes": alertes}
        reste_total += fam["reste_a_prelever"]
        if id_responsable not in (None, "") or alertes or len(fs) > 1:
            familles.append(fam)
    return {
        "date": auj, "validations": [validations[k] for k in sorted(validations)],
        "resume": {"familles": len(par_resp), "familles_avec_plusieurs_factures": sum(1 for fs in par_resp.values() if len(fs) > 1),
                   "total_facture": round(sum(num(f.get("HF_APAYER_FACTURE")) for fs in par_resp.values() for f in fs), 2),
                   "reste_a_prelever": round(reste_total, 2)},
        "nb_alertes": {k: len(v) for k, v in A.items()},
        "alertes": {k: v[:MAX_ELEMENTS] for k, v in A.items()},
        "familles": familles[:MAX_ELEMENTS],
        "note": ("Donnees a la date du dernier export. Les echeances passees sont supposees prelevees : aucun "
                 "encaissement n'est exporte, le statut paye/impaye n'est pas connu. 'familles' ne liste que les "
                 "familles avec une alerte ou plusieurs factures, sauf si id_responsable est donne."),
    }
