"""Outil MCP - observations des fiches élève et responsable.

Le champ « Observation » de la fiche élève (et ceux de la fiche responsable) sert à
documenter les cas particuliers : jours de cantine, de garderie ou d'étude convenus
hors fiche forfaits, changement de forfait en cours d'année, contraintes de la
famille. Cet outil les rassemble pour les analyses (prestations exceptionnelles,
régularisations de facturation...). Lecture seule.
"""

import re
import unicodedata

from tools.famille import JOURS, _jours, _q
from tools.texte import rtf_en_texte


PRESTATIONS = {"C": "cantine", "M": "garderie du matin", "S": "etude / garderie du soir", "A": "atelier anglais"}
JOURS_LETTRES = {"L": "lundi", "M": "mardi", "J": "jeudi", "V": "vendredi"}
_ACCORD = re.compile(r"^([CMSA])=([A-Za-z0-9]+)(?:@(\d{6}))?$")


def lire_suivi(valeur: str | None) -> dict:
    """Decode le champ « Suivi prestations » (convention v1, <= 60 caracteres) :
    'v1 S=LJ@260901 M=occ@260413' -> {'S': {...}, 'M': {...}} ; jetons illisibles dans 'illisible'."""
    out: dict = {}
    jetons = (valeur or "").split()
    if not jetons:
        return out
    if jetons[0] != "v1":
        return {"illisible": jetons}
    for j in jetons[1:]:
        m = _ACCORD.match(j)
        if not m:
            out.setdefault("illisible", []).append(j)
            continue
        code, val, date = m.groups()
        jours = [JOURS_LETTRES[x] for x in val] if set(val) <= set(JOURS_LETTRES) else None
        out[code] = {"prestation": PRESTATIONS[code], "valeur": val, "jours": jours,
                     "depuis": f"20{date[:2]}-{date[2:4]}-{date[4:]}" if date else None}
    return out


_LIGNE_DATEE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}\b.*\b[CMSA]=\S", re.I)


def journal_claude(observation: str) -> list[str]:
    """Lignes de journal recopiees dans l'observation : prefixe [C] (forme recommandee), ou ligne
    commencant par une date JJ/MM/AA(AA) et contenant un code d'instruction (C=, M=, S=, A=),
    forme saisie a la main sans le prefixe."""
    out = []
    for l in (observation or "").splitlines():
        l = l.strip()
        if l.upper().startswith("[C]") or _LIGNE_DATEE.match(l):
            out.append(l)
    return out


