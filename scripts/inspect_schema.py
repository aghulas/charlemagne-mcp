"""
Script d'introspection ponctuel (Phase 1/2) - liste les colonnes de tables
candidates pour les cas d'usage "solde eleve / facture / impayes".
Usage: venv\\Scripts\\python.exe scripts\\inspect_schema.py TABLE1 TABLE2 ...
"""

import sys

import pypyodbc

DSN = "Charlemagne Compta"


def main() -> int:
    tables = sys.argv[1:]
    conn = pypyodbc.connect(f"DSN={DSN}", timeout=5)
    cursor = conn.cursor()

    for table in tables:
        print(f"\n=== {table} ===")
        try:
            cols = list(cursor.columns(table=table))
        except pypyodbc.Error as exc:
            print(f"  ERREUR: {exc}")
            continue
        if not cols:
            print("  (aucune colonne retournee - table absente ?)")
            continue
        for c in cols:
            # (table_name, column_name, data_type_code, type_name, column_size, ..., remarks, ...)
            name, dtype, size, remarks = c[1], c[3], c[4], c[9]
            print(f"  {name:<20} {dtype:<8} size={size:<5} {remarks}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
