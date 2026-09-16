"""Tests pour tools/personnels.py - donnees synthetiques uniquement, jamais de
vraies donnees d'adultes (voir Phase 0 du plan : minimisation, pas de PII dans
le depot)."""

import sqlite3

import pytest

from tools.personnels import liste_personnels


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_PERSONNELS (
            IDPERSONNEL TEXT PRIMARY KEY, PE_NOM TEXT, PE_PRENOM TEXT,
            PE_PARTICULE TEXT, PE_TYPE TEXT, PE_DATE_SORTIE TEXT
        );

        -- Dupont : actif, sans particule
        INSERT INTO COM_PERSONNELS VALUES ('1', 'DUPONT', 'Marie', NULL, 'ENS', NULL);
        -- De La Tour : actif, avec particule
        INSERT INTO COM_PERSONNELS VALUES ('2', 'TOUR', 'Paul', 'DE LA', 'PER', '');
        -- Petit : sorti en cours d'annee
        INSERT INTO COM_PERSONNELS VALUES ('3', 'PETIT', 'Luc', NULL, 'ENS', '2026-01-10');
        """
    )
    yield conn
    conn.close()


def test_liste_personnels_par_defaut_exclut_les_sortis(conn):
    result = liste_personnels(conn)
    ids = {p["id_personnel"] for p in result}
    assert ids == {"1", "2"}


def test_liste_personnels_tous_inclut_les_sortis(conn):
    result = liste_personnels(conn, actifs_seulement=False)
    ids = {p["id_personnel"] for p in result}
    assert ids == {"1", "2", "3"}
    luc = next(p for p in result if p["id_personnel"] == "3")
    assert luc["actif"] is False


def test_liste_personnels_particule_exposee_separement(conn):
    result = liste_personnels(conn, actifs_seulement=False)
    paul = next(p for p in result if p["id_personnel"] == "2")
    assert paul["particule"] == "DE LA"
    assert paul["nom_prenom"] == "TOUR Paul"

    marie = next(p for p in result if p["id_personnel"] == "1")
    assert marie["particule"] is None
