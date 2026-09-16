"""Tests pour tools/facturation.py - donnees synthetiques uniquement, jamais de vraies
donnees d'eleves (voir Phase 0 du plan : minimisation, pas de PII dans le depot)."""

import sqlite3

import pytest

from tools.facturation import solde_eleve


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_ELEVES (IDELEVE TEXT PRIMARY KEY, EL_NOM1 TEXT, EL_PRENOM1 TEXT);
        CREATE TABLE COM_RESPONSABLES (
            IDRESPONSABLE TEXT PRIMARY KEY, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_CODE_COMPTABLE TEXT
        );
        CREATE TABLE COM_LIENER (
            IDRESPONSABLE TEXT, IDELEVE TEXT, LER_TYPE_RESP TEXT, LER_LIEN TEXT
        );
        CREATE TABLE FAC_COMPTA_FAMILLE (
            IDVALIDATION TEXT, IDRESPONSABLE TEXT, CF_DEBIT TEXT, CF_CREDIT TEXT
        );

        INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice');
        INSERT INTO COM_ELEVES VALUES ('2', 'MARTIN', 'Bob');

        INSERT INTO COM_RESPONSABLES VALUES ('10', 'DURAND', 'Jean', '4111DURAND');
        INSERT INTO COM_RESPONSABLES VALUES ('20', 'MARTIN', 'Paul', '4111MARTIN');
        INSERT INTO COM_RESPONSABLES VALUES ('21', 'MARTIN', 'Julie', '4111MARTIN1');

        INSERT INTO COM_LIENER VALUES ('10', '1', '1', 'PERE');
        INSERT INTO COM_LIENER VALUES ('20', '2', '1', 'PERE');
        INSERT INTO COM_LIENER VALUES ('21', '2', '2', 'MERE');

        -- Alice (via son pere, compte 10) : deux evenements de facturation
        INSERT INTO FAC_COMPTA_FAMILLE VALUES ('1', '10', '100', '0');
        INSERT INTO FAC_COMPTA_FAMILLE VALUES ('2', '10', '50', '30');
        -- Bob : seul le pere (20) est facture, la mere (21) n'a rien
        INSERT INTO FAC_COMPTA_FAMILLE VALUES ('1', '20', '200', '0');
        """
    )
    yield conn
    conn.close()


def test_solde_eleve_avec_facturation(conn):
    result = solde_eleve(conn, "1")
    assert result["eleve"] == "Alice DURAND"
    assert len(result["responsables"]) == 1
    resp = result["responsables"][0]
    assert resp["responsable"] == "Jean DURAND"
    assert resp["nb_evenements_facturation"] == 2
    assert resp["total_debit"] == 150.0
    assert resp["total_credit"] == 30.0
    assert resp["solde"] == 120.0


def test_solde_eleve_plusieurs_responsables_un_seul_facture(conn):
    result = solde_eleve(conn, "2")
    assert len(result["responsables"]) == 2
    by_id = {r["id_responsable"]: r for r in result["responsables"]}

    assert by_id["20"]["nb_evenements_facturation"] == 1
    assert by_id["20"]["solde"] == 200.0

    assert by_id["21"]["nb_evenements_facturation"] == 0
    assert by_id["21"]["solde"] == 0.0


def test_solde_eleve_inconnu(conn):
    with pytest.raises(ValueError, match="Aucun eleve"):
        solde_eleve(conn, "999")
