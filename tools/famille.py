"""Outils MCP - fiche famille : tout ce qu'il faut pour controler une famille en un appel.

A partir d'un eleve (IDELEVE) ou d'un foyer (IDFOYER) : foyer (cotisation APEL),
responsables (lien, responsable principal, payeur et pourcentage, mode de reglement,
IBAN renseigne ou non, enfants a charge, quotients, informations complementaires),
enfants (classe, regime, jours de cantine, activites, informations complementaires,
remises), lignes facturees (preparation en cours, ou derniere facturation validee) et
pieces a verser recues.

Lecture seule. Aucune coordonnee bancaire n'est renvoyee (seulement renseigne / vide).
"""

import sqlite3

from tools.referentiels import libelles_csp, libelles_liens, libelles_situations_familiales

JOURS = (("lundi", "1"), ("mardi", "2"), ("mercredi", "3"), ("jeudi", "4"), ("vendredi", "5"))


def _q(conn, sql: str, params: tuple = ()) -> list[dict]:
    """Requete parametree ; une table absente de l'export (non exportee cette annee)
    donne une liste vide plutot qu'une erreur."""
    try:
        cur = conn.execute(sql, params)
    except sqlite3.OperationalError:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _in(n: int) -> str:
    return ",".join("?" * n)


def _num(v) -> float:
    try:
        return round(float(v), 2) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _jours(row: dict, prefixe: str) -> list[str]:
    return [nom for nom, n in JOURS if str(row.get(f"{prefixe}{n}") or "") == "1"]


def _renseigne(v) -> str:
    return "renseigne" if str(v or "").strip() else "vide"


def _foyers(conn, id_eleve, id_foyer) -> set[str]:
    if id_foyer not in (None, ""):
        if not _q(conn, "SELECT 1 FROM COM_RESPONSABLES WHERE IDFOYER = ?", (str(id_foyer),)):
            raise ValueError(f"Aucun responsable dans le foyer IDFOYER={id_foyer!r}")
        return {str(id_foyer)}
    if not _q(conn, "SELECT 1 FROM COM_ELEVES WHERE IDELEVE = ?", (str(id_eleve),)):
        raise ValueError(f"Aucun eleve avec IDELEVE={id_eleve!r}")
    rows = _q(conn, """SELECT DISTINCT r.IDFOYER FROM COM_LIENER l
                       JOIN COM_RESPONSABLES r ON r.IDRESPONSABLE = l.IDRESPONSABLE
                       WHERE l.IDELEVE = ?""", (str(id_eleve),))
    foyers = {str(r["IDFOYER"]) for r in rows if str(r["IDFOYER"] or "").strip()}
    if not foyers:
        raise ValueError(f"L'eleve {id_eleve!r} n'a aucun responsable lie (COM_LIENER).")
    return foyers


def _source_facturation(conn, validee: bool | None) -> tuple[str, str, str, tuple] | None:
    """-> (table, prefixe, libelle, filtre) de la facturation a lire : la preparation en
    cours si elle existe, sinon le cumul de toutes les validations (facturation initiale
    + factures complementaires / avoirs de l'annee)."""
    prep = _q(conn, "SELECT COUNT(*) AS n FROM FAC_GESTION_LIGNE")
    if validee is not True and prep and prep[0]["n"]:
        return "FAC_GESTION_LIGNE", "GL_", "preparation en cours (non validee)", ("", ())
    vals = _q(conn, "SELECT DISTINCT CAST(IDVALIDATION AS INTEGER) AS v FROM FAC_HISTO_LIGNE ORDER BY 1")
    if validee is not False and vals:
        ids = [r["v"] for r in vals if r["v"] is not None]
        return ("FAC_HISTO_LIGNE", "HL_",
                f"facturation validee, cumul des validations {ids}" if len(ids) > 1 else f"facturation validee (IDVALIDATION {ids[0]})",
                ("", ()))
    return None


