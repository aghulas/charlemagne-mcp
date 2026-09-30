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


# ---- confidentialite : aucune donnee bancaire ni numero de securite sociale en clair ----
@pytest.mark.parametrize("champ", [
    "RE_IBAN", "RE_BIC", "RE_DOMICILIATION", "RE_TIRE", "RE_CODE_BANQUE", "RE_CODE_GUICHET",
    "RE_COMPTE_BANQUE", "RE_CLE_RIB", "PE_IBAN", "PE_TIRE", "EL_NUM_SECU", "PE_NUMSECU",
])
def test_champs_sensibles_masques(champ):
    from tools.comparaison import est_masque
    assert est_masque(champ)


@pytest.mark.parametrize("champ", ["RE_NOM1", "RE_MODE_REGLEMENT", "RE_TELDOMICILE", "EL_IDREGIME", "RE_PUBLIC"])
def test_champs_ordinaires_non_masques(champ):
    from tools.comparaison import est_masque
    assert not est_masque(champ)


def _base_banque(domiciliation, tire, iban):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, "
              "RE_DOMICILIATION TEXT, RE_TIRE TEXT, RE_IBAN TEXT)")
    c.execute("INSERT INTO COM_RESPONSABLES VALUES ('10', 'DURAND', 'Jean', ?, ?, ?)", (domiciliation, tire, iban))
    return c


def test_domiciliation_et_titulaire_jamais_en_clair():
    # cas reel du 30/09/2026 : banque et titulaire du compte sortaient en clair
    avant = _base_banque("", "", "FR7600000000000000000000001")
    apres = _base_banque("BANQUE FICTIVE AGENCE X", "M OU MME DURAND JEAN", "FR7600000000000000000000002")
    r = comparer_exports(apres, avant)
    champs = r["fiches"]["COM_RESPONSABLES"]["details"][0]["champs"]
    assert champs["RE_DOMICILIATION"] == {"avant": "vide", "apres": "renseigné"}
    assert champs["RE_TIRE"] == {"avant": "vide", "apres": "renseigné"}
    # IBAN change mais reste renseigne : le changement est signale sans la valeur
    assert champs["RE_IBAN"] == {"avant": "renseigné", "apres": "renseigné (modifié)"}
    texte = str(r)
    assert "FICTIVE" not in texte and "DURAND JEAN" not in texte and "FR76" not in texte
    avant.close(); apres.close()
