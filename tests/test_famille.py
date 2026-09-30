"""Tests pour tools/famille.py - donnees synthetiques uniquement (aucune vraie famille)."""

import sqlite3

import pytest

from tools.famille import fiche_famille


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT,
            EL_IDREGIME TEXT, EL_REPASMIDI1 TEXT, EL_REPASMIDI2 TEXT, EL_REPASMIDI3 TEXT, EL_REPASMIDI4 TEXT,
            EL_REPASMIDI5 TEXT, EL_REMISE_CODE1 TEXT, EL_REMISE_VALEUR1 TEXT, EL_REMISE_NATURE1 TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, IDFOYER TEXT,
            RE_MODE_REGLEMENT TEXT, RE_IBAN TEXT, RE_ENF_A_CHARGE TEXT, RE_QUOTIENT1 TEXT, RE_QUOTIENT2 TEXT,
            RE_COT_APEL TEXT);
        CREATE TABLE COM_FOYER (IDFOYER TEXT, NOM TEXT, COT_APEL TEXT, ID_RESP_FINANCIER TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT, LER_LIEN TEXT, LER_TYPE_RESP TEXT,
            LER_VERSQUI TEXT, LER_POURCENTAGE TEXT);
        CREATE TABLE FAC_REGIME (IDREGIME TEXT, RG_LIBELLE TEXT);
        CREATE TABLE ADM_ICR (ID_ICR TEXT, ICR_LIBELLE TEXT);
        CREATE TABLE ADM_ICR_SAISIE (ID_ICR TEXT, IDRESPONSABLE TEXT, ICRS_SAISIE_TEXTE TEXT, ICRS_SAISIE_NBRE TEXT);
        CREATE TABLE FAC_GESTION_LIGNE (IDELEVE TEXT, IDRESPONSABLE TEXT, GL_CODE_LIGNE TEXT, GL_LIBELLE_LIGNE TEXT,
            GL_QUANTITE TEXT, GL_PRIX TEXT, GL_NUMLIGNE TEXT, GL_APAYER_LIGNE TEXT, GL_REMISE_MT_ELEVE TEXT,
            GL_REMISE_MT_FAMILLE TEXT, GL_REMISE_MT_AUTO TEXT, GL_REGROUPE_AVEC TEXT);
        CREATE TABLE FAC_GESTION_FAMILLE (IDRESPONSABLE TEXT, GF_APAYER_FACTURE TEXT);
        CREATE TABLE FAC_HISTO_LIGNE (IDVALIDATION TEXT, IDELEVE TEXT, IDRESPONSABLE TEXT);

        INSERT INTO COM_CLASSES VALUES ('8', 'CM2 B');
        INSERT INTO FAC_REGIME VALUES ('1', 'Demi pensionnaire'), ('2', 'Externe libre');
        INSERT INTO COM_ELEVES VALUES ('10', 'TEST', 'Alice', '8', '', '1', '1', '1', '0', '1', '1', 'REMISE', '20', '%');
        INSERT INTO COM_ELEVES VALUES ('11', 'AUTRE', 'Bob', '8', '', '2', '0', '0', '0', '0', '0', '', '', '');
        INSERT INTO COM_RESPONSABLES VALUES ('100', 'TEST', 'Paul', '100', 'Prélèvement', 'FR76XXXX', '3', '', '', 'Oui');
        INSERT INTO COM_RESPONSABLES VALUES ('101', 'TEST', 'Marie', '100', 'Chèque', '', '3', '', '', 'Oui');
        INSERT INTO COM_RESPONSABLES VALUES ('200', 'AUTRE', 'Luc', '200', 'Chèque', '', '1', '', '', 'Oui');
        INSERT INTO COM_FOYER VALUES ('100', 'M. Mme TEST', 'Ext', '100'), ('200', 'M. AUTRE', 'Oui', '200');
        INSERT INTO COM_LIENER VALUES ('100', '10', 'PS', '1', '1', '100'), ('101', '10', 'MS', '2', '1', '0'),
                                      ('200', '11', 'PS', '1', '1', '100');
        INSERT INTO ADM_ICR VALUES ('1', 'Justificatif Fraterie');
        INSERT INTO ADM_ICR_SAISIE VALUES ('1', '100', NULL, '1');
        INSERT INTO FAC_GESTION_LIGNE VALUES
            ('10', '100', 'CONTRIBUTION', 'Contribution', '1', '1000', '1', '1000', '0', '0', '0', ''),
            ('10', '100', 'CONTRIB', 'Contribution des familles', '1', '900', '2', '900', '0', '0', '0', 'CONTRIBUTION'),
            ('10', '100', 'DDEC', 'DDEC', '1', '100', '3', '100', '0', '0', '0', 'CONTRIBUTION'),
            ('10', '100', 'FAMILLE3', 'Reduction fratrie', '1', '-200', '4', '-200', '0', '0', '0', ''),
            ('10', '100', 'CANT', 'Cantine', '1', '0', '5', '0', '0', '0', '0', ''),
            ('0', '100', 'APEL', 'Cotisation APEL', '1', '27', '6', '27', '0', '0', '0', ''),
            ('11', '200', 'CONTRIBUTION', 'Contribution', '1', '1000', '1', '1000', '0', '0', '0', '');
        INSERT INTO FAC_GESTION_FAMILLE VALUES ('100', '827'), ('200', '1000');
    """)
    return c


def test_fiche_depuis_eleve(conn):
    r = fiche_famille(conn, id_eleve="10")
    assert [f["id_foyer"] for f in r["foyers"]] == ["100"]
    assert r["foyers"][0]["cotisation_apel"] == "Ext"
    assert {x["id_responsable"] for x in r["responsables"]} == {"100", "101"}   # pas l'autre famille
    alice = r["enfants"][0]
    assert alice["regime"] == "Demi pensionnaire"
    assert alice["jours_cantine"] == ["lundi", "mardi", "jeudi", "vendredi"]
    assert alice["remises"][0]["valeur"] == "20"
    paul = next(x for x in r["responsables"] if x["id_responsable"] == "100")
    assert paul["informations_complementaires"] == {"Justificatif Fraterie": "1"}
    assert paul["liens"][0]["responsable_principal"] and paul["liens"][0]["pourcentage"] == 100


def test_iban_jamais_renvoye(conn):
    r = fiche_famille(conn, id_eleve="10")
    assert "FR76" not in str(r)
    assert {x["iban"] for x in r["responsables"]} == {"renseigne", "vide"}


def test_facturation_sans_double_compte_des_regroupements(conn):
    f = fiche_famille(conn, id_eleve="10")["facturation"]
    assert f["source"].startswith("preparation")
    codes = [l["code"] for l in f["lignes"]]
    assert "CANT" not in codes                                   # ligne a zero omise
    assert next(l for l in f["lignes"] if l["code"] == "DDEC")["detail_de"] == "CONTRIBUTION"
    assert f["total_par_responsable"] == {"TEST Paul": 827.0}    # 1000 - 200 + 27, sans CONTRIB/DDEC
    assert f["montant_facture_charlemagne"]["TEST Paul"] == 827.0


def test_fiche_depuis_foyer_et_erreurs(conn):
    assert fiche_famille(conn, id_foyer="200")["enfants"][0]["eleve"] == "AUTRE Bob"
    with pytest.raises(ValueError):
        fiche_famille(conn)
    with pytest.raises(ValueError, match="Aucun eleve"):
        fiche_famille(conn, id_eleve="999")
    with pytest.raises(ValueError, match="foyer"):
        fiche_famille(conn, id_foyer="999")
