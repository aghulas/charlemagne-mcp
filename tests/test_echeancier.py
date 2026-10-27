"""Echeancier effectif : echeance unique d'une facture en cours d'annee reetalee comme en comptabilite."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.echeancier import echeanciers_effectifs, reetaler  # noqa: E402

DATES = ["20260929", "20261027", "20261127", "20261227", "20270127",
         "20270227", "20270327", "20270427", "20270527", "20270627"]


def facture(mode, echeances):
    f = {"HF_MODE_REGLEMENT": mode}
    for k, (d, m) in enumerate(echeances, 1):
        f[f"HF_ECHE_DATE{k}"], f[f"HF_ECHE_PRIX{k}"] = d, str(m)
    return f


def test_reetaler_arrondi_a_l_euro_et_ajustement_final():
    r = reetaler(3642.7, DATES[1:])                      # cas reel : 3 642,70 sur 9 echeances
    assert [m for _, m in r[:-1]] == [405.0] * 8 and r[-1] == ("20270627", 402.7)
    assert round(sum(m for _, m in r), 2) == 3642.7
    assert [m for _, m in reetaler(1872.1, DATES[1:])][:2] == [208.0, 208.0]   # 208,01 -> 208
    assert reetaler(5760, DATES[1:])[0][1] == 640.0


def test_echeance_unique_en_prelevement_reetalee():
    initiale = facture("Prélèvement", [(d, 403) for d in DATES])
    complement = facture("Prélèvement", [("20261027", 3642.7)])
    eff = echeanciers_effectifs([initiale, complement])
    assert eff[0]["reetale"] is False and len(eff[0]["echeances"]) == 10
    assert eff[1]["reetale"] is True and [d for d, _ in eff[1]["echeances"]] == DATES[1:]


def test_cas_non_reetales():
    initiale = facture("Prélèvement", [(d, 403) for d in DATES])
    # facture a plusieurs echeances : prise telle quelle
    reechelonnee = facture("Prélèvement", [(d, 450) for d in DATES[1:]])
    assert echeanciers_effectifs([initiale, reechelonnee])[1]["echeances"][0] == ("20261027", 450.0)
    # cheque : echeance unique annuelle normale
    cheque = facture("Chèque", [("20260915", 2000)])
    assert echeanciers_effectifs([cheque, facture("Chèque", [("20261016", 30)])])[1]["echeances"] == [("20261016", 30.0)]
    # derniere echeance de l'annee : plus rien a repartir
    tardive = facture("Prélèvement", [("20270627", 500)])
    assert echeanciers_effectifs([initiale, tardive])[1] == {"echeances": [("20270627", 500.0)], "reetale": False}
    # facture sans echeance (solde nul) : l'echeancier precedent reste en place
    vide = facture("Prélèvement", [])
    assert echeanciers_effectifs([initiale, vide])[1]["echeances"] == echeanciers_effectifs([initiale])[0]["echeances"]


def test_reetalements_en_chaine():
    initiale = facture("Prélèvement", [(d, 100) for d in DATES])
    c1 = facture("Prélèvement", [("20261027", 900)])     # reetale sur 9 dates
    c2 = facture("Prélèvement", [("20261127", 880)])     # puis sur les 8 suivantes
    eff = echeanciers_effectifs([initiale, c1, c2])
    assert eff[2]["reetale"] and [d for d, _ in eff[2]["echeances"]] == DATES[2:]
    assert eff[2]["echeances"][0][1] == 110.0
