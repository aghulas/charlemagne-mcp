"""Outils MCP - audit de la facturation (preparation ou facturation validee).

Compare chaque ligne facturee a ce qu'imposent les donnees sources (jours de cantine,
activites, informations complementaires, liens eleve-responsable) et les regles
tarifaires de l'etablissement, puis controle les reductions, l'APEL, les echeances
et, pour une facturation validee, la numerotation et l'equilibre comptable.

En cours d'annee, la facturation validee est le cumul de toutes les validations
(facturation initiale + factures complementaires / avoirs manuels) : les lignes
sont additionnees par eleve et par code, l'echeancier lu sur la derniere facture
de chaque responsable (dont le solde repris n'est pas une dette), et une ligne
facturee au prorata (k/10 du tarif) est signalee en information, pas en anomalie.

Le module est generique : tarifs, codes de lignes et regles viennent d'un fichier
JSON (variable d'environnement CHARLEMAGNE_REGLES_FACTURATION), jamais du code.
Voir docs/regles_facturation.exemple.json pour le format. Le calcul des lignes
attendues est dans tools/regles_facturation.py (partage avec le suivi en cours
d'annee).

Lecture seule. Aucune donnee bancaire n'est renvoyee.
"""

from collections import Counter, defaultdict

from tools.regles_facturation import (
    Contexte,
    charger_regles,  # noqa: F401 - reexporte pour mcp_server
    colonne,
    indice_mois,
    mois_restants,
    prorata_regles,
)
from tools.regles_facturation import num as _num

MAX_PAR_RUBRIQUE = 40


def _prorata(facture: float, attendu: float, nb: int) -> int | None:
    """k si facture == attendu * k / nb (ligne facturee au prorata), sinon None."""
    if not attendu:
        return None
    for k in range(1, nb + 1):
        if abs(facture - attendu * k / nb) <= .02:
            return k
    return None


