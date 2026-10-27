"""Echeancier effectif d'un responsable a partir de ses factures validees (FAC_HISTO_FAMILLE).

Constate sur l'echeance de prelevement d'octobre 2026 : une facture validee en cours d'annee (facture
complementaire, avoir, regularisation) peut porter dans la base Administratif une echeance UNIQUE
(solde restant + complement, a la prochaine date de prelevement), alors que la comptabilite preleve ce
montant reetale sur les echeances restantes de l'echeancier precedent : reajustement Charlemagne,
montant / nombre d'echeances restantes, dates conservees, arrondi a l'euro le plus proche, derniere
echeance d'ajustement. Les outils raisonnent sur cet echeancier effectif ; la facture elle-meme (et ce
qu'en voit la famille) garde l'echeance unique.

Regle appliquee : facture en Prelevement dont l'echeancier n'a qu'une date, alors que l'echeancier
effectif precedent a au moins deux dates a partir de celle-ci -> le montant est reparti sur ces dates.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def echeances_facture(f: dict) -> list[tuple[str, float]]:
    """Echeances (date AAAAMMJJ, montant) d'une ligne FAC_HISTO_FAMILLE, triees, sans les vides."""
    ech = [(f.get(f"HF_ECHE_DATE{k}"), _num(f.get(f"HF_ECHE_PRIX{k}"))) for k in range(1, 13)]
    return sorted(((d, m) for d, m in ech if d and m), key=lambda x: x[0])


def reetaler(total: float, dates: list[str]) -> list[tuple[str, float]]:
    """Repartit total sur dates : montants arrondis a l'euro, la derniere echeance porte l'ajustement."""
    n = len(dates)
    unite = float(Decimal(str(total / n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    res = [(d, unite) for d in dates[:-1]]
    res.append((dates[-1], round(total - unite * (n - 1), 2)))
    return res


def est_prelevement(mode: str | None) -> bool:
    return (mode or "").strip().lower().startswith("pr")


def echeanciers_effectifs(factures: list[dict]) -> list[dict]:
    """Pour chaque facture (lignes FAC_HISTO_FAMILLE d'un responsable, dans l'ordre des validations),
    l'echeancier effectif apres cette facture : {"echeances": [...], "reetale": bool}."""
    res, courant, courant_reetale = [], [], False
    for f in factures:
        e, reetale = echeances_facture(f), False
        if len(e) == 1 and courant and est_prelevement(f.get("HF_MODE_REGLEMENT")):
            restantes = [d for d, _ in courant if d >= e[0][0]]
            if len(restantes) >= 2:
                e, reetale = reetaler(e[0][1], restantes), True
        if e:                      # une facture sans echeance laisse l'echeancier precedent en place
            courant, courant_reetale = e, reetale
        res.append({"echeances": courant, "reetale": courant_reetale})
    return res
