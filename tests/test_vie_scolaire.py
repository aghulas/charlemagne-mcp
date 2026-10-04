"""Tests pour tools/vie_scolaire.py - donnees synthetiques uniquement."""

import sqlite3

import pytest

from tools.vie_scolaire import appels_enseignants, emploi_du_temps_classe, horaires_classe


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_CODE TEXT, CL_LIBELLE TEXT);
        INSERT INTO COM_CLASSES VALUES ('7', 'CM2A', 'CM2 A'), ('20', 'PS', 'TPSPS');
        CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT, PE_NOM TEXT, PE_PRENOM TEXT);
        INSERT INTO COM_PERSONNELS VALUES ('15', 'DUPONT', 'Anne'), ('42', 'SMITH', 'Jo');
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT);
        INSERT INTO COM_ELEVES VALUES ('100', 'MARTIN', 'Leo', '7'), ('101', 'PETIT', 'Lou', '7');
        CREATE TABLE TAB_MATIERE (MA_CODE_GESTION TEXT, MA_LIBELLE TEXT);
        INSERT INTO TAB_MATIERE VALUES ('FRANC', 'Français'), ('ARTS', 'Arts'), ('0302', 'ANGLAIS');
        CREATE TABLE VS_SALLES (IDSALLE TEXT, SA_CODE TEXT);
        INSERT INTO VS_SALLES VALUES ('11', 'A23');
        CREATE TABLE VS_HORAIRE (IDVS_HORAIRE TEXT, IDETABLISSEMENT TEXT, HO_DEBUT TEXT, HO_FIN TEXT, HO_TYPE TEXT);
        INSERT INTO VS_HORAIRE VALUES ('1', '1', '0825', '1140', 'cours'), ('2', '1', '1330', '1630', 'cours');
        CREATE TABLE VS_HORAIRE_CLASSE (IDHORAIRE_CLASSE TEXT, HO_DEBUT TEXT, HO_FIN TEXT, HO_TYPE TEXT, IDCLASSE TEXT);
        INSERT INTO VS_HORAIRE_CLASSE VALUES ('1', '0825', '1015', 'cours', '7'), ('2', '1015', '1030', 'récréation', '7');
        CREATE TABLE VS_EDT_TYPE_ENTETE (IDENTETE TEXT, LIBELLE TEXT, DESCRIPTION TEXT);
        INSERT INTO VS_EDT_TYPE_ENTETE VALUES ('4', 'Import EDT', 'ancien'), ('5', 'Import EDT', 'Import EDT du 04/10/2026');
        CREATE TABLE VS_EDT_TYPE_COURS (IDCOURS TEXT, IDENTETE TEXT, IDCLASSE TEXT, CODE_MATIERE TEXT,
            JOUR TEXT, HEURE_DEBUT TEXT, HEURE_FIN TEXT, SEMAINE TEXT);
        INSERT INTO VS_EDT_TYPE_COURS VALUES
            ('1', '4', '7', 'FRANC', '1', '0825', '0900', ''),
            ('2', '5', '7', 'FRANC', '1', '0825', '0900', 'A'),
            ('3', '5', '7', 'ARTS', '1', '0825', '0900', 'B'),
            ('4', '5', '7', '0302', '1', '1415', '1500', ''),
            ('5', '5', '7', '', '2', '0825', '0900', '');
        CREATE TABLE VS_EDT_TYPE_PROF (IDCOURS TEXT, IDPERSONNEL TEXT);
        INSERT INTO VS_EDT_TYPE_PROF VALUES ('2', '15'), ('3', '15'), ('4', '42');
        CREATE TABLE VS_EDT_TYPE_SALLE (IDCOURS TEXT, IDSALLE TEXT);
        INSERT INTO VS_EDT_TYPE_SALLE VALUES ('2', '11'), ('3', '11'), ('4', '11');
        CREATE TABLE VS_EDT_COURS (IDCOURS TEXT, IDCLASSE TEXT, CODE_MATIERE TEXT, DATE TEXT,
            HEURE_DEBUT TEXT, HEURE_FIN TEXT, ANNULE TEXT, MODIFIE TEXT);
        INSERT INTO VS_EDT_COURS VALUES
            ('100', '7', 'FRANC', '20261005', '0825', '0900', '0', '0'),
            ('101', '7', '0302', '20261005', '1415', '1500', '0', '0'),
            ('102', '7', 'ARTS', '20261012', '0825', '0900', '0', '0');
        CREATE TABLE VS_EDT_PROF (IDCOURSPROF TEXT, IDCOURS TEXT, IDPERSONNEL TEXT);
        INSERT INTO VS_EDT_PROF VALUES ('1', '100', '15'), ('2', '101', '42');
        CREATE TABLE VS_EDT_SALLE (IDCOURSSALLE TEXT, IDCOURS TEXT, IDSALLE TEXT);
        INSERT INTO VS_EDT_SALLE VALUES ('1', '100', '11');
        CREATE TABLE VS_EDT_ALTERNANCES (IDALTERNANCE TEXT, SE_DEBUT TEXT, SE_ALTERNANCE TEXT);
        INSERT INTO VS_EDT_ALTERNANCES VALUES ('1', '20261005', 'A'), ('2', '20261012', 'B');
        CREATE TABLE VS_APPEL_PROF (_rowkey TEXT, IDPERSONNEL TEXT, IDCLASSE TEXT, AP_DATE TEXT,
            AP_NB_ABSENCE TEXT, AP_NB_RETARD TEXT, AP_EFFECTIF TEXT, AP_DATE_INTEGRATION TEXT,
            AP_TOUSPRESENTS TEXT, AP_COURS_DATE TEXT, AP_COURS_HEURE_DEBUT TEXT, AP_COURS_HEURE_FIN TEXT);
        INSERT INTO VS_APPEL_PROF VALUES
            ('a', '15', '7', '20261003160139000', '1', '0', '26', '20261003205333240', '0', '20260907', '0800', '1200'),
            ('b', '15', '7', '20261003160140000', '0', '0', '26', '20261003205333240', '1', '20260907', '1300', '1700'),
            ('c', '15', '7', '20261003160141000', '2', '0', '26', '20261003205333240', '0', '20260908', '0800', '1200');
        CREATE TABLE VS_ABSENCE_JOUR (IDVS_ABSENCE_JOUR TEXT, IDELEVE TEXT, AJ_DATE TEXT, AJ_DEMIJ_AM TEXT, AJ_DEMIJ_PM TEXT);
        INSERT INTO VS_ABSENCE_JOUR VALUES ('1', '100', '20260907', '1', '0'),
            ('2', '100', '20260908', '1', '1'), ('3', '101', '20260908', '1', '0');
        """
    )
    yield conn
    conn.close()


def test_horaires_de_la_classe_prioritaires(conn):
    h = horaires_classe(conn, "7")
    assert h["source"] == "classe"
    assert h["plages"][1] == {"debut": "10:15", "fin": "10:30", "type": "récréation"}
    assert horaires_classe(conn, "20")["source"] == "etablissement"


def test_semaine_type_la_plus_recente(conn):
    r = emploi_du_temps_classe(conn, "CM2 A")
    st = r["semaine_type"]
    assert st["id_entete"] == "5" and st["nb_cours"] == 4 and st["nb_cours_sans_matiere"] == 1
    lundi = st["jours"]["lundi"]
    assert [c["semaine"] for c in lundi[:2]] == ["A", "B"]
    assert lundi[2]["enseignants"] == ["SMITH Jo"] and lundi[2]["salles"] == ["A23"]


def test_classe_par_code_ou_identifiant(conn):
    assert emploi_du_temps_classe(conn, "cm2a")["classe"]["id_classe"] == "7"
    assert emploi_du_temps_classe(conn, "7")["classe"]["code"] == "CM2A"
    assert "error" in emploi_du_temps_classe(conn, "CM9Z")


def test_cours_generes_sur_une_semaine(conn):
    r = emploi_du_temps_classe(conn, "CM2A", "2026-10-05")
    g = r["cours_generes"]
    assert g["au"] == "2026-10-11" and g["nb"] == 2
    assert g["semaines_alternance"] == {"2026-10-05": "A"}
    assert g["cours"][1]["matiere_libelle"] == "ANGLAIS"


def test_sans_tables_edt():
    c = sqlite3.connect(":memory:")
    assert emploi_du_temps_classe(c, "CM2A") == {}
    assert appels_enseignants(c) == {}


def test_appels_par_demi_journee(conn):
    r = appels_enseignants(conn, "2026-09-07", "2026-09-30")
    assert r["nb_appels"] == 3
    assert r["par_classe"]["CM2A"] == {"demi_journees": 3, "demi_journees_absence": 3}
    assert r["appels"][0]["demi_journee"] == "matin" and r["appels"][1]["tous_presents"]
    assert "eleves_absents" not in r["appels"][0]


def test_appels_detail_absences(conn):
    r = appels_enseignants(conn, classe="CM2A", detail_absences=True)
    assert r["appels"][0]["eleves_absents"] == ["MARTIN Leo"]
    assert r["appels"][2]["eleves_absents"] == ["MARTIN Leo", "PETIT Lou"]
    assert appels_enseignants(conn, date_debut="2026-09-08")["nb_appels"] == 1
