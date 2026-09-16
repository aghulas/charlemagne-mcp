"""
Phase 1 - Validation de la connexion ODBC a la base HFSQL Charlemagne
(copie locale). Ne fait rien d'autre que se connecter et lister les tables
disponibles - aucune requete sur les donnees.

Note technique importante : le driver ODBC HFSQL (PC Soft, wd310hfo64.dll)
crashe (violation d'acces memoire) quand il est appele via `pyodbc` (le
wrapper C standard). Cause probable : incompatibilite entre la maniere dont
pyodbc appelle SQLDriverConnectW et ce driver particulier (un test via
.NET System.Data.Odbc fonctionne, ce qui confirme que le DSN/driver sont
corrects). Le wrapper pur Python `pypyodbc` (ctypes, sans extension C)
fonctionne correctement avec ce driver -> c'est celui utilise ici.
A garder en tete pour la suite du projet MCP (Phase 3) : soit continuer
avec pypyodbc, soit re-tester pyodbc plus tard si une mise a jour du
driver PC Soft resout le probleme.

Usage:
    venv\\Scripts\\python.exe test_connection.py [nom_du_dsn]

Par defaut, utilise le DSN "Charlemagne Compta" (ODBC Data Sources >
User DSN, deja configure sur cette machine). Peut etre surcharge via la
variable d'environnement CHARLEMAGNE_DSN ou un argument en ligne de
commande.
"""

import os
import sys

import pypyodbc

DEFAULT_DSN = "Charlemagne Compta"


def main() -> int:
    dsn = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHARLEMAGNE_DSN", DEFAULT_DSN)
    user = os.environ.get("CHARLEMAGNE_USER")
    password = os.environ.get("CHARLEMAGNE_PASSWORD")

    print("Drivers ODBC disponibles contenant 'HFSQL':")
    for driver in pypyodbc.drivers():
        if "HFSQL" in driver.upper():
            print(f"  - {driver}")

    print(f"\nDSN cible : {dsn}")

    conn_parts = [f"DSN={dsn}"]
    if user:
        conn_parts.append(f"UID={user}")
    if password:
        conn_parts.append(f"PWD={password}")
    conn_str = ";".join(conn_parts)

    print("Connexion en cours...")
    try:
        conn = pypyodbc.connect(conn_str, timeout=5)
    except pypyodbc.Error as exc:
        print(f"\nECHEC de connexion : {exc}")
        return 1

    print("Connexion etablie.\n")

    cursor = conn.cursor()
    # Colonnes retournees par .tables() : (catalog, schema, table_name, table_type, remarks)
    tables = sorted(row[2] for row in cursor.tables(tableType="TABLE"))

    print(f"{len(tables)} table(s) trouvee(s) :\n")
    for name in tables:
        print(f"  - {name}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
