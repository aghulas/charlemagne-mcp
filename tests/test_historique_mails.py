"""Tests pour tools/historique_mails.py - donnees synthetiques uniquement (aucune vraie famille)."""

import sqlite3

import pytest

from tools.historique_mails import destinataires, historique_mails, texte_brut


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT, PE_NOM TEXT, PE_PRENOM TEXT);
        CREATE TABLE COM_HISTORIQUE_MAILS (IDHISTO TEXT, SUJET TEXT, CORPS TEXT, DATE_PURGE TEXT, DATE_ENVOI TEXT,
            LISTE_MAILS TEXT, LISTE_CLIENTS TEXT, NOM_CAMPAGNE TEXT, NOM_MODULE TEXT, ID_CAMPAGNE TEXT,
            LISTE_TYPES TEXT, IDPERSONNEL TEXT);
        INSERT INTO COM_PERSONNELS VALUES ('18', 'SECRET', 'Anne');
        INSERT INTO COM_HISTORIQUE_MAILS VALUES
            ('2', 'Informations rentree', '<p>Bonjour,</p><p>La rentree a lieu&nbsp;le 1er.</p>', '', '20260828',
             'a.test@example.org;b.test@example.org;', 'TEST Alice(Perso);TEST Bob(Pro);', '0000_20260828165442062_1',
             'Administratif', '1', 'famille;famille;', '18'),
            ('9', 'Vos identifiants', '<div>Identifiant : #LOGIN<br>Mot de passe : #PASS</div>', '', '20261001',
             'c.autre@example.org', 'AUTRE Carla(Perso)', '0000_20261001214420692_4', 'Administratif', '4',
             'famille', '0'),
            ('10', 'Reunion enseignants', '<p>Ordre du jour</p>', '', '20261002',
             'prof@example.org', 'PROF Paul(Pro)', '', 'Administratif', '1', 'prof', '18');
    """)
    return c


def test_texte_brut():
    assert texte_brut("<p>Bonjour,</p><p>A&nbsp;demain &amp; merci</p>") == "Bonjour,\n\nA demain & merci"
    assert texte_brut(None) == ""


def test_destinataires_zippe_les_listes_et_ignore_le_vide():
    d = destinataires({"LISTE_CLIENTS": "TEST Alice(Perso);TEST Bob(Pro);",
                       "LISTE_MAILS": "a@example.org;b@example.org;", "LISTE_TYPES": "famille;prof;"})
    assert d == [{"nom": "TEST Alice", "adresse": "Perso", "mail": "a@example.org", "type": "famille"},
                 {"nom": "TEST Bob", "adresse": "Pro", "mail": "b@example.org", "type": "prof"}]


def test_liste_du_plus_recent_au_plus_ancien(conn):
    r = historique_mails(conn)
    assert [e["id_histo"] for e in r["envois"]] == ["10", "9", "2"]
    e2 = r["envois"][-1]
    assert e2["date"] == "2026-08-28" and e2["heure"] == "16:54:42"
    assert e2["utilisateur"] == "Anne SECRET" and e2["nb_destinataires"] == 2
    assert e2["types_destinataires"] == {"famille": 2}
    assert r["envois"][1]["utilisateur"] is None            # IDPERSONNEL 0
    assert r["envois"][0]["heure"] is None                 # campagne sans horodatage
    assert "statut de remise" in r["note"]


def test_filtres(conn):
    assert [e["id_histo"] for e in historique_mails(conn, recherche="#login")["envois"]] == ["9"]
    assert [e["id_histo"] for e in historique_mails(conn, recherche="RENTREE")["envois"]] == ["2"]
    assert [e["id_histo"] for e in historique_mails(conn, depuis="2026-09-01", jusqu_a="2026-10-01")["envois"]] == ["9"]
    r = historique_mails(conn, destinataire="bob")
    assert [e["id_histo"] for e in r["envois"]] == ["2"]
    assert r["envois"][0]["destinataires_correspondants"][0]["mail"] == "b.test@example.org"
    # chaine a cheval sur deux entrees de la liste : pas de faux positif
    assert historique_mails(conn, destinataire="org;b.test")["nb_envois"] == 0
    assert historique_mails(conn, limite=1)["tronque"] is True


def test_detail_et_erreurs(conn):
    d = historique_mails(conn, id_histo="9")
    assert d["objet"] == "Vos identifiants"
    assert d["corps"] == "Identifiant : #LOGIN\nMot de passe : #PASS"
    assert d["destinataires"][0]["nom"] == "AUTRE Carla"
    with pytest.raises(ValueError, match="IDHISTO"):
        historique_mails(conn, id_histo="999")
    with pytest.raises(ValueError, match="AAAA-MM-JJ"):
        historique_mails(conn, depuis="hier")


def test_table_absente():
    c = sqlite3.connect(":memory:")
    assert historique_mails(c)["nb_envois"] == 0