def fiche_famille(conn, id_eleve: str | None = None, id_foyer: str | None = None,
                  validee: bool | None = None) -> dict:
    if id_eleve in (None, "") and id_foyer in (None, ""):
        raise ValueError("Indiquer id_eleve ou id_foyer.")
    foyers = sorted(_foyers(conn, id_eleve, id_foyer))
    resp = _q(conn, f"SELECT * FROM COM_RESPONSABLES WHERE IDFOYER IN ({_in(len(foyers))})", tuple(foyers))
    rids = [str(r["IDRESPONSABLE"]) for r in resp]
    liens = _q(conn, f"SELECT * FROM COM_LIENER WHERE IDRESPONSABLE IN ({_in(len(rids))})", tuple(rids)) if rids else []
    eids = sorted({str(l["IDELEVE"]) for l in liens}, key=lambda x: int(x) if x.isdigit() else 0)
    regimes = {str(r["IDREGIME"]): r["RG_LIBELLE"] for r in _q(conn, "SELECT IDREGIME, RG_LIBELLE FROM FAC_REGIME")}
    icr_lib = {str(r["ID_ICR"]): r["ICR_LIBELLE"] for r in _q(conn, "SELECT ID_ICR, ICR_LIBELLE FROM ADM_ICR")}
    ice_lib = {str(r["ID_ICE"]): r["ICE_LIBELLE"] for r in _q(conn, "SELECT ID_ICE, ICE_LIBELLE FROM ADM_ICE")}
    noms_e, noms_r = {}, {str(r["IDRESPONSABLE"]): f"{r.get('RE_NOM1') or ''} {r.get('RE_PRENOM1') or ''}".strip() for r in resp}

    # --- foyers
    fo = [{"id_foyer": f["IDFOYER"], "nom": f.get("NOM"), "cotisation_apel": f.get("COT_APEL"),
           "id_resp_financier": f.get("ID_RESP_FINANCIER")}
          for f in _q(conn, f"SELECT * FROM COM_FOYER WHERE IDFOYER IN ({_in(len(foyers))})", tuple(foyers))]

    # --- enfants
    enfants = []
    rows = _q(conn, f"""SELECT e.*, c.CL_LIBELLE FROM COM_ELEVES e LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE
                        WHERE e.IDELEVE IN ({_in(len(eids))})""", tuple(eids)) if eids else []
    for e in rows:
        i = str(e["IDELEVE"])
        noms_e[i] = f"{e.get('EL_NOM1') or ''} {e.get('EL_PRENOM1') or ''}".strip()
        act = {a["SI_CODE"]: _jours(a, "JOUR") for a in _q(
            conn, "SELECT * FROM PA_SUIVI_CONSOMMATEUR WHERE IDPASSANT = ?", (i,))}
        infos = {ice_lib.get(str(s["ID_ICE"]), s["ID_ICE"]): s.get("ICES_SAISIE_TEXTE") or s.get("ICES_SAISIE_NBRE")
                 for s in _q(conn, "SELECT * FROM ADM_ICE_SAISIE WHERE IDELEVE = ?", (i,))}
        remises = [{"code": e.get(f"EL_REMISE_CODE{n}"), "valeur": e.get(f"EL_REMISE_VALEUR{n}"),
                    "nature": e.get(f"EL_REMISE_NATURE{n}")}
                   for n in range(1, 5) if str(e.get(f"EL_REMISE_CODE{n}") or "").strip()]
        enfants.append({
            "id_eleve": i, "eleve": noms_e[i], "classe": e.get("CL_LIBELLE"),
            "sorti_le": e.get("EL_DATE_SORTIE") or None,
            "regime": regimes.get(str(e.get("EL_IDREGIME")), e.get("EL_IDREGIME")),
            "jours_cantine": _jours(e, "EL_REPASMIDI"),
            "activites": act, "informations_complementaires": infos, "remises": remises,
        })

    # --- responsables (jamais de coordonnees bancaires : seulement renseigne / vide)
    lib_lien, lib_csp, lib_sitfam = libelles_liens(conn), libelles_csp(conn), libelles_situations_familiales(conn)
    responsables = []
    for r in resp:
        rid = str(r["IDRESPONSABLE"])
        infos = {icr_lib.get(str(s["ID_ICR"]), s["ID_ICR"]): s.get("ICRS_SAISIE_TEXTE") or s.get("ICRS_SAISIE_NBRE")
                 for s in _q(conn, "SELECT * FROM ADM_ICR_SAISIE WHERE IDRESPONSABLE = ?", (rid,))}
        responsables.append({
            "id_responsable": rid, "responsable": noms_r[rid], "id_foyer": r.get("IDFOYER"),
            "mode_reglement": r.get("RE_MODE_REGLEMENT"), "iban": _renseigne(r.get("RE_IBAN")),
            "situation_familiale": lib_sitfam.get(str(r.get("RE_ID_SITFAM") or ""), r.get("RE_ID_SITFAM") or None),
            "csp": lib_csp.get(str(r.get("RE_CSP1") or ""), r.get("RE_CSP1") or None),
            "enfants_a_charge": r.get("RE_ENF_A_CHARGE"), "quotient1": r.get("RE_QUOTIENT1") or None,
            "quotient2": r.get("RE_QUOTIENT2") or None, "cotisation_apel": r.get("RE_COT_APEL") or None,
            "informations_complementaires": infos,
            "liens": [{"id_eleve": str(l["IDELEVE"]), "eleve": noms_e.get(str(l["IDELEVE"])), "lien": l.get("LER_LIEN"),
                       "lien_libelle": lib_lien.get(l.get("LER_LIEN"), l.get("LER_LIEN")),
                       "responsable_principal": str(l.get("LER_TYPE_RESP")) == "1",
                       "payeur": str(l.get("LER_VERSQUI")) == "1", "pourcentage": _num(l.get("LER_POURCENTAGE"))}
                      for l in liens if str(l["IDRESPONSABLE"]) == rid],
        })

    # --- facturation
    facturation = {"source": "aucune facturation dans l'export", "lignes": [], "total_par_responsable": {}}
    src = _source_facturation(conn, validee) if rids else None
    if src:
        table, p, libelle, (filtre, fparams) = src
        lignes = _q(conn, f"SELECT * FROM {table} WHERE IDRESPONSABLE IN ({_in(len(rids))}){filtre}",
                    tuple(rids) + fparams)
        out, tot = [], {}
        for l in sorted(lignes, key=lambda x: (str(x["IDELEVE"]), _num(x.get(f"{p}NUMLIGNE")))):
            a_payer = _num(l.get(f"{p}APAYER_LIGNE"))
            remises = [_num(l.get(f"{p}REMISE_MT_{k}")) for k in ("ELEVE", "FAMILLE", "AUTO")]
            if not a_payer and not any(remises):
                continue  # lignes a zero (prestations non prises) : bruit
            rid, eid = str(l["IDRESPONSABLE"]), str(l["IDELEVE"] or "0")
            # Une ligne « regroupee avec » X est le detail d'une ligne de regroupement X
            # (ex. CONTRIB, DDEC, ASEC... dans CONTRIBUTION) : l'additionner compterait deux fois.
            regroupee = str(l.get(f"{p}REGROUPE_AVEC") or "").strip()
            out.append({"eleve": noms_e.get(eid, "(ligne famille)" if eid in ("0", "") else eid),
                        "responsable": noms_r.get(rid, rid),
                        **({"validation": l["IDVALIDATION"]} if "IDVALIDATION" in l else {}),
                        "code": l.get(f"{p}CODE_LIGNE"),
                        "libelle": l.get(f"{p}LIBELLE_LIGNE"), "quantite": _num(l.get(f"{p}QUANTITE")),
                        "prix": _num(l.get(f"{p}PRIX")), "remise_eleve": remises[0], "remise_famille": remises[1],
                        "remise_auto": remises[2], "a_payer": a_payer,
                        **({"detail_de": regroupee} if regroupee else {})})
            if not regroupee:
                tot[noms_r.get(rid, rid)] = round(tot.get(noms_r.get(rid, rid), 0) + a_payer, 2)
        fam_table, fp = ("FAC_HISTO_FAMILLE", "HF_") if table == "FAC_HISTO_LIGNE" else ("FAC_GESTION_FAMILLE", "GF_")
        factures, detail = {}, {}
        for f in _q(conn, f"SELECT * FROM {fam_table} WHERE IDRESPONSABLE IN ({_in(len(rids))}){filtre}"
                          + (" ORDER BY CAST(IDVALIDATION AS INTEGER)" if fp == "HF_" else ""), tuple(rids) + fparams):
            nom = noms_r.get(str(f["IDRESPONSABLE"]), f["IDRESPONSABLE"])
            factures[nom] = round(factures.get(nom, 0) + _num(f.get(f"{fp}APAYER_FACTURE")), 2)
            if fp == "HF_":
                detail.setdefault(nom, []).append({
                    "validation": f.get("IDVALIDATION"), "numero": f.get("HF_NUMERO_FACTURE"), "type": f.get("HF_TYPE"),
                    "date": f.get("HF_DATE_FACTURE"), "montant": _num(f.get("HF_APAYER_FACTURE")),
                    "solde_origine": _num(f.get("HF_ORI_SOLDE")), "mode_reglement": f.get("HF_MODE_REGLEMENT"),
                    "echeances": [{"date": f.get(f"HF_ECHE_DATE{k}"), "montant": _num(f.get(f"HF_ECHE_PRIX{k}"))}
                                  for k in range(1, 13) if _num(f.get(f"HF_ECHE_PRIX{k}"))]})
        facturation = {"source": libelle, "lignes": out, "total_par_responsable": tot,
                       "montant_facture_charlemagne": factures}
        if detail:
            facturation["factures"] = detail
        attente = [{"responsable": noms_r.get(str(a["IDRESPONSABLE"]), a["IDRESPONSABLE"]),
                    "eleve": noms_e.get(str(a["IDELEVE"]), "(ligne famille)"), "code": a.get("GH_CODE_LIGNE"),
                    "quantite": _num(a.get("GH_QTE")), "prix": _num(a.get("GH_PRIX")), "libelle": a.get("GH_LIBELLE")}
                   for a in _q(conn, f"SELECT * FROM FAC_GESTION_HISTO WHERE IDRESPONSABLE IN ({_in(len(rids))})", tuple(rids))]
        if attente:
            facturation["preparation_manuelle_en_attente"] = attente

    # --- pieces a verser (liste de type E = eleve, F = famille/responsable)
    pieces_dossier = {str(r["IDPIECE_DOSSIER"]): r["LIBELLE"] for r in _q(conn, "SELECT * FROM INS_PIECES_DOSSIER")}
    pieces_liste = {}
    for r in _q(conn, "SELECT * FROM COM_LIEN_PIECE_LISTE"):
        pieces_liste.setdefault(str(r["ID_LISTE_PIECE"]), []).append(
            (str(r["ID_LIEN_PIECE_LISTE"]), pieces_dossier.get(str(r["IDPIECE_DOSSIER"]), r["IDPIECE_DOSSIER"])))
    recues = {(str(r["ID_LIEN_PIECE_PERSONNE"]), str(r["ID_LIEN_PIECE_LISTE"])): r.get("ETAT")
              for r in _q(conn, "SELECT * FROM COM_PIECE_RECU")}
    listes = {str(r["ID_LISTE_PIECE"]): r for r in _q(conn, "SELECT * FROM COM_LISTE_PIECE")}
    personnes = {**{i: n for i, n in noms_e.items()}, **{i: n for i, n in noms_r.items()}}
    pieces = []
    for lp in _q(conn, "SELECT * FROM COM_LIEN_PIECE_PERSONNE"):
        pid, lid = str(lp["ID_PERSONNE"]), str(lp["ID_LISTE_PIECE"])
        liste = listes.get(lid, {})
        concerne = pid in (noms_r if liste.get("TYPE") == "F" else noms_e)
        if not concerne:
            continue
        for lien_piece, libelle in pieces_liste.get(lid, []):
            etat = recues.get((str(lp["ID_LIEN_PIECE_PERSONNE"]), lien_piece))
            pieces.append({"liste": liste.get("LIBELLE", lid), "piece": libelle, "personne": personnes.get(pid, pid),
                           "etat": etat or "non recue"})

    return {
        "foyers": fo,
        "responsables": responsables,
        "enfants": enfants,
        "facturation": facturation,
        "pieces_a_verser": pieces,
        "note": ("Base a jour a la date du dernier export Charlemagne charge. Lignes facturees a zero "
                 "omises. Facturation validee = cumul de toutes les validations de l'annee (initiale + "
                 "complementaires), detail par facture dans 'factures'. Aucune coordonnee bancaire renvoyee. "
                 "Pour le controle des regles tarifaires, voir audit_de_facturation ; pour une facture "
                 "complementaire, regularisations_a_preparer."),
    }
