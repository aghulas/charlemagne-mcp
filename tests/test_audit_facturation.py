"""Tests pour tools/audit_facturation.py - donnees synthetiques uniquement."""

import sqlite3

import pytest

from tools.audit_facturation import audit_facturation

REGLES = {
    "date_rentree": "20260901",
    "cantine": {"ligne": "CANT{n}J", "ligne_panier": "PAN{n}J", "regime_panier": "8", "regime_externe": "2",
                "tarifs": {"1": 100, "2": 200, "3": 300, "4": 400}, "tarifs_panier": {"1": 50, "2": 100, "3": 150, "4": 200}},
    "garderie": {"activite_matin": "MATIN", "activite_etude": "ETUDE", "ligne_matin": "GM", "tarif_matin": 50,
                 "ligne_etude": "ET{n}J", "tarifs_etude": {"1": 10, "2": 20, "3": 30, "4": 40}, "ligne_forfait": "FMS",
                 "jours_forfait": 4, "tarif_forfait": 80},
    "activites": [],
    "informations_complementaires": [{"code_ice": "BAV", "valeur": 1, "ligne": "BAVOIR", "tarif": 5}],
    "fratrie": {"prefixe_lignes": "FAMILLE", "montants": {"2": -10, "3": -30, "4": -40},
                "info_nb_exterieurs": "Ext.", "info_justificatif": "Justificatif Fraterie"},
    "codes_personnel": ["PERSO"],
    "apel": {"ligne": "APEL", "tarifs": {"Oui": 20, "Ext": 20, "Non": 0}, "valeur_exterieur": "Ext",
             "tarif_exterieur_justifie": 8, "info_justificatif": "Justificatif APEL", "info_foyer_separe": "Foyer S"},
    "echeances": {"mode_prelevement": "Prélèvement", "nb_prelevement": 10},
    "solde_a_signaler": 100,
}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    ech = ", ".join(f"GF_ECHE_PRIX{i} TEXT" for i in range(1, 13))
    c.executescript(f"""
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT,
            EL_IDREGIME TEXT, EL_REPASMIDI1 TEXT, EL_REPASMIDI2 TEXT, EL_REPASMIDI4 TEXT, EL_REPASMIDI5 TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_QUOTIENT2 TEXT,
            RE_MODE_REGLEMENT TEXT, RE_IBAN TEXT, IDFOYER TEXT);
        CREATE TABLE COM_FOYER (IDFOYER TEXT, COT_APEL TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT, LER_TYPE_RESP TEXT, LER_VERSQUI TEXT, LER_POURCENTAGE TEXT);
        CREATE TABLE ADM_ICR (ID_ICR TEXT, ICR_LIBELLE TEXT);
        CREATE TABLE ADM_ICR_SAISIE (ID_ICR TEXT, IDRESPONSABLE TEXT, ICRS_SAISIE_NBRE TEXT, ICRS_SAISIE_TEXTE TEXT);
        CREATE TABLE ADM_ICE (ID_ICE TEXT, ICE_CODE TEXT);
        CREATE TABLE ADM_ICE_SAISIE (ID_ICE TEXT, IDELEVE TEXT, ICES_SAISIE_NBRE TEXT, ICES_SAISIE_TEXTE TEXT);
        CREATE TABLE PA_SUIVI_CONSOMMATEUR (SI_CODE TEXT, IDPASSANT TEXT, JOUR1 TEXT, JOUR2 TEXT, JOUR4 TEXT, JOUR5 TEXT);
        CREATE TABLE FAC_GESTION_LIGNE (IDELEVE TEXT, IDRESPONSABLE TEXT, GL_CODE_LIGNE TEXT, GL_TOTAL TEXT,
            GL_REMISE_MT_FAMILLE TEXT, GL_REMISE_MT_ELEVE TEXT, GL_REMISE_CODE_FAMILLE TEXT, GL_REMISE_CODE_ELEVE TEXT);
        CREATE TABLE FAC_GESTION_FAMILLE (IDRESPONSABLE TEXT, GF_ORI_SOLDE TEXT, {ech});

        INSERT INTO COM_CLASSES VALUES ('C1', 'CP');
        -- Famille DURAND : 2 enfants, pere payeur et responsable principal
        INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice', 'C1', '', '1', '1', '1', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('2', 'DURAND', 'Bob', 'C1', '', '1', '1', '1', '1', '1');
        -- Famille MARTIN : 2 enfants, payee par la mere qui n'est PAS responsable principale
        INSERT INTO COM_ELEVES VALUES ('3', 'MARTIN', 'Chloe', 'C1', '', '2', '0', '0', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('4', 'MARTIN', 'David', 'C1', '', '2', '0', '0', '0', '0');
        INSERT INTO COM_RESPONSABLES VALUES ('10', 'DURAND', 'Jean', '', 'Prélèvement', 'FR76XXXX', 'F1');
        INSERT INTO COM_RESPONSABLES VALUES ('20', 'MARTIN', 'Paul', '', 'Chèque', '', 'F2');
        INSERT INTO COM_RESPONSABLES VALUES ('21', 'MARTIN', 'Julie', '', 'Chèque', '', 'F2');
        INSERT INTO COM_FOYER VALUES ('F1', 'Non');
        INSERT INTO COM_FOYER VALUES ('F2', 'Oui');
        INSERT INTO COM_LIENER VALUES ('10', '1', '1', '1', '100');
        INSERT INTO COM_LIENER VALUES ('10', '2', '1', '1', '100');
        INSERT INTO COM_LIENER VALUES ('20', '3', '1', '1', '0');
        INSERT INTO COM_LIENER VALUES ('21', '3', '2', '1', '100');
        INSERT INTO COM_LIENER VALUES ('20', '4', '1', '1', '0');
        INSERT INTO COM_LIENER VALUES ('21', '4', '2', '1', '100');
        INSERT INTO PA_SUIVI_CONSOMMATEUR VALUES ('ETUDE', '2', '1', '1', '1', '1');
        INSERT INTO PA_SUIVI_CONSOMMATEUR VALUES ('MATIN', '2', '1', '1', '1', '1');

        -- Alice : cantine 2 jours juste ; Bob : cantine 4 jours facturee 3 jours (erreur), forfait matin+soir juste
        INSERT INTO FAC_GESTION_LIGNE VALUES ('1', '10', 'CANT2J', '200', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('2', '10', 'CANT3J', '300', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('2', '10', 'FMS', '80', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('1', '10', 'FAMILLE2', '-10', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('2', '10', 'FAMILLE2', '-10', '0', '0', '', '');
        -- MARTIN : aucune fratrie (payeur non principal) ; APEL facturee 20 alors que « Oui » -> juste
        INSERT INTO FAC_GESTION_LIGNE VALUES ('3', '21', 'CONTRIB', '1000', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('4', '21', 'CONTRIB', '1000', '0', '0', '', '');
        INSERT INTO FAC_GESTION_LIGNE VALUES ('0', '21', 'APEL', '20', '0', '0', '', '');
        -- DURAND facture APEL alors que le foyer est « Non » (erreur)
        INSERT INTO FAC_GESTION_LIGNE VALUES ('0', '10', 'APEL', '20', '0', '0', '', '');
        INSERT INTO FAC_GESTION_FAMILLE VALUES ('10', '250', '100','100','100','100','100','100','0','0','100','100','100','100');
        INSERT INTO FAC_GESTION_FAMILLE VALUES ('21', '0', '0','0','0','0','0','0','0','0','2040','0','0','0');
    """)
    yield c
    c.close()


