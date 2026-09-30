"""Tests pour tools/comparaison.py - donnees synthetiques uniquement."""

import sqlite3

import pytest

from tools.comparaison import comparer_exports

SCHEMA = """
    CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDREGIME TEXT);
    CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_IBAN TEXT, RE_MODE_REGLEMENT TEXT);
    CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT, LER_TYPE_RESP TEXT, LER_VERSQUI TEXT, LER_POURCENTAGE TEXT);
    CREATE TABLE FAC_FORMULE (ID_FORMULE TEXT, FORMULE TEXT);
    CREATE TABLE FAC_GESTION_LIGNE (IDELEVE TEXT, IDRESPONSABLE TEXT, GL_CODE_LIGNE TEXT, GL_TOTAL TEXT);
"""


def base(formule, iban, pct, lignes):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice', '1')")
    c.execute("INSERT INTO COM_RESPONSABLES VALUES ('10', 'DURAND', 'Jean', ?, 'Prélèvement')", (iban,))
    c.execute("INSERT INTO COM_LIENER VALUES ('10', '1', '1', '1', ?)", (pct,))
    c.execute("INSERT INTO FAC_FORMULE VALUES ('1', ?)", (formule,))
    for code, total in lignes:
        c.execute("INSERT INTO FAC_GESTION_LIGNE VALUES ('1', '10', ?, ?)", (code, total))
    return c


@pytest.fixture
def paire():
    avant = base("SI X ALORS =1", "", "50", [("CANT", "100")])
    apres = base("SI X ALORS =2", "FR7612345678901234567890123", "100", [("CANT", "100")])
    yield apres, avant
    apres.close(); avant.close()


def test_changements_detectes(paire):
    apres, avant = paire
    r = comparer_exports(apres, avant)
    assert r["parametrage_facturation"]["FAC_FORMULE"]["nb_ajouts"] == 1
    fiche = r["fiches"]["COM_RESPONSABLES"]["details"][0]
    # l'IBAN n'est jamais renvoye en clair
    assert fiche["champs"]["RE_IBAN"] == {"avant": "vide", "apres": "renseigné"}
    assert "FR76" not in str(r)
    assert r["liens_eleve_responsable"][0]["apres"]["pourcentage"] == "100"
    # formules modifiees mais preparation identique -> alerte
    assert r["facturation"]["FAC_GESTION_LIGNE"]["identique"] is True
    assert "alerte" in r


def test_aucun_changement():
    a = base("F", "", "100", [("CANT", "1")]); b = base("F", "", "100", [("CANT", "1")])
    r = comparer_exports(a, b)
    assert r["tables_modifiees"] == [] and r["parametrage_facturation"] == {} and r["fiches"] == {}
    assert "alerte" not in r
