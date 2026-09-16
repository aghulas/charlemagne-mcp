"""Tests pour tools/eleves.py - donnees synthetiques uniquement, jamais de vraies
donnees d'eleves (voir Phase 0 du plan : minimisation, pas de PII dans le depot)."""

import sqlite3

import pytest

from tools.eleves import liste_eleves


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_ELEVES (
            IDELEVE TEXT PRIMARY KEY, EL_NOM1 TEXT, EL_PRENOM1 TEXT,
            EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT
        );
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT PRIMARY KEY, CL_LIBELLE TEXT);

        INSERT INTO COM_CLASSES VALUES ('C1', 'CE1 A');
        INSERT INTO COM_CLASSES VALUES ('C2', 'CE1 B');

        -- Alice : active, CE1 A
        INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice', 'C1', NULL);
        -- Bob : actif, CE1 A
        INSERT INTO COM_ELEVES VALUES ('2', 'MARTIN', 'Bob', 'C1', '');
        -- Chloe : sortie en cours d'annee, CE1 B
        INSERT INTO COM_ELEVES VALUES ('3', 'PETIT', 'Chloe', 'C2', '2026-03-15');
        """
    )
    yield conn
    conn.close()


def test_liste_eleves_par_defaut_exclut_les_sortis(conn):
    result = liste_eleves(conn)
    ids = {e["id_eleve"] for e in result}
    assert ids == {"1", "2"}


def test_liste_eleves_tous_inclut_les_sortis(conn):
    result = liste_eleves(conn, actifs_seulement=False)
    ids = {e["id_eleve"] for e in result}
    assert ids == {"1", "2", "3"}
    chloe = next(e for e in result if e["id_eleve"] == "3")
    assert chloe["actif"] is False
    assert chloe["nom_prenom"] == "PETIT Chloe"


def test_liste_eleves_filtre_par_classe_insensible_a_la_casse(conn):
    result = liste_eleves(conn, classe="ce1 a")
    ids = {e["id_eleve"] for e in result}
    assert ids == {"1", "2"}


def test_liste_eleves_classe_inconnue_renvoie_vide(conn):
    result = liste_eleves(conn, classe="TERMINALE Z")
    assert result == []
