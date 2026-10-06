"""Journal des transferts vers EcoleDirecte - donnees fictives, sans reseau."""

import pytest

from tools import journal_ecoledirecte as je

JOURNAL = """
-DEBUT EXPORT ECOLE DIRECTE (14.0.0.0)\t: le 02/10/2026 à 15h35m29s par (POSTE-B) 
Mode\t        \t\t\t: Manuel - httpsV3 
Module\t        \t\t\t: Outils
ERREUR\t\t\t\t\t: EcoleDirecte - Erreur http 0 : Erreur de connexion  Type erreur : http Code erreur : 1
-FIN EXPORT ECOLE DIRECTE\t\t: le 02/10/2026 à 15h35m40s

-DEBUT EXPORT ECOLE DIRECTE (14.0.0.0)\t: le 01/10/2026 à 19h25m12s par (SERVEUR-A) 
Mode\t        \t\t\t: Automatique - httpsV3 
Module\t        \t\t\t: Outils
Réplication Administratif  \t\t: Cycle normal
Réplication Vie Scolaire   \t\t: Cycle normal
Photos des élèves\t\t\t: Sans - Dernier envoi le 24/09/2026
Documents pdf envoyés\t\t\t: 2
-FIN EXPORT ECOLE DIRECTE\t\t: le 01/10/2026 à 19h26m40s

-DEBUT EXPORT ECOLE DIRECTE (14.0.0.0)\t: le 30/09/2026 à 19h25m00s par (SERVEUR-A) 
Mode\t        \t\t\t: Automatique - httpsV3 
Documents pdf envoyés\t\t\t: 0
-FIN EXPORT ECOLE DIRECTE\t\t: le 30/09/2026 à 19h26m00s

-DEBUT EXPORT ECOLE DIRECTE (14.0.0.0)\t: le 29/09/2026 à 14h29m42s par (POSTE-B) 
ABANDON\t\t\t\t\t: EcoleDirecte  - Intégration en cours du fichier TO_EDVS.zip.cry
"""


def test_parse_blocs():
    t = je.parser_journal(JOURNAL)
    assert [x["debut"] for x in t] == ["2026-10-02 15:35:29", "2026-10-01 19:25:12",
                                       "2026-09-30 19:25:00", "2026-09-29 14:29:42"]
    ok = t[1]
    assert ok["statut"] == "ok" and ok["documents_pdf_envoyes"] == 2
    assert ok["replications"] == {"Administratif": "Cycle normal", "Vie Scolaire": "Cycle normal"}
    assert ok["poste"] == "SERVEUR-A" and ok["mode"].startswith("Automatique")
    assert ok["fin"] == "2026-10-01 19:26:40"


def test_erreur_et_abandon():
    t = je.parser_journal(JOURNAL)
    assert t[0]["statut"] == "erreur" and "Type erreur" not in t[0]["erreurs"][0]
    assert t[3]["statut"] == "abandon" and "TO_EDVS" in t[3]["abandon"]


def test_filtres_et_publications(tmp_path, monkeypatch):
    f = tmp_path / "journal.txt"
    f.write_bytes(JOURNAL.encode("cp1252"))  # le fichier serveur est en ANSI
    monkeypatch.setenv("CHARLEMAGNE_JOURNAL_ED", str(f))
    r = je.journal_transferts()
    assert r["nb_transferts"] == 4 and r["nb_en_erreur"] == 2
    assert r["publications_documents"] == [{"date": "2026-10-01 19:25:12", "documents_pdf_envoyes": 2,
                                            "mode": "Automatique - httpsV3", "poste": "SERVEUR-A"}]
    r = je.journal_transferts(avec_documents_seulement=True)
    assert [t["debut"] for t in r["transferts"]] == ["2026-10-01 19:25:12"]
    r = je.journal_transferts(depuis="2026-09-30", jusqu_a="2026-10-01")
    assert r["nb_transferts"] == 2


def test_sans_chemin(monkeypatch):
    monkeypatch.delenv("CHARLEMAGNE_JOURNAL_ED", raising=False)
    with pytest.raises(ValueError):
        je.journal_transferts()
