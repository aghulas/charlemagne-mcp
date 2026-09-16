"""
Prototype (pre-tool) : "solde d'un eleve" -> resout le(s) responsable(s) lies
a l'eleve via COM_LIENER, puis calcule le solde de chacun a partir de
FAC_COMPTA_FAMILLE (SUM(CF_DEBIT) - SUM(CF_CREDIT) sur tous les evenements
de facturation).

Ne pas supposer un seul responsable par eleve : un eleve peut etre lie a
plusieurs responsables (ex. parents separes), et en pratique un seul des
deux a des lignes de facturation - l'autre n'a alors aucun solde (ce n'est
pas une erreur).

Usage:
    venv\\Scripts\\python.exe scripts\\query_solde_famille.py <IDELEVE> [--db data\\administration_consolidee.db]
"""

import argparse
import sqlite3


def solde_eleve(conn: sqlite3.Connection, id_eleve: str) -> list[dict]:
    cur = conn.cursor()

    eleve = cur.execute(
        'SELECT IDELEVE, EL_NOM1, EL_PRENOM1 FROM COM_ELEVES WHERE IDELEVE = ?',
        (id_eleve,),
    ).fetchone()
    if eleve is None:
        raise ValueError(f"Aucun eleve avec IDELEVE={id_eleve!r}")

    responsables = cur.execute(
        '''
        SELECT r.IDRESPONSABLE, r.RE_NOM1, r.RE_PRENOM1, r.RE_CODE_COMPTABLE,
               l.LER_TYPE_RESP, l.LER_LIEN
        FROM COM_LIENER l
        JOIN COM_RESPONSABLES r ON r.IDRESPONSABLE = l.IDRESPONSABLE
        WHERE l.IDELEVE = ?
        ''',
        (id_eleve,),
    ).fetchall()

    results = []
    for id_resp, nom, prenom, code_comptable, type_resp, lien in responsables:
        row = cur.execute(
            '''
            SELECT SUM(CAST(CF_DEBIT AS REAL)) AS total_debit,
                   SUM(CAST(CF_CREDIT AS REAL)) AS total_credit,
                   COUNT(*) AS nb_evenements
            FROM FAC_COMPTA_FAMILLE
            WHERE IDRESPONSABLE = ?
            ''',
            (id_resp,),
        ).fetchone()
        total_debit, total_credit, nb = row
        results.append(
            {
                "eleve": f"{eleve[2]} {eleve[1]}",
                "id_responsable": id_resp,
                "responsable": f"{prenom} {nom}",
                "lien": lien,
                "code_comptable": code_comptable,
                "nb_evenements_facturation": nb,
                "total_debit": total_debit or 0.0,
                "total_credit": total_credit or 0.0,
                "solde": (total_debit or 0.0) - (total_credit or 0.0),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id_eleve")
    parser.add_argument("--db", default="data/administration_consolidee.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        results = solde_eleve(conn, args.id_eleve)
    except ValueError as exc:
        print(exc)
        return 1

    if not results:
        print(f"Eleve {args.id_eleve} : aucun responsable trouve dans COM_LIENER.")
        return 0

    for r in results:
        print(f"Eleve : {r['eleve']} (IDELEVE={args.id_eleve})")
        print(f"  Responsable ({r['lien']}) : {r['responsable']} "
              f"[IDRESPONSABLE={r['id_responsable']}, compte={r['code_comptable']}]")
        if r["nb_evenements_facturation"] == 0:
            print("    Aucune facturation enregistree pour ce responsable.")
        else:
            print(f"    {r['nb_evenements_facturation']} evenement(s) de facturation")
            print(f"    Total facture (debit)  : {r['total_debit']:.2f} EUR")
            print(f"    Total credite          : {r['total_credit']:.2f} EUR")
            print(f"    Solde (a payer)        : {r['solde']:.2f} EUR")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