def audit_facturation(conn, regles: dict, validee: bool = False) -> dict:
    q = lambda s, p=(): conn.execute(s, p).fetchall()
    L, F, pl, pf = (("FAC_HISTO_LIGNE", "FAC_HISTO_FAMILLE", "HL_", "HF_") if validee
                    else ("FAC_GESTION_LIGNE", "FAC_GESTION_FAMILLE", "GL_", "GF_"))
    if not q(f"SELECT COUNT(*) FROM {L}")[0][0]:
        raise ValueError(f"{L} est vide : " + ("aucune facturation validee." if validee
                         else "aucune preparation en cours (deja validee ? relancer avec validee=True)."))
    ctx = Contexte(conn, regles)
    el, pay, princ, nm, rn = ctx.el, ctx.pay, ctx.princ, ctx.nom, ctx.rn
    _, nb_mois = prorata_regles(regles)
    A = defaultdict(list)
    alerte = lambda rub, **d: A[rub].append(d)
    sel_val = colonne(conn, L, "IDVALIDATION", defaut="'1'")
    sel_lib = colonne(conn, L, f"{pl}LIBELLE_LIGNE")
    GL = [(int(r[0] or 0), int(r[1] or 0), r[2], _num(r[3]), _num(r[4]), _num(r[5]), r[6], r[7], int(r[8] or 1), r[9])
          for r in q(f"""SELECT IDELEVE, IDRESPONSABLE, {pl}CODE_LIGNE, {pl}TOTAL, {pl}REMISE_MT_FAMILLE, {pl}REMISE_MT_ELEVE,
                                {pl}REMISE_CODE_FAMILLE, {pl}REMISE_CODE_ELEVE, {sel_val}, {sel_lib} FROM {L}""")]
    premiere_validation = min((g[8] for g in GL), default=1)

    # 1. perimetre et payeurs
    factures = {g[0] for g in GL if g[0]}
    for i in el:
        if i not in factures:
            alerte("eleve_actif_non_facture", eleve=nm(i), entre_le=ctx.entree(i) or None)
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

    # 2. lignes par eleve (cumul de toutes les validations)
    tot, part = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for eid, rid, code, t, *_ in GL:
        if eid in el:
            tot[eid][code] += t
            part[(eid, code)][rid] += t
    for eid, rid, code, t, rf, re_, cf, ce, v, lib in GL:
        if v != premiere_validation and (t or rf or re_):
            alerte("ligne_de_regularisation", eleve=nm(eid) if eid else "(ligne famille)", responsable=rn.get(rid),
                   validation=v, ligne=code, libelle=lib, montant=round(t, 2))
    controles = ctx.prefixes_controles()
    contrib = defaultdict(Counter)
    for i in el:
        g = tot[i]
        att, anomalies = ctx.attendu_eleve(i)
        for a in anomalies:
            alerte(a, eleve=nm(i))
        for code in set(att) | {c for c in g if any(c.startswith(k) for k in controles)}:
            f, a = g.get(code, 0), att.get(code, 0)
            if abs(f - a) > .01:
                k = _prorata(f, a, nb_mois)
                if k:
                    alerte("ligne_au_prorata", eleve=nm(i), ligne=code, facture=round(f, 2), tarif_annuel=a,
                           prorata=f"{k}/{nb_mois}")
                else:
                    alerte("ligne_incorrecte", eleve=nm(i), ligne=code, facture=round(f, 2), attendu=a)
        rg = regles.get("lignes_regroupement_contribution", [])
        if rg:
            contrib[ctx.classe(i)][round(sum(v for c, v in g.items() if c in rg), 2)] += 1
    for cl, c in contrib.items():
        if len(c) > 1:
            alerte("contribution_differente_dans_une_classe", classe=cl, montants=dict(c))

    # 3. fratrie et remises
    fr_r = regles.get("fratrie")
    if fr_r:
        for i in el:
            fr = sum(v for c, v in tot[i].items() if c.startswith(fr_r["prefixe_lignes"]))
            f_att = ctx.fratrie_attendue(i)
            if f_att["personnel"]:
                if fr and not fr_r.get("cumul_avec_personnel", False):
                    alerte("fratrie_cumulee_avec_remise_personnel", eleve=nm(i), fratrie=round(fr, 2))
                continue
            attendu = f_att["montant"]
            if abs(fr - attendu) > .02:
                alerte("reduction_fratrie_hors_regle", eleve=nm(i), facture=round(fr, 2), attendu=attendu,
                       a_l_ecole=f_att["a_l_ecole"], exterieurs=f_att["exterieurs"], justifie=f_att["justifie"])
            if f_att["exterieurs"] and not f_att["justifie"]:
                alerte("enfants_exterieurs_sans_justificatif", eleve=nm(i), responsable=rn.get(princ.get(i)))
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
    for eid, rid, code, t, rf, re_, cf, ce, *_ in GL:
        if rf and cf and eid in el and not ctx.est_perso(eid):
            alerte("remise_famille_sans_code_personnel", eleve=nm(eid), remise=cf)
        if re_ and ce not in rem_eleve_ok:
            alerte("remise_eleve_inattendue", eleve=nm(eid), ligne=code, remise=ce, montant=re_)
    for i in el:
        if ctx.est_perso(i) and not any(g[0] == i and g[4] for g in GL):
            alerte("famille_du_personnel_sans_remise", eleve=nm(i))

    # 4. APEL, soldes, echeances (derniere facture de chaque responsable)
    fcols = [r[1] for r in conn.execute(f"PRAGMA table_info({F})")]
    ordre = " ORDER BY CAST(IDVALIDATION AS INTEGER)" if "IDVALIDATION" in fcols else ""
    FAM = {int(r[0]): dict(zip(fcols, r[1:])) for r in q(f"SELECT IDRESPONSABLE, * FROM {F}{ordre}")}
    # premiere facture de chaque responsable : son solde d'origine est le solde reporte de l'annee
    # precedente ; sur une facture complementaire, ORI_SOLDE est le solde repris des factures
    # precedentes (pas une dette)
    FAM1 = {int(r[0]): dict(zip(fcols, r[1:])) for r in q(f"SELECT IDRESPONSABLE, * FROM {F}{ordre.replace('INTEGER)', 'INTEGER) DESC') if ordre else ''}")}
    ap_r = regles.get("apel")
    if ap_r:
        apel = defaultdict(float)
        for eid, rid, code, t, *_ in GL:
            if code == ap_r["ligne"]:
                apel[rid] += t
        for rid in FAM:
            att = ctx.apel_attendue(rid)
            if abs(apel.get(rid, 0) - att) > .01:
                alerte("apel_incorrecte", responsable=rn.get(rid), foyer=ctx.foyer_apel.get(rid),
                       facture=round(apel.get(rid, 0), 2), attendu=att)
    ech_r = regles.get("echeances", {})
    for rid, f in FAM.items():
        n = sum(1 for k in range(1, 13) if _num(f.get(f"{pf}ECHE_PRIX{k}")))
        solde = _num(FAM1[rid].get(f"{pf}ORI_SOLDE"))
        if solde > regles.get("solde_a_signaler", 100):
            alerte("solde_reporte_important", responsable=rn.get(rid), solde=solde)
        m, iban = ctx.mode.get(rid, (None, False))
        if m == ech_r.get("mode_prelevement", "Prélèvement"):
            idx = indice_mois(f.get(f"{pf}DATE_FACTURE"), regles)
            n_att = min(mois_restants(idx, regles) or ech_r.get("nb_prelevement", 0), ech_r.get("nb_prelevement", 99))
            if n_att and n != n_att:
                alerte("nombre_echeances_prelevement", responsable=rn.get(rid), echeances=n, attendu=n_att,
                       facture_du=f.get(f"{pf}DATE_FACTURE"))
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
        vs = q("""SELECT IDVALIDATION, VA_TYPE_FACTURE, VA_NB_FACTURES, VA_NUMERO_DEBUT, VA_NUMERO_FIN, VA_DATE_HEURE
                  FROM FAC_VALIDATION ORDER BY CAST(IDVALIDATION AS INTEGER)""")
        resume["validations"] = [dict(zip(("id", "type", "nb_factures", "numero_debut", "numero_fin", "date"), v)) for v in vs]
    return {
        "facturation": "validee" if validee else "preparation",
        "resume": resume,
        "nb_anomalies": {k: len(v) for k, v in A.items()},
        "anomalies": {k: v[:MAX_PAR_RUBRIQUE] for k, v in A.items()},
        "note": ("Donnees a la date du dernier export charge. Les lignes de reduction sont negatives par nature ; "
                 "le forfait matin+soir remplace les lignes etude et garderie du matin. Pour une facturation validee, "
                 "les montants sont le cumul de toutes les validations (initiale + complementaires) ; les rubriques "
                 "ligne_de_regularisation et ligne_au_prorata sont informatives. Pour preparer une facture "
                 "complementaire, voir regularisations_a_preparer."),
    }
