"""Journal des transferts Charlemagne -> EcoleDirecte (lecture seule).

Charlemagne ecrit, a chaque transfert vers EcoleDirecte (automatique la nuit ou
lance a la main depuis Outils), un bloc dans le fichier texte
`Documents/EcoleDirecte/EcoleDirecte Journal <RNE>.txt` du partage serveur :

    -DEBUT EXPORT ECOLE DIRECTE (14.0.0.0)  : le 01/10/2026 a 19h25m12s par (POSTE)
    Mode                    : Automatique - httpsV3
    Module                  : Outils
    Replication Administratif : Cycle normal
    ...
    Photos des eleves       : Sans - Dernier envoi le 24/09/2026
    Documents pdf envoyes   : 2
    -FIN EXPORT ECOLE DIRECTE : le 01/10/2026 a 19h26m40s

Ce fichier n'est PAS dans l'export CSV : on le lit dans la copie locale du
partage (chemin donne par CHARLEMAGNE_JOURNAL_ED). C'est la seule trace, cote
Charlemagne, des documents publies dans l'espace Documents d'EcoleDirecte
(circulaires, factures, documents a signer) : on y lit QUAND et COMBIEN de PDF
sont partis, jamais leur intitule ni leurs destinataires (a lire dans
EcoleDirecte : outil ed_admin_documents_ecole du connecteur EcoleDirecte).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

_DEBUT = re.compile(
    r"^-DEBUT EXPORT ECOLE DIRECTE \(([\d.]+)\)\s*:\s*le (\d{2}/\d{2}/\d{4}) à (\d{2})h(\d{2})m(\d{2})s"
    r"(?: par \(([^)]*)\))?"
)
_FIN = re.compile(r"^-FIN EXPORT ECOLE DIRECTE\s*:\s*le (\d{2}/\d{2}/\d{4}) à (\d{2})h(\d{2})m(\d{2})s")
_CHAMP = re.compile(r"^([^:\t][^:]*?)\s*:\s*(.*)$")


def _horodatage(d: str, h: str, m: str, s: str) -> str:
    return datetime.strptime(f"{d} {h}:{m}:{s}", "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")


def _cle(libelle: str) -> str:
    return re.sub(r"\s+", " ", libelle).strip()


def lire_texte(chemin: str | Path) -> str:
    brut = Path(chemin).read_bytes()
    try:
        return brut.decode("utf-8")
    except UnicodeDecodeError:
        return brut.decode("cp1252", errors="replace")


def parser_journal(texte: str) -> list[dict]:
    """Blocs du journal -> transferts (ordre du fichier : le plus recent en tete)."""
    transferts: list[dict] = []
    courant: dict | None = None
    for ligne in texte.splitlines():
        ligne = ligne.rstrip()
        m = _DEBUT.match(ligne)
        if m:
            courant = {
                "debut": _horodatage(*m.group(2, 3, 4, 5)),
                "fin": None,
                "version": m.group(1),
                "poste": (m.group(6) or "").strip() or None,
                "mode": None,
                "module": None,
                "replications": {},
                "documents_pdf_envoyes": None,
                "photos": None,
                "erreurs": [],
                "abandon": None,
            }
            transferts.append(courant)
            continue
        if courant is None:
            continue
        m = _FIN.match(ligne)
        if m:
            courant["fin"] = _horodatage(*m.groups())
            continue
        m = _CHAMP.match(ligne)
        if not m:
            continue
        cle, valeur = _cle(m.group(1)), m.group(2).strip()
        if cle.startswith("Réplication") or cle.startswith("Replication"):
            courant["replications"][cle.split(" ", 1)[1]] = valeur
        elif cle == "Mode":
            courant["mode"] = valeur
        elif cle == "Module":
            courant["module"] = valeur
        elif cle.startswith("Documents pdf envoy"):
            courant["documents_pdf_envoyes"] = int(valeur) if valeur.isdigit() else valeur
        elif cle.startswith("Photos des"):
            courant["photos"] = valeur
        elif cle == "ERREUR":
            # tronque : le message d'erreur contient l'URL du webservice, inutile ici
            courant["erreurs"].append(valeur.split(" Type erreur")[0][:200])
        elif cle == "ABANDON":
            courant["abandon"] = valeur[:200]
    for t in transferts:
        if t["erreurs"] or t["abandon"]:
            t["statut"] = "erreur" if t["erreurs"] else "abandon"
        elif t["fin"] is None:
            t["statut"] = "inacheve"
        else:
            t["statut"] = "ok"
        if not t["erreurs"]:
            del t["erreurs"]
        if t["abandon"] is None:
            del t["abandon"]
    return transferts


def chemin_journal(chemin: str | None = None) -> Path:
    p = chemin or os.environ.get("CHARLEMAGNE_JOURNAL_ED")
    if not p:
        raise ValueError("Journal introuvable : definir CHARLEMAGNE_JOURNAL_ED (copie locale du "
                         "fichier 'EcoleDirecte Journal <RNE>.txt' du partage serveur).")
    p = Path(p).expanduser()
    if not p.is_file():
        raise ValueError(f"Journal introuvable : {p.name} (verifier CHARLEMAGNE_JOURNAL_ED).")
    return p


def journal_transferts(depuis: str | None = None, jusqu_a: str | None = None,
                       avec_documents_seulement: bool = False, limite: int = 50,
                       chemin: str | None = None) -> dict:
    p = chemin_journal(chemin)
    tous = parser_journal(lire_texte(p))
    res = []
    for t in tous:
        jour = t["debut"][:10]
        if depuis and jour < depuis:
            continue
        if jusqu_a and jour > jusqu_a:
            continue
        if avec_documents_seulement and not (isinstance(t["documents_pdf_envoyes"], int)
                                             and t["documents_pdf_envoyes"] > 0):
            continue
        res.append(t)
    res.sort(key=lambda t: t["debut"], reverse=True)
    publications = [
        {"date": t["debut"], "documents_pdf_envoyes": t["documents_pdf_envoyes"],
         "mode": t["mode"], "poste": t["poste"]}
        for t in res if isinstance(t["documents_pdf_envoyes"], int) and t["documents_pdf_envoyes"] > 0
    ]
    maj = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return {
        "fichier_mis_a_jour_le": maj,
        "nb_transferts": len(res),
        "nb_en_erreur": sum(1 for t in res if t["statut"] != "ok"),
        "publications_documents": publications,
        "transferts": res[:limite],
        "note": ("Une ligne 'documents_pdf_envoyes' > 0 = des PDF (circulaires, factures, documents "
                 "a signer) ont ete publies dans l'espace Documents d'EcoleDirecte, SANS notification "
                 "aux familles. Le journal ne donne ni intitule ni destinataires : les lire dans "
                 "EcoleDirecte (ed_admin_documents_ecole). Fichier copie depuis le serveur : a jour "
                 "a la date indiquee."),
    }
