"""Tests pour tools/responsables.py - donnees synthetiques uniquement, jamais de
vraies donnees de familles (voir Phase 0 du plan : minimisation, pas de PII)."""

import sqlite3

import pytest

from tools.responsables import responsables_eleves


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_ELEVES (
            IDELEVE TEXT PRIMARY KEY, EL_NOM1 TEXT, EL_PRENOM1 TEXT,
            EL_SEXE TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT
        );
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT PRIMARY KEY, CL_LIBELLE TEXT);
        CREATE TABLE COM_LIENER (
            IDRESPONSABLE TEXT, IDELEVE TEXT, LER_LIEN TEXT,
            LER_TYPE_RESP TEXT, LER_ORDRE TEXT
        );
        CREATE TABLE COM_RESPONSABLES (
            IDRESPONSABLE TEXT PRIMARY KEY,
            RE_CIVILITE1 TEXT, RE_PARTICULE1 TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT,
            RE_NOM_JFILLE1 TEXT, RE_EMAILPERSO1 TEXT, RE_EMAILPRO1 TEXT,
            RE_TELPORTABLE1 TEXT, RE_TELPRO1 TEXT,
            RE_CIVILITE2 TEXT, RE_PARTICULE2 TEXT, RE_NOM2 TEXT, RE_PRENOM2 TEXT,
            RE_NOM_JFILLE2 TEXT, RE_EMAILPERSO2 TEXT, RE_EMAILPRO2 TEXT,
            RE_TELPORTABLE2 TEXT, RE_TELPRO2 TEXT,
            RE_TELDOMICILE TEXT, RE_CODEPOSTAL TEXT, RE_VILLE TEXT,
            RE_IBAN TEXT
        );

        INSERT INTO COM_CLASSES VALUES ('C1', 'CE1 A');
        INSERT INTO COM_CLASSES VALUES ('C2', 'CE1 B');

        INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice', 'F', 'C1', NULL);
        INSERT INTO COM_ELEVES VALUES ('2', 'MARTIN', 'Bob', 'M', 'C2', '');
        -- Chloe : sortie en cours d'annee
        INSERT INTO COM_ELEVES VALUES ('3', 'PETIT', 'Chloe', 'F', 'C2', '2026-03-15');
        -- Dan : actif mais sans aucun lien responsable
        INSERT INTO COM_ELEVES VALUES ('4', 'ROUX', 'Dan', 'M', 'C1', NULL);

        -- Alice : deux responsables (pere + mere, fiches distinctes)
        INSERT INTO COM_LIENER VALUES ('R1', '1', 'PS', '1', '0');
        INSERT INTO COM_LIENER VALUES ('R2', '1', 'MS', '2', '1');
        -- Bob : une seule fiche portant deux personnes (blocs 1 et 2)
        INSERT INTO COM_LIENER VALUES ('R3', '2', 'MS', '1', '0');
        -- Chloe : rattachee a R1
        INSERT INTO COM_LIENER VALUES ('R1', '3', 'PS', '1', '0');

        INSERT INTO COM_RESPONSABLES VALUES ('R1', 'M.', NULL, 'DURAND', 'Paul',
            NULL, 'paul@example.org', NULL, '0600000001', NULL,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            '0100000000', '99999', 'TESTVILLE', 'FR76XXXX');
        INSERT INTO COM_RESPONSABLES VALUES ('R2', 'Mme', NULL, 'DURAND', 'Marie',
            'LEROY', 'marie@example.org', 'marie.pro@example.org', '0600000002', NULL,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            NULL, '99999', 'TESTVILLE', 'FR76YYYY');
        INSERT INTO COM_RESPONSABLES VALUES ('R3', 'Mme', NULL, 'MARTIN', 'Sophie',
            NULL, 'sophie@example.org', NULL, '0600000003', NULL,
            'M.', NULL, 'MARTIN', 'Luc', NULL, 'luc@example.org', NULL,
            '0600000004', NULL, NULL, '77210', 'AVON', 'FR76ZZZZ');
        """
    )
    yield conn
    conn.close()


def test_deux_responsables_pour_un_eleve(conn):
    result = responsables_eleves(conn, id_eleve="1")
    assert len(result) == 1
    fiche = result[0]
    assert fiche["nom_prenom"] == "DURAND Alice"
    assert fiche["classe"] == "CE1 A"
    liens = sorted(r["lien_libelle"] for r in fiche["responsables"])
    assert liens == ["Mère", "Père"]


def test_une_fiche_portant_deux_personnes(conn):
    fiche = responsables_eleves(conn, id_eleve="2")[0]
    prenoms = sorted(r["prenom"] for r in fiche["responsables"])
    assert prenoms == ["Luc", "Sophie"]
    # Les deux personnes partagent la meme fiche, donc le meme IDRESPONSABLE.
    assert {r["id_responsable"] for r in fiche["responsables"]} == {"R3"}
    assert {r["bloc"] for r in fiche["responsables"]} == {1, 2}


def test_aucune_coordonnee_bancaire_exposee(conn):
    fiche = responsables_eleves(conn, id_eleve="1")[0]
    for resp in fiche["responsables"]:
        serialise = " ".join(str(v) for v in resp.values())
        assert "FR76" not in serialise
        assert not any(cle.lower().startswith("iban") for cle in resp)


def test_filtre_par_classe_et_exclusion_des_sortis(conn):
    result = responsables_eleves(conn, classe="ce1 b")
    assert [f["id_eleve"] for f in result] == ["2"]
    tous = responsables_eleves(conn, classe="CE1 B", actifs_seulement=False)
    assert sorted(f["id_eleve"] for f in tous) == ["2", "3"]


def test_eleve_sans_lien_absent_du_resultat(conn):
    ids = {f["id_eleve"] for f in responsables_eleves(conn)}
    assert "4" not in ids
    assert ids == {"1", "2"}