def test_detecte_les_ecarts(conn):
    r = audit_facturation(conn, REGLES)
    a = r["anomalies"]
    assert r["resume"]["eleves_factures"] == 4
    # cantine de Bob : 3 jours factures au lieu de 4
    lignes = {(x["eleve"].split(" (")[0], x["ligne"]) for x in a["ligne_incorrecte"]}
    assert ("DURAND Bob", "CANT3J") in lignes and ("DURAND Bob", "CANT4J") in lignes
    # le forfait matin+soir (etude 4 j + matin) n'est pas signale
    assert not any(x["ligne"] in ("FMS", "GM", "ET4J") for x in a["ligne_incorrecte"])
    # payeur MARTIN non responsable principal -> fratrie sous-comptee
    assert len(a["payeur_de_plusieurs_enfants_non_responsable_principal"]) == 2
    assert {x["eleve"].split(" (")[0] for x in a["reduction_fratrie_hors_regle"]} == {"MARTIN Chloe", "MARTIN David"}
    # APEL : DURAND « Non » facture 20 -> erreur ; MARTIN « Oui » a 20 -> correct
    assert [x["responsable"] for x in a["apel_incorrecte"]] == ["DURAND Jean"]
    # solde reporte de 250 > 100 et prelevement a 10 echeances -> seul le solde est signale
    assert [x["responsable"] for x in a["solde_reporte_important"]] == ["DURAND Jean"]
    assert "nombre_echeances_prelevement" not in a


def test_fratrie_justifiee_avec_exterieur(conn):
    conn.executescript("""
        INSERT INTO ADM_ICR VALUES ('1', 'Ext. Scolarisée Enseignement Catholique');
        INSERT INTO ADM_ICR VALUES ('2', 'Justificatif Fraterie');
        INSERT INTO ADM_ICR_SAISIE VALUES ('1', '10', '1', NULL);
    """)
    a = audit_facturation(conn, REGLES)["anomalies"]
    # exterieur saisi sans justificatif : non compte, signale
    assert [x["responsable"] for x in a["enfants_exterieurs_sans_justificatif"]] == ["DURAND Jean", "DURAND Jean"]
    conn.execute("INSERT INTO ADM_ICR_SAISIE VALUES ('2', '10', '1', NULL)")
    a = audit_facturation(conn, REGLES)["anomalies"]
    # justifie : 2 + 1 = 3 enfants -> -30 attendu au lieu de -10
    assert {x["attendu"] for x in a["reduction_fratrie_hors_regle"] if x["eleve"].startswith("DURAND")} == {-30}


def test_preparation_vide(conn):
    conn.execute("DELETE FROM FAC_GESTION_LIGNE")
    with pytest.raises(ValueError):
        audit_facturation(conn, REGLES)
