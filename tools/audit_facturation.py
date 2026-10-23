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

import sqlite3
from collections import Counter, defaultdict

from tools.regles_facturation import (
    Contexte,
    code_de_base,
    colonne,
    indice_mois,
    mois_restants,
    prorata_regles,
)
from tools.regles_facturation import charger_regles  # noqa: F401 - reexporte pour mcp_server
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
    # code de ligne ramene a sa ligne d'origine (ETUDE4JREGUL -> ETUDE4J) : les lignes de
    # regularisation compensent la ligne initiale et se cumulent avec elle ; le code reel est garde
    # pour la rubrique ligne_de_regularisation (10e element)
    def lire_lignes(table, p, validation_fixe=None):
        sv = colonne(conn, table, "IDVALIDATION", defaut="'1'") if validation_fixe is None else str(validation_fixe)
        sl = colonne(conn, table, f"{p}LIBELLE_LIGNE")
        return [(int(r[0] or 0), int(r[1] or 0), code_de_base(r[2], regles), _num(r[3]), _num(r[4]), _num(r[5]), r[6], r[7],
                 int(r[8] or 1), r[9], r[2])
                for r in q(f"""SELECT IDELEVE, IDRESPONSABLE, {p}CODE_LIGNE, {p}TOTAL, {p}REMISE_MT_FAMILLE, {p}REMISE_MT_ELEVE,
                                      {p}REMISE_CODE_FAMILLE, {p}REMISE_CODE_ELEVE, {sv}, {sl} FROM {table}""")]
    GL = lire_lignes(L, pl)
    # Preparation complementaire (en cours d'annee) : la preparation ne contient que les lignes de
    # regularisation de quelques familles ; on la juge sur le CUMUL facturation validee + preparation,
    # sinon chaque ligne absente de la preparation serait signalee.
    complementaire = False
    def nb_lignes(table):
        try:
            return q(f"SELECT COUNT(*) FROM {table}")[0][0]
        except sqlite3.OperationalError:  # table absente de l'export (ou fixture de test)
            return 0
    if not validee and nb_lignes("FAC_HISTO_LIGNE"):
        complementaire = True
        histo = lire_lignes("FAC_HISTO_LIGNE", "HL_")
        v_prep = max((g[8] for g in histo), default=0) + 1
        GL = histo + [(*g[:8], v_prep, *g[9:]) for g in GL]
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
    for eid, rid, code, t, rf, re_, cf, ce, v, lib, code_reel in GL:
        if (v != premiere_validation or code_reel != code) and (t or rf or re_):
            alerte("ligne_de_regularisation", eleve=nm(eid) if eid else "(ligne famille)", responsable=rn.get(rid),
                   validation="preparation" if complementaire and v == v_prep else v, ligne=code_reel,
                   **({"compense": code} if code_reel != code else {}), libelle=lib, montant=round(t, 2))
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
    familles_prep = {}
    # Cycle des extras (occasionnels du mois, retards, frais de rejet) : la facture doit s'ajouter a
    # l'echeance suivante sans toucher aux autres (option « Sans solde : avec echeancier existant »).
    # Incident du 23/10/2026 (validation 7, 90 factures) : preparee en « Reprise du solde » sans dates,
    # elle a remplace l'echeancier de 86 familles en prelevement par UNE echeance (solde restant +
    # extras, 287 995,68 EUR au 27/10). Controle : preparation (ou derniere validation) dont toutes les
    # lignes non nulles sont des lignes d'extras, et solde repris sur les factures.
    x_r = regles.get("facturation_extras", {})
    codes_extras = set(x_r.get("lignes", ["CANTOCC", "GARDMATINOCC", "GARDETUDOCC", "RETARDGARDETUD", "FRSIMP"]))
    if complementaire:
        v_cible = v_prep
    elif validee:
        v_cible = max((g[8] for g in GL), default=0)
    else:
        v_cible = None
    lignes_cible = [g for g in GL if v_cible is not None and g[8] == v_cible and (g[3] or g[4] or g[5])]
    cycle_extras = (bool(lignes_cible) and all(g[10] in codes_extras for g in lignes_cible)
                    and (complementaire or (validee and v_cible > premiere_validation)))
    col_solde_pris = f"{pf}SOLDE_PRIS" in fcols
    extras_repris = []
    for rid, f in FAM.items():
        concerne = False
        if cycle_extras:
            montant_x = _num(f.get(f"{pf}APAYER_FACTURE"))
            concerne = (bool(montant_x) if complementaire
                        else str(f.get("IDVALIDATION")) == str(v_cible) and bool(montant_x))
            if concerne:
                ori = _num(f.get(f"{pf}ORI_SOLDE"))
                repris = (_num(f.get(f"{pf}SOLDE_PRIS")) == 1 and bool(ori)) if col_solde_pris else bool(ori)
                if repris:
                    n_x = sum(1 for k in range(1, 13) if _num(f.get(f"{pf}ECHE_PRIX{k}")))
                    extras_repris.append(rid)
                    alerte("extras_en_reprise_du_solde", responsable=rn.get(rid), extras=round(montant_x, 2),
                           solde_repris=round(ori, 2), echeances=n_x,
                           total_echeances=round(sum(_num(f.get(f"{pf}ECHE_PRIX{k}")) for k in range(1, 13)), 2),
                           attention=("facturation des extras en « Reprise du solde » : l'echeancier de la famille "
                                      "est remplace" + (" (une seule echeance)" if n_x <= 1 else "")
                                      + (". Avant validation : effacer le calcul et choisir « Sans solde : avec "
                                         "echeancier existant »." if not validee else
                                         ". Validee : reajuster l'echeancier en comptabilite (Outils › Reajustement "
                                         "des echeanciers) AVANT la remise en banque.")))
                # dans les deux cas, le nombre d'echeances n'est pas a controler ici : extras sur
                # l'echeancier existant (une seule echeance, la suivante, est normale) ou deja signale
        if complementaire:
            # preparation complementaire : seules les familles a montant non nul sont facturees ; leur
            # ORI_SOLDE est le solde restant des factures precedentes (pas une dette)
            montant = _num(f.get(f"{pf}APAYER_FACTURE"))
            if not montant:
                continue
            familles_prep[rid] = montant
        n = sum(1 for k in range(1, 13) if _num(f.get(f"{pf}ECHE_PRIX{k}")))
        solde = _num(FAM1[rid].get(f"{pf}ORI_SOLDE"))
        if not complementaire and solde > regles.get("solde_a_signaler", 100):
            alerte("solde_reporte_important", responsable=rn.get(rid), solde=solde)
        m, iban = ctx.mode.get(rid, (None, False))
        if m == ech_r.get("mode_prelevement", "Prélèvement"):
            idx = indice_mois(f.get(f"{pf}DATE_FACTURE"), regles)
            n_att = min(mois_restants(idx, regles) or ech_r.get("nb_prelevement", 0), ech_r.get("nb_prelevement", 99))
            if n_att and n != n_att and not concerne:
                d = {"responsable": rn.get(rid), "echeances": n, "attendu": n_att, "facture_du": f.get(f"{pf}DATE_FACTURE")}
                if complementaire:
                    d["montant_total_echeances"] = round(sum(_num(f.get(f"{pf}ECHE_PRIX{k}")) for k in range(1, 13)), 2)
                    d["solde_repris"] = solde
                    d["attention"] = "solde restant + complement sur une seule echeance : reactualiser l'echeancier avant de valider"
                alerte("nombre_echeances_prelevement", **d)
            if not iban:
                alerte("prelevement_sans_iban", responsable=rn.get(rid))

    # 5. validation : numerotation et equilibre comptable
    resume = {"eleves_actifs": len(el), "eleves_factures": len(factures & set(el)), "familles": len(FAM), "lignes": len(GL)}
    if complementaire:
        resume["preparation_complementaire"] = {
            "familles_facturees": len(familles_prep), "montant_total": round(sum(familles_prep.values()), 2),
            "lignes": sum(1 for g in GL if g[8] == v_prep and (g[3] or g[4] or g[5])),
            "note": "jugee sur le cumul facturation validee + preparation"}
    if cycle_extras:
        resume["cycle_extras"] = {
            "validation": v_cible if validee else "preparation", "lignes": sorted({g[10] for g in lignes_cible}),
            "familles_en_reprise_du_solde": len(extras_repris),
            "option_attendue": "Sans solde : avec echeancier existant"}
    if fr_r:
        resume["repartition_fratrie"] = {str(k): v for k, v in Counter(
            round(sum(x for c, x in tot[i].items() if c.startswith(fr_r["prefixe_lignes"])), 2) for i in el).items()}
    if validee:
        nums = sorted(int(r[0]) for r in q("SELECT DISTINCT CG_NUMERO_FACTURE FROM FAC_COMPTA_GENERAL") if r[0])
        if nums and nums != list(range(nums[0], nums[-1] + 1)):
            alerte("numerotation_discontinue", premier=nums[0], dernier=nums[-1], nombre=len(nums))
        d, c = q("SELECT SUM(CAST(CG_DEBIT AS REAL)), SUM(CAST(CG_CREDIT AS REAL)) FROM FAC_COMPTA_GENERAL")[0]
        # comptes clients : debit des factures moins credit des avoirs (un avoir manuel credite le client)
        cfd, cfc = q("SELECT SUM(CAST(CF_DEBIT AS REAL)), SUM(CAST(CF_CREDIT AS REAL)) FROM FAC_COMPTA_FAMILLE")[0]
        cf = (cfd or 0) - (cfc or 0)
        d, c = d or 0, c or 0
        resume["comptabilite"] = {"produits": round(c, 2), "reductions": round(d, 2), "clients": round(cf, 2),
                                  "equilibree": abs((c - d) - cf) <= .05}
        if abs((c - d) - cf) > .05:
            alerte("comptabilite_desequilibree", produits_nets=round(c - d, 2), clients=round(cf, 2))
        vs = q("""SELECT IDVALIDATION, VA_TYPE_FACTURE, VA_NB_FACTURES, VA_NUMERO_DEBUT, VA_NUMERO_FIN, VA_DATE_HEURE
                  FROM FAC_VALIDATION ORDER BY CAST(IDVALIDATION AS INTEGER)""")
        resume["validations"] = [dict(zip(("id", "type", "nb_factures", "numero_debut", "numero_fin", "date"), v)) for v in vs]
    return {
        "facturation": "validee" if validee else ("preparation_complementaire" if complementaire else "preparation"),
        "resume": resume,
        "nb_anomalies": {k: len(v) for k, v in A.items()},
        "anomalies": {k: v[:MAX_PAR_RUBRIQUE] for k, v in A.items()},
        "note": ("Donnees a la date du dernier export charge. Les lignes de reduction sont negatives par nature ; "
                 "le forfait matin+soir remplace les lignes etude et garderie du matin. Pour une facturation validee, "
                 "les montants sont le cumul de toutes les validations (initiale + complementaires) ; les rubriques "
                 "ligne_de_regularisation et ligne_au_prorata sont informatives. Pour preparer une facture "
                 "complementaire, voir regularisations_a_preparer."),
    }