def _plat(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def observations(conn, recherche: str | None = None, classe: str | None = None,
                 inclure_sortis: bool = False, avec_vides: bool = False,
                 a_faire_seulement: bool = False, a_facturer_seulement: bool = False) -> dict:
    """Élèves dont la fiche (ou celle d'un de leurs responsables) porte une observation.

    recherche : texte cherché dans les observations (sans accents ni casse).
    classe : libellé de classe (partiel, ex. 'CM1').
    avec_vides : inclure aussi les élèves sans aucune observation.
    a_faire_seulement : seulement les élèves dont le champ « A faire » porte une instruction
    en attente (valeur commençant par « # »).
    a_facturer_seulement : seulement les élèves dont le champ « A facturer » porte une
    facturation à préparer (valeur commençant par « #F »).
    Renvoie aussi, par élève, les informations complémentaires « Suivi prestations »
    (décodée), « A faire » et « A facturer », et le journal [C] recopié dans l'observation.
    """
    ice = {}
    for r in _q(conn, """SELECT s.IDELEVE, i.ICE_LIBELLE, s.ICES_SAISIE_TEXTE FROM ADM_ICE_SAISIE s
                         JOIN ADM_ICE i ON i.ID_ICE = s.ID_ICE"""):
        lib = _plat(str(r["ICE_LIBELLE"] or ""))
        cle = ("suivi" if lib.startswith("suivi prestations") else "a_facturer" if lib.startswith("a facturer")
               else "a_faire" if lib.startswith("a faire") else None)
        if cle and str(r["ICES_SAISIE_TEXTE"] or "").strip():
            ice.setdefault(str(r["IDELEVE"]), {})[cle] = str(r["ICES_SAISIE_TEXTE"]).strip()
    classes = {str(r["IDCLASSE"]): r["CL_LIBELLE"] for r in _q(conn, "SELECT IDCLASSE, CL_LIBELLE FROM COM_CLASSES")}
    resp = {str(r["IDRESPONSABLE"]): r for r in _q(conn, "SELECT * FROM COM_RESPONSABLES")}
    liens: dict[str, list[str]] = {}
    for l in _q(conn, "SELECT IDELEVE, IDRESPONSABLE FROM COM_LIENER"):
        liens.setdefault(str(l["IDELEVE"]), []).append(str(l["IDRESPONSABLE"]))
    act: dict[str, dict] = {}
    for a in _q(conn, "SELECT * FROM PA_SUIVI_CONSOMMATEUR"):
        if str(a.get("SI_CODE")) not in ("-1", "", "None"):
            act.setdefault(str(a["IDPASSANT"]), {})[a["SI_CODE"]] = _jours(a, "JOUR")
    cible = _plat(recherche) if recherche else None
    out = []
    for e in _q(conn, "SELECT * FROM COM_ELEVES"):
        if not inclure_sortis and str(e.get("EL_DATE_SORTIE") or "").strip():
            continue
        cl = classes.get(str(e.get("EL_IDCLASSE")), e.get("EL_IDCLASSE"))
        if classe and _plat(classe) not in _plat(str(cl or "")):
            continue
        i = str(e["IDELEVE"])
        obs = rtf_en_texte(e.get("EL_OBSERVATION"))
        rs = []
        for rid in liens.get(i, []):
            r = resp.get(rid)
            if not r:
                continue
            o, of = rtf_en_texte(r.get("RE_OBSERVATION")), rtf_en_texte(r.get("RE_OBSERVATION_FACTU"))
            if o or of:
                rs.append({"id_responsable": rid, "responsable": f"{r.get('RE_NOM1') or ''} {r.get('RE_PRENOM1') or ''}".strip(),
                           "observation": o or None, "observation_facturation": of or None})
        champs = ice.get(i, {})
        if a_faire_seulement and not champs.get("a_faire", "").startswith("#"):
            continue
        if a_facturer_seulement and not champs.get("a_facturer", "").startswith("#"):
            continue
        if not (obs or rs or champs) and not avec_vides:
            continue
        if cible and cible not in _plat(" ".join([obs, champs.get("suivi", ""), champs.get("a_faire", ""),
                                                   champs.get("a_facturer", "")]
                                                  + [x["observation"] or "" for x in rs]
                                                  + [x["observation_facturation"] or "" for x in rs])):
            continue
        out.append({"id_eleve": i, "eleve": f"{e.get('EL_NOM1') or ''} {e.get('EL_PRENOM1') or ''}".strip(),
                    "classe": cl, "observation": obs or None,
                    "jours_cantine": _jours(e, "EL_REPASMIDI"), "activites": act.get(i, {}),
                    "observations_responsables": rs,
                    "suivi_prestations": champs.get("suivi"), "suivi_decode": lire_suivi(champs.get("suivi")),
                    "a_faire": champs.get("a_faire"), "a_facturer": champs.get("a_facturer"),
                    "journal": journal_claude(obs)})
    out.sort(key=lambda x: (str(x["classe"] or ""), x["eleve"]))
    return {"nombre": len(out), "eleves": out,
            "note": ("Jours au format lundi..vendredi ; activites = inscriptions Charlemagne "
                     "(MATIN = garderie du matin, ETUDE = etude / garderie du soir). suivi_prestations : "
                     "accords en vigueur (v1, C/M/S/A = cantine/matin/soir/anglais, @AAMMJJ = depuis) ; "
                     "a_faire : instruction en attente pour le secretariat si elle commence par #, OK #n = verifiee ; "
                     "a_facturer : facturation a preparer avec l'assistant si elle commence par #F, "
                     "OK #Fn = facturee ; "
                     "journal : lignes [C] recopiees par le secretariat dans l'observation.")}


__all__ = ["observations", "lire_suivi", "journal_claude", "JOURS"]
