"""Apercu ponctuel de quelques lignes (lecture seule) pour valider le format des donnees."""
import pypyodbc

conn = pypyodbc.connect("DSN=Charlemagne Compta", timeout=5)
cur = conn.cursor()

print("--- TAB_PLAN_COMPTABLE (comptes commencant par 411, familles) ---")
cur.execute("SELECT COMPTE, LIBELLE, TYPE_COMPTE, NOM FROM TAB_PLAN_COMPTABLE WHERE COMPTE LIKE '411%'")
for i, row in enumerate(cur.fetchall()):
    print(" ", tuple(row))
    if i >= 9:
        break

print("\n--- ECRITURE (echantillon sur un compte 411) ---")
cur.execute("SELECT TOP 10 COMPTE, DATE_ECRIT, LIB_ECRIT, DEBIT, CREDIT, LETTRAGE, CODE_JOURNAL FROM ECRITURE WHERE COMPTE LIKE '411%'")
for row in cur.fetchall():
    print(" ", tuple(row))

conn.close()
