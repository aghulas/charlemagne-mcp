"""Tests pour tools/texte.py et tools/observations.py - donnees synthetiques uniquement."""

import sqlite3

import pytest

from tools.observations import observations
from tools.texte import rtf_en_texte

RTF = r"{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}{\colortbl;\red0\green0\blue0;}\f0\fs20 \'e9tude L J\par 2026-10-06 : + jeudi (mail)\par}"


def test_rtf_en_texte():
    assert rtf_en_texte(RTF) == "étude L J\n2026-10-06 : + jeudi (mail)"
    assert rtf_en_texte(r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0 \par }") == ""
    assert rtf_en_texte("  texte simple  ") == "texte simple"
    assert rtf_en_texte(None) == ""
    assert rtf_en_texte(r"{\rtf1\uc1 caf\u233?}") == "café"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT,
            EL_OBSERVATION TEXT, EL_REPASMIDI1 TEXT, EL_REPASMIDI2 TEXT, EL_REPASMIDI3 TEXT, EL_REPASMIDI4 TEXT,
            EL_REPASMIDI5 TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_OBSERVATION TEXT,
            RE_OBSERVATION_FACTU TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT);
        CREATE TABLE PA_SUIVI_CONSOMMATEUR (SI_CODE TEXT, TYPE_PASSANT TEXT, IDPASSANT TEXT, JOUR1 TEXT, JOUR2 TEXT,
            JOUR3 TEXT, JOUR4 TEXT, JOUR5 TEXT);
        INSERT INTO COM_CLASSES VALUES ('5', 'CM1 A'), ('6', 'CP B');
        INSERT INTO COM_ELEVES VALUES ('1', 'TEST', 'Alice', '5', '', ?, '1', '1', '0', '1', '1');
    """.replace("?", "'" + RTF.replace("'", "''") + "'"))
    c.executescript("""
        INSERT INTO COM_ELEVES VALUES ('2', 'AUTRE', 'Bob', '6', '', '{\\rtf1 \\par }', '0', '0', '0', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('3', 'SORTI', 'Zoe', '6', '20260930', 'Parti', '0', '0', '0', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('4', 'PARENT', 'Leo', '6', '', '', '0', '0', '0', '0', '0');
        INSERT INTO COM_RESPONSABLES VALUES ('10', 'TEST', 'Paul', '', ''), ('11', 'PARENT', 'Eve', 'Garde alternée', 'Payeur : père');
        INSERT INTO COM_LIENER VALUES ('10', '1'), ('11', '4');
        INSERT INTO PA_SUIVI_CONSOMMATEUR VALUES ('ETUDE', 'ELEVE', '1', '1', '0', '0', '1', '0'), ('-1', 'ELEVE', '2', '0', '0', '0', '0', '0');
    """)
    return c


def test_observations_par_defaut(conn):
    r = observations(conn)
    assert [e["eleve"] for e in r["eleves"]] == ["TEST Alice", "PARENT Leo"]
    alice = r["eleves"][0]
    assert alice["observation"].startswith("étude L J")
    assert alice["activites"] == {"ETUDE": ["lundi", "jeudi"]}
    assert alice["jours_cantine"] == ["lundi", "mardi", "jeudi", "vendredi"]
    leo = r["eleves"][1]
    assert leo["observation"] is None
    assert leo["observations_responsables"][0]["observation_facturation"] == "Payeur : père"


def test_observations_filtres(conn):
    assert [e["eleve"] for e in observations(conn, recherche="ETUDE")["eleves"]] == ["TEST Alice"]
    assert [e["eleve"] for e in observations(conn, recherche="alternee")["eleves"]] == ["PARENT Leo"]
    assert observations(conn, classe="cm1")["nombre"] == 1
    assert "SORTI Zoe" in [e["eleve"] for e in observations(conn, inclure_sortis=True)["eleves"]]
    assert observations(conn, avec_vides=True)["nombre"] == 3


def test_lire_suivi():
    from tools.observations import lire_suivi
    r = lire_suivi("v1 S=LJ@260901 M=occ@260413 C=LMJV")
    assert r["S"] == {"prestation": "etude / garderie du soir", "valeur": "LJ", "jours": ["lundi", "jeudi"],
                      "depuis": "2026-09-01"}
    assert r["M"]["valeur"] == "occ" and r["M"]["jours"] is None and r["M"]["depuis"] == "2026-04-13"
    assert r["C"]["depuis"] is None
    assert lire_suivi("v1 S=LJ@2609 X") == {"illisible": ["S=LJ@2609", "X"]}
    assert lire_suivi("texte libre") == {"illisible": ["texte", "libre"]}
    assert lire_suivi(None) == {}


def test_champs_claude_et_journal(conn):
    conn.executescript("""
        CREATE TABLE ADM_ICE (ID_ICE TEXT, ICE_LIBELLE TEXT);
        CREATE TABLE ADM_ICE_SAISIE (ID_ICE TEXT, IDELEVE TEXT, ICES_SAISIE_TEXTE TEXT, ICES_SAISIE_NBRE TEXT);
        INSERT INTO ADM_ICE VALUES ('22', 'Suivi prestations (Claude)'), ('23', 'A faire (Claude)'), ('5', 'PAI');
        INSERT INTO ADM_ICE_SAISIE VALUES ('22', '2', 'v1 S=LJ@261006', NULL), ('23', '2', '#2 S=LJ cocher soir', NULL),
                                          ('23', '4', 'OK #1 verifie 12/10/26', NULL), ('5', '1', 'oui', NULL);
        UPDATE COM_ELEVES SET EL_OBSERVATION = 'note libre
[C] #1 S=LJ cocher soir - fait 12/10/26 AC' WHERE IDELEVE = '4';
    """)
    r = observations(conn)
    par = {e["eleve"]: e for e in r["eleves"]}
    assert par["AUTRE Bob"]["suivi_decode"]["S"]["jours"] == ["lundi", "jeudi"]
    assert par["AUTRE Bob"]["a_faire"] == "#2 S=LJ cocher soir"
    assert par["PARENT Leo"]["journal"] == ["[C] #1 S=LJ cocher soir - fait 12/10/26 AC"]
    assert par["TEST Alice"]["suivi_prestations"] is None
    assert [e["eleve"] for e in observations(conn, a_faire_seulement=True)["eleves"]] == ["AUTRE Bob"]


def test_journal_tolerant():
    from tools.observations import journal_claude
    obs = "L J\n08/10/26 : S=LJ cocher soir lun+jeu, facturer ETUDE2J (mail 08/09)\n8/10/2026 S=LJ cocher soir\n12/10 rappel parent\n[C] #1 S=LJ - fait"
    assert journal_claude(obs) == ["08/10/26 : S=LJ cocher soir lun+jeu, facturer ETUDE2J (mail 08/09)",
                                   "8/10/2026 S=LJ cocher soir", "[C] #1 S=LJ - fait"]


def test_champ_a_facturer(conn):
    conn.executescript("""
        CREATE TABLE ADM_ICE (ID_ICE TEXT, ICE_LIBELLE TEXT);
        CREATE TABLE ADM_ICE_SAISIE (ID_ICE TEXT, IDELEVE TEXT, ICES_SAISIE_TEXTE TEXT, ICES_SAISIE_NBRE TEXT);
        INSERT INTO ADM_ICE VALUES ('23', 'A faire'), ('24', 'A facturer');
        INSERT INTO ADM_ICE_SAISIE VALUES ('23', '2', 'OK #2 verifie 09/10/26', NULL),
                                          ('24', '2', '#F2 ETUDE2J 1x370€ forfait soir L+J', NULL),
                                          ('24', '1', 'OK #F1 facture 273 du 15/10/26', NULL);
    """)
    r = {e["eleve"]: e for e in observations(conn)["eleves"]}
    assert r["AUTRE Bob"]["a_facturer"].startswith("#F2") and r["AUTRE Bob"]["a_faire"].startswith("OK")
    assert [e["eleve"] for e in observations(conn, a_facturer_seulement=True)["eleves"]] == ["AUTRE Bob"]
    assert observations(conn, a_faire_seulement=True)["nombre"] == 0
    assert [e["eleve"] for e in observations(conn, recherche="etude2j")["eleves"]] == ["AUTRE Bob"]
