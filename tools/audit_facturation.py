"""Outils MCP - audit de la facturation (preparation ou facturation validee).

Compare chaque ligne facturee a ce qu'imposent les donnees sources (jours de cantine,
activites, informations complementaires, liens eleve-responsable) et les regles
tarifaires de l'etablissement, puis controle les reductions, l'APEL, les echeances
et, pour une facturation validee, la numerotation et l'equilibre comptable.

Le module est generique : tarifs, codes de lignes et regles viennent d'un fichier
JSON (variable d'environnement CHARLEMAGNE_REGLES_FACTURATION), jamais du code.
Voir docs/regles_facturation.exemple.json pour le format.

Lecture seule. Aucune donnee bancaire n'est renvoyee.
"""

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

MAX_PAR_RUBRIQUE = 40


def charger_regles(chemin: str | None = None) -> dict:
    p = chemin or os.environ.get("CHARLEMAGNE_REGLES_FACTURATION")
    if not p:
        raise ValueError("Aucun fichier de regles : definir CHARLEMAGNE_REGLES_FACTURATION.")
    if not Path(p).exists():
        raise ValueError(f"Fichier de regles introuvable : {p}")
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _num(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def audit_facturation(conn, regles: dict, validee: bool = False) -> dict:
    q = lambda s, p=(): conn.execute(s, p).fetchall()
    L, F, pl, pf = (("FAC_HISTO_LIGNE", "FAC_HISTO_FAMILLE", "HL_", "HF_") if validee
                    else ("FAC_GESTION_LIGNE", "FAC_GESTION_FAMILLE", "GL_", "GF_"))
    if not q(f"SELECT COUNT(*) FROM {L}")[0][0]:
        raise ValueError(f"{L} est vide : " + ("aucune facturation validee." if validee
                         else "aucune preparation en cours (deja validee ? relancer avec validee=True)."))
    rentree = regles.get("date_rentree", "00000000")
    el = {int(r[0]): tuple(r[1:]) for r in q(
        """SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, c.CL_LIBELLE, e.EL_IDREGIME,
                  e.EL_REPASMIDI1||e.EL_REPASMIDI2||e.EL_REPASMIDI4||e.EL_REPASMIDI5
           FROM COM_ELEVES e JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
           WHERE e.EL_IDCLASSE <> '' AND (COALESCE(e.EL_DATE_SORTIE,'') = '' OR e.EL_DATE_SORTIE > ?)""", (rentree,))}
    nm = lambda i: f"{el[i][0]} {el[i][1]} ({el[i][2]})" if i in el else f"eleve {i}"
    rn = {int(r[0]): f"{r[1]} {r[2]}" for r in q("SELECT IDRESPONSABLE, RE_NOM1, RE_PRENOM1 FROM COM_RESPONSABLES")}
    A = defaultdict(list)
    alerte = lambda rub, **d: A[rub].append(d)
    GL = [(int(r[0] or 0), int(r[1] or 0), r[2], _num(r[3]), _num(r[4]), _num(r[5]), r[6], r[7]) for r in q(
        f"""SELECT IDELEVE, IDRESPONSABLE, {pl}CODE_LIGNE, {pl}TOTAL, {pl}REMISE_MT_FAMILLE, {pl}REMISE_MT_ELEVE,
                   {pl}REMISE_CODE_FAMILLE, {pl}REMISE_CODE_ELEVE FROM {L}""")]

    pay, princ = defaultdict(dict), {}
    for eid, rid, typ, v, pct in q("SELECT IDELEVE, IDRESPONSABLE, LER_TYPE_RESP, LER_VERSQUI, LER_POURCENTAGE FROM COM_LIENER"):
        eid, rid = int(eid), int(rid)
        if eid not in el:
            continue
        if str(typ) == "1":
            princ[eid] = rid
        if str(v) == "1" and _num(pct):
            pay[eid][rid] = _num(pct)
    icr = defaultdict(dict)
    for rid, lib, v in q("""SELECT s.IDRESPONSABLE, i.ICR_LIBELLE, COALESCE(s.ICRS_SAISIE_NBRE, s.ICRS_SAISIE_TEXTE)
                            FROM ADM_ICR_SAISIE s JOIN ADM_ICR i ON i.ID_ICR = s.ID_ICR"""):
        icr[int(rid)][str(lib).lower()] = str(v).replace(".0", "")
    info = lambda rid, debut: next((v for k, v in icr[rid].items() if k.startswith(debut.lower())), None)
    q2 = {int(r[0]): r[1] for r in q("SELECT IDRESPONSABLE, RE_QUOTIENT2 FROM COM_RESPONSABLES WHERE COALESCE(RE_QUOTIENT2,'') <> ''")}
    act = defaultdict(dict)
    for code, idp, *j in q("SELECT SI_CODE, IDPASSANT, JOUR1, JOUR2, JOUR4, JOUR5 FROM PA_SUIVI_CONSOMMATEUR"):
        act[int(idp)][code] = sum(1 for x in j if str(x) == "1")
    def ice(code):
        return {int(r[0]): _num(r[1]) for r in q("""SELECT s.IDELEVE, COALESCE(s.ICES_SAISIE_NBRE, s.ICES_SAISIE_TEXTE)
            FROM ADM_ICE_SAISIE s JOIN ADM_ICE i ON i.ID_ICE = s.ID_ICE WHERE i.ICE_CODE = ?""", (code,))}
    perso_codes = set(regles.get("codes_personnel", []))
    est_perso = lambda i: any(q2.get(r) in perso_codes for r in pay[i])

    # 1. perimetre et payeurs
    factures = {g[0] for g in GL if g[0]}
    for i in el:
        if i not in factures:
            alerte("eleve_actif_non_facture", eleve=nm(i))
        s = sum(pay[i].values())
        if abs(s - 100) > .01:
            alerte("repartition_payeurs_differente_de_100", eleve=nm(i), total=s)
        for rid, pct in pay[i].items():
            if pct == 100 and princ.get(i) != rid and sum(1 for e in pay if rid in pay[e]) >= 2:
                alerte("payeur_de_plusieurs_enfants_non_responsable_principal", eleve=nm(i), payeur=rn.get(rid),
                       consequence="la fratrie est sous-comptee pour ce payeur")
    for i in factures - set(el):
        t = sum(g[3] for g in GL if g[0] == i)
        if t:
            alerte("eleve_facture_non_actif", id_eleve=i, montant=round(t, 2))

    # 2. lignes par eleve
    tot, part = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for eid, rid, code, t, *_ in GL:
        if eid in el:
            tot[eid][code] += t
            part[(eid, code)][rid] += t
    can = regles.get("cantine", {}); gar = regles.get("garderie", {})
    ices = {x["code_ice"]: ice(x["code_ice"]) for x in regles.get("informations_complementaires", [])}
    controles = set()
    contrib = defaultdict(Counter)
    for i, (n, p, cl, reg, midi) in el.items():
        g, a, nb = tot[i], act.get(i, {}), str(midi).count("1")
        att = {}
        if can:
            if str(reg) == str(can.get("regime_panier")) and nb:
                att[can["ligne_panier"].format(n=nb)] = can["tarifs_panier"][str(nb)]
            elif nb:
                att[can["ligne"].format(n=nb)] = can["tarifs"][str(nb)]
            if str(reg) == str(can.get("regime_externe")) and nb:
                alerte("externe_avec_jours_de_cantine", eleve=nm(i))
            if str(reg) not in (str(can.get("regime_externe")), str(can.get("regime_panier"))) and not nb:
                alerte("demi_pensionnaire_sans_jour", eleve=nm(i))
            controles |= {can["ligne"].split("{")[0], can["ligne_panier"].split("{")[0]}
        if gar:
            ne, nmat = a.get(gar["activite_etude"], 0), a.get(gar["activite_matin"], 0)
            if ne == gar.get("jours_forfait", 4) and nmat and gar.get("ligne_forfait"):
                att[gar["ligne_forfait"]] = gar["tarif_forfait"]
            else:
                if ne:
                    att[gar["ligne_etude"].format(n=ne)] = gar["tarifs_etude"][str(ne)]
                if nmat:
                    att[gar["ligne_matin"]] = gar["tarif_matin"]
            controles |= {gar["ligne_etude"].split("{")[0], gar["ligne_matin"], gar.get("ligne_forfait", "")}
        for x in regles.get("activites", []):
            if a.get(x["activite"]):
                att[x["ligne"]] = x["tarif"]
            controles.add(x["ligne"])
        for x in regles.get("informations_complementaires", []):
            if ices[x["code_ice"]].get(i) == x.get("valeur", 1):
                att[x["ligne"]] = x["tarif"]
            controles.add(x["ligne"])
        controles.discard("")
        for code in set(att) | {c for c in g if any(c.startswith(k) for k in controles)}:
            if abs(g.get(code, 0) - att.get(code, 0)) > .01:
                alerte("ligne_incorrecte", eleve=nm(i), ligne=code, facture=round(g.get(code, 0), 2), attendu=att.get(code, 0))
        rg = regles.get("lignes_regroupement_contribution", [])
        if rg:
            contrib[cl][round(sum(v for c, v in g.items() if c in rg), 2)] += 1
    for cl, c in contrib.items():
        if len(c) > 1:
            alerte("contribution_differente_dans_une_classe", classe=cl, montants=dict(c))

    # 3. fratrie et remises
    fr_r = regles.get("fratrie")
    if fr_r:
        enf = defaultdict(set)
        for e, r in princ.items():
            enf[r].add(e)
        mt = {int(k): v for k, v in fr_r["montants"].items()}
        for i in el:
            fr = sum(v for c, v in tot[i].items() if c.startswith(fr_r["prefixe_lignes"]))
            if est_perso(i):
                if fr and not fr_r.get("cumul_avec_personnel", False):
                    alerte("fratrie_cumulee_avec_remise_personnel", eleve=nm(i), fratrie=round(fr, 2))
                continue
            r = princ.get(i); n = len(enf[r])
            ext = int(_num(info(r, fr_r["info_nb_exterieurs"]))); j = info(r, fr_r["info_justificatif"]) == "1"
            total = n + (ext if j else 0)
            seuil = max((k for k in mt if total >= k and k >= 3), default=None)
            attendu = mt[seuil] if seuil else (mt.get(2, 0) if n == 2 else 0)
            if abs(fr - attendu) > .02:
                alerte("reduction_fratrie_hors_regle", eleve=nm(i), facture=round(fr, 2), attendu=attendu,
                       a_l_ecole=n, exterieurs=ext, justifie=j)
            if ext and not j:
                alerte("enfants_exterieurs_sans_justificatif", eleve=nm(i), responsable=rn.get(r))
            if len(pay[i]) > 1 and attendu:
                parts = defaultdict(float)
                for (eid, code), d in part.items():
                    if eid == i and code.startswith(fr_r["prefixe_lignes"]):
                        for rid, v in d.items():
                            parts[rid] += v
                for rid, pct in pay[i].items():
                    if abs(parts.get(rid, 0) - attendu * pct / 100) > .02:
                        alerte("fratrie_mal_repartie_entre_parents", eleve=nm(i), responsable=rn.get(rid),
                               facture=round(parts.get(rid, 0), 2), attendu=round(attendu * pct / 100, 2))
    rem_eleve_ok = set(regles.get("remises_eleve_autorisees", []))
    for eid, rid, code, t, rf, re_, cf, ce in GL:
        if rf and cf and eid in el and not est_perso(eid):
            alerte("remise_famille_sans_code_personnel", eleve=nm(eid), remise=cf)
        if re_ and ce not in rem_eleve_ok:
            alerte("remise_eleve_inattendue", eleve=nm(eid), ligne=code, remise=ce, montant=re_)
    for i in el:
        if est_perso(i) and not any(g[0] == i and g[4] for g in GL):
            alerte("famille_du_personnel_sans_remise", eleve=nm(i))

    # 4. APEL, soldes, echeances
    fcols = [r[1] for r in conn.execute(f"PRAGMA table_info({F})")]
    FAM = {int(r[0]): dict(zip(fcols, r[1:])) for r in q(f"SELECT IDRESPONSABLE, * FROM {F}")}
    ap_r = regles.get("apel")
    if ap_r:
        foyer = {int(r[0]): r[1] for r in q("""SELECT r.IDRESPONSABLE, f.COT_APEL FROM COM_RESPONSABLES r
                                               JOIN COM_FOYER f ON f.IDFOYER = r.IDFOYER""")}
        apel = defaultdict(float)
        for eid, rid, code, t, *_ in GL:
            if code == ap_r["ligne"]:
                apel[rid] += t
        for rid in FAM:
            v = foyer.get(rid)
            att = ap_r["tarifs"].get(str(v), 0)
            if v == ap_r.get("valeur_exterieur") and info(rid, ap_r["info_justificatif"]) == "1":
                att = ap_r["tarif_exterieur_justifie"]
            if ap_r.get("info_foyer_separe") and info(rid, ap_r["info_foyer_separe"]) == "1":
                att = att / 2
            if abs(apel.get(rid, 0) - att) > .01:
                alerte("apel_incorrecte", responsable=rn.get(rid), foyer=v, facture=round(apel.get(rid, 0), 2), attendu=att)
    mode = {int(r[0]): (r[1], bool((r[2] or "").strip())) for r in q("SELECT IDRESPONSABLE, RE_MODE_REGLEMENT, RE_IBAN FROM COM_RESPONSABLES")}
    ech_r = regles.get("echeances", {})
    for rid, f in FAM.items():
        n = sum(1 for k in range(1, 13) if _num(f.get(f"{pf}ECHE_PRIX{k}")))
        solde = _num(f.get(f"{pf}ORI_SOLDE"))
        if solde > regles.get("solde_a_signaler", 100):
            alerte("solde_reporte_important", responsable=rn.get(rid), solde=solde)
        m, iban = mode.get(rid, (None, False))
        if m == ech_r.get("mode_prelevement", "Prélèvement"):
            if ech_r.get("nb_prelevement") and n != ech_r["nb_prelevement"]:
                alerte("nombre_echeances_prelevement", responsable=rn.get(rid), echeances=n)
            if not iban:
                alerte("prelevement_sans_iban", responsable=rn.get(rid))

    # 5. validation : numerotation et equilibre comptable
    resume = {"eleves_actifs": len(el), "eleves_factures": len(factures & set(el)), "familles": len(FAM), "lignes": len(GL)}
    if fr_r:
        resume["repartition_fratrie"] = {str(k): v for k, v in Counter(
            round(sum(x for c, x in tot[i].items() if c.startswith(fr_r["prefixe_lignes"])), 2) for i in el).items()}
    if validee:
        nums = sorted(int(r[0]) for r in q("SELECT DISTINCT CG_NUMERO_FACTURE FROM FAC_COMPTA_GENERAL") if r[0])
        if nums and nums != list(range(nums[0], nums[-1] + 1)):
            alerte("numerotation_discontinue", premier=nums[0], dernier=nums[-1], nombre=len(nums))
        d, c = q("SELECT SUM(CAST(CG_DEBIT AS REAL)), SUM(CAST(CG_CREDIT AS REAL)) FROM FAC_COMPTA_GENERAL")[0]
        cf = q("SELECT SUM(CAST(CF_DEBIT AS REAL)) FROM FAC_COMPTA_FAMILLE")[0][0] or 0
        d, c = d or 0, c or 0
        resume["comptabilite"] = {"produits": round(c, 2), "reductions": round(d, 2), "clients": round(cf, 2),
                                  "equilibree": abs((c - d) - cf) <= .05}
        if abs((c - d) - cf) > .05:
            alerte("comptabilite_desequilibree", produits_nets=round(c - d, 2), clients=round(cf, 2))
        v = q("SELECT VA_NB_FACTURES, VA_NUMERO_DEBUT, VA_NUMERO_FIN, VA_DATE_HEURE FROM FAC_VALIDATION ORDER BY rowid DESC LIMIT 1")
        if v:
            resume["validation"] = dict(zip(("nb_factures", "numero_debut", "numero_fin", "date"), tuple(v[0])))
    return {
        "facturation": "validee" if validee else "preparation",
        "resume": resume,
        "nb_anomalies": {k: len(v) for k, v in A.items()},
        "anomalies": {k: v[:MAX_PAR_RUBRIQUE] for k, v in A.items()},
        "note": ("Donnees a la date du dernier export charge. Les lignes de reduction sont negatives par nature ; "
                 "le forfait matin+soir remplace les lignes etude et garderie du matin."),
    }
