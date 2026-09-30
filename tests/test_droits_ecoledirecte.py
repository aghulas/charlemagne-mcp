"""Tests pour tools/personnels.droits_ecoledirecte - donnees synthetiques
uniquement (noms fictifs), jamais de vraies donnees d'adultes."""

import sqlite3

import pytest

from tools.personnels import droits_ecoledirecte


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT, PE_NOM TEXT, PE_PRENOM TEXT,
            PE_TYPE TEXT, PE_DATE_SORTIE TEXT, PE_AVECED TEXT);
        INSERT INTO COM_PERSONNELS VALUES ('1', 'ACCUEIL', 'Anne', 'personnel', '', '1');
        INSERT INTO COM_PERSONNELS VALUES ('2', 'CHEF', 'Bruno', 'prof_personnel', '', '1');
        INSERT INTO COM_PERSONNELS VALUES ('3', 'CLASSE', 'Chloe', 'prof', '', '0');
        INSERT INTO COM_PERSONNELS VALUES ('4', 'ANCIEN', 'Denis', 'personnel', '20200831', '1');

        CREATE TABLE TAB_FONCTIONS (IDFONCTION TEXT, LIBELLE TEXT);
        INSERT INTO TAB_FONCTIONS VALUES ('1', 'Secretariat'), ('2', 'Direction');
        CREATE TABLE ADM_FONCTION_PERSONNEL (IDFONCTION_PERSONNEL TEXT, IDPERSONNEL TEXT, IDFONCTION TEXT);
        INSERT INTO ADM_FONCTION_PERSONNEL VALUES ('1', '1', '1');

        CREATE TABLE COM_PERSONNELS_ED (IDPERSONNEL TEXT, PED_LIBRE1 TEXT, ID_PERSO_ED TEXT,
            PED_TYPE TEXT, PED_CLEF TEXT, PED_AUTORIS TEXT, PED_COMPLEMENT TEXT);
        INSERT INTO COM_PERSONNELS_ED VALUES ('1', '', '10', 'ETAB', '1', '1', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('1', '', '11', 'MODULE', 'MESSAGE', '1', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('1', '', '12', 'MODULE', 'APPEL', '0', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('1', '', '13', 'MODULE', 'XYZ', '1', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('2', '', '20', 'MODULE', 'MESSAGE', '0', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('2', '', '21', 'MODULE', 'ADMIN', '0', '');
        INSERT INTO COM_PERSONNELS_ED VALUES ('3', '', '30', 'ETAB', '1', '0', '');

        CREATE TABLE COM_PERSONNELS_PREFERENCE (ID_AUTO_PREF TEXT, IDPERSONNEL TEXT,
            PEP_TYPE TEXT, PEP_VALEUR TEXT, PEP_LIBRE TEXT);
        INSERT INTO COM_PERSONNELS_PREFERENCE VALUES ('1', '1', 'INT_MESSAGE_ED', '1', '');
        INSERT INTO COM_PERSONNELS_PREFERENCE VALUES ('2', '1', 'INT_COORDONNEES', '1', '');
        INSERT INTO COM_PERSONNELS_PREFERENCE VALUES ('3', '1', 'INT_DEMANDE_MODIF_EL', '0', '');
        INSERT INTO COM_PERSONNELS_PREFERENCE VALUES ('4', '2', 'INT_MESSAGE_ED', '0', '');
        INSERT INTO COM_PERSONNELS_PREFERENCE VALUES ('5', '1', 'AUTRE_PREF', '1', '');

        CREATE TABLE ADM_PROFIL (ID_UTILISATEUR TEXT, PR_TYPE TEXT, PR_VALEUR TEXT);
        INSERT INTO ADM_PROFIL VALUES ('1', 'EcoleD_LoginPass', 'O'), ('1', 'EmailsRecapTous', 'N');
        """
    )
    yield conn
    conn.close()


def _adulte(res, pid):
    return next(a for a in res["adultes"] if a["id_personnel"] == pid)


def test_personnel_bien_parametre(conn):
    res = droits_ecoledirecte(conn)
    a = _adulte(res, "1")
    assert a["utilisateur_ecoledirecte"] is True
    assert a["fonctions"] == ["Secretariat"]
    assert a["etablissements_coches"] == ["1"]
    assert a["fonctionnalites_autorisees"] == ["Messagerie", "XYZ"]  # code inconnu renvoye tel quel
    assert a["fonctionnalites_refusees"] == ["Feuille d'appel"]
    assert "Messages EcoleDirecte en attente" in a["notifications_actives"]
    assert "Demande de modifications élève" in a["notifications_inactives"]
    assert "Demande de sanction" in a["notifications_inactives"]  # absente = inactive
    assert a["points_attention"] == [
        "Notifiée des demandes de modification de coordonnées mais pas des "
        "demandes de modifications élève (activités, régime...)."
    ]


def test_personnel_mal_parametre_signale(conn):
    a = _adulte(droits_ecoledirecte(conn), "2")
    textes = " ".join(a["points_attention"])
    assert "sans établissement" in textes
    assert "Aucune fonctionnalité" in textes
    assert "Aucune fonction" in textes
    assert "notification des messages" in textes


def test_enseignant_resume_par_defaut(conn):
    a = _adulte(droits_ecoledirecte(conn), "3")
    assert "resume" in a and "fonctionnalites_refusees" not in a and "points_attention" not in a


def test_enseignant_detail_sur_demande(conn):
    for res in (droits_ecoledirecte(conn, detail_enseignants=True), droits_ecoledirecte(conn, id_personnel="3")):
        a = _adulte(res, "3")
        assert a["points_attention"] == [] and a["etablissements_coches"] == []


def test_sortis_exclus_par_defaut(conn):
    assert {a["id_personnel"] for a in droits_ecoledirecte(conn)["adultes"]} == {"1", "2", "3"}
    assert len(droits_ecoledirecte(conn, actifs_seulement=False)["adultes"]) == 4


def test_filtre_et_erreur(conn):
    assert droits_ecoledirecte(conn, id_personnel="1")["nb_adultes"] == 1
    with pytest.raises(ValueError):
        droits_ecoledirecte(conn, id_personnel="999")


def test_fonctions_et_profils(conn):
    res = droits_ecoledirecte(conn)
    assert res["fonctions_existantes"] == ["Secretariat", "Direction"]
    assert res["profils_utilisateurs_charlemagne"] == [
        {"id_utilisateur": "1", "options_actives": ["Visualisation des logins / mots de passe EcoleDirecte"]}
    ]


def test_tables_optionnelles_absentes():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT, PE_NOM TEXT, PE_PRENOM TEXT, PE_TYPE TEXT, PE_DATE_SORTIE TEXT);
           INSERT INTO COM_PERSONNELS VALUES ('1', 'X', 'Y', 'personnel', '');
           CREATE TABLE COM_PERSONNELS_ED (IDPERSONNEL TEXT, PED_TYPE TEXT, PED_CLEF TEXT, PED_AUTORIS TEXT);"""
    )
    res = droits_ecoledirecte(c)
    assert res["adultes"][0]["utilisateur_ecoledirecte"] is None
    assert res["profils_utilisateurs_charlemagne"] == []


def test_table_ed_absente():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT)")
    with pytest.raises(ValueError, match="COM_PERSONNELS_ED"):
        droits_ecoledirecte(c)
