"""Tests pour tools/suivi_facturation.py - donnees synthetiques uniquement."""

import sqlite3
from datetime import date

import pytest

from tools.regles_facturation import indice_mois, mois_restants
from tools.suivi_facturation import regularisations_a_preparer, suivi_echeanciers

REGLES = {
    "date_rentree": "20260901",
    "prorata": {"premier_mois": 9, "nb_mois": 10},
    "cantine": {"ligne": "CANT{n}J", "ligne_panier": "PAN{n}J", "regime_panier": "8", "regime_externe": "2",
                "tarifs": {"1": 100, "2": 200, "3": 300, "4": 400}, "tarifs_panier": {"1": 50, "2": 100, "3": 150, "4": 200}},
    "garderie": {"activite_matin": "MATIN", "activite_etude": "ETUDE", "ligne_matin": "GM", "tarif_matin": 50,
                 "ligne_etude": "ET{n}J", "tarifs_etude": {"1": 10, "2": 20, "3": 30, "4": 40}, "ligne_forfait": "FMS",
                 "jours_forfait": 4, "tarif_forfait": 80},
    "activites": [],
    "informations_complementaires": [],
    "lignes_regroupement_contribution": ["CONTRIB"],
    "fratrie": {"prefixe_lignes": "FAMILLE", "montants": {"2": -10, "3": -30, "4": -40},
                "info_nb_exterieurs": "Ext.", "info_justificatif": "Justificatif Fraterie"},
    "codes_personnel": ["PERSO"],
    "apel": {"ligne": "APEL", "tarifs": {"Oui": 20, "Ext": 20, "Non": 0}, "valeur_exterieur": "Ext",
             "tarif_exterieur_justifie": 8, "info_justificatif": "Justificatif APEL", "info_foyer_separe": "Foyer S"},
    "echeances": {"mode_prelevement": "Prélèvement", "nb_prelevement": 10},
    "pieces_justificatifs": [
        {"piece": "Certificat ext.", "info_responsable": "Justificatif Fraterie", "valeur": 1},
        {"piece": "Justif APEL", "info_responsable": "Justificatif APEL", "valeur": 1},
    ],
    "solde_a_signaler": 100,
}
AUJ = date(2026, 10, 5)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    ech = ", ".join(f"HF_ECHE_PRIX{i} TEXT, HF_ECHE_DATE{i} TEXT" for i in range(1, 13))
    c.executescript(f"""
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT, EL_DATE_ENTREE TEXT,
            EL_DATE_SORTIE TEXT, EL_IDREGIME TEXT, EL_REPASMIDI1 TEXT, EL_REPASMIDI2 TEXT, EL_REPASMIDI4 TEXT, EL_REPASMIDI5 TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_QUOTIENT2 TEXT,
            RE_MODE_REGLEMENT TEXT, RE_IBAN TEXT, IDFOYER TEXT);
        CREATE TABLE COM_FOYER (IDFOYER TEXT, COT_APEL TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT, LER_TYPE_RESP TEXT, LER_VERSQUI TEXT, LER_POURCENTAGE TEXT);
        CREATE TABLE ADM_ICR (ID_ICR TEXT, ICR_LIBELLE TEXT);
        CREATE TABLE ADM_ICR_SAISIE (ID_ICR TEXT, IDRESPONSABLE TEXT, ICRS_SAISIE_NBRE TEXT, ICRS_SAISIE_TEXTE TEXT);
        CREATE TABLE ADM_ICE (ID_ICE TEXT, ICE_CODE TEXT);
        CREATE TABLE ADM_ICE_SAISIE (ID_ICE TEXT, IDELEVE TEXT, ICES_SAISIE_NBRE TEXT, ICES_SAISIE_TEXTE TEXT);
        CREATE TABLE PA_SUIVI_CONSOMMATEUR (SI_CODE TEXT, IDPASSANT TEXT, JOUR1 TEXT, JOUR2 TEXT, JOUR4 TEXT, JOUR5 TEXT);
        CREATE TABLE FAC_LIGNE (LI_CODE TEXT, LI_LIBELLE TEXT);
        CREATE TABLE FAC_VALIDATION (IDVALIDATION TEXT, VA_TYPE_FACTURE TEXT, VA_NB_FACTURES TEXT, VA_NUMERO_DEBUT TEXT,
            VA_NUMERO_FIN TEXT, VA_DATE_HEURE TEXT);
        CREATE TABLE FAC_HISTO_LIGNE (IDVALIDATION TEXT, IDELEVE TEXT, IDRESPONSABLE TEXT, HL_CODE_LIGNE TEXT, HL_TOTAL TEXT,
            HL_QUANTITE TEXT, HL_PRIX TEXT, HL_LIBELLE_LIGNE TEXT, HL_REGROUPEMENT TEXT, HL_REMISE_MT_FAMILLE TEXT,
            HL_REMISE_MT_ELEVE TEXT);
        CREATE TABLE FAC_HISTO_FAMILLE (IDVALIDATION TEXT, IDRESPONSABLE TEXT, HF_DATE_FACTURE TEXT, HF_NUMERO_FACTURE TEXT,
            HF_APAYER_FACTURE TEXT, HF_ORI_SOLDE TEXT, HF_MODE_REGLEMENT TEXT, {ech});
        CREATE TABLE FAC_GESTION_HISTO (IDRESPONSABLE TEXT, IDELEVE TEXT, GH_CODE_LIGNE TEXT, GH_QTE TEXT, GH_LIBELLE TEXT, GH_PRIX TEXT);
        CREATE TABLE INS_PIECES_DOSSIER (IDPIECE_DOSSIER TEXT, LIBELLE TEXT);
        CREATE TABLE COM_LIEN_PIECE_LISTE (ID_LIEN_PIECE_LISTE TEXT, IDPIECE_DOSSIER TEXT);
        CREATE TABLE COM_LIEN_PIECE_PERSONNE (ID_LIEN_PIECE_PERSONNE TEXT, ID_PERSONNE TEXT);
        CREATE TABLE COM_PIECE_RECU (ID_LIEN_PIECE_PERSONNE TEXT, ID_LIEN_PIECE_LISTE TEXT, ETAT TEXT);

        INSERT INTO COM_CLASSES VALUES ('C1', 'CP');
        INSERT INTO FAC_LIGNE VALUES ('CANT2J', 'Cantine 2 jours'), ('CANT3J', 'Cantine 3 jours'), ('CONTRIB', 'Contribution'),
            ('APEL', 'Cotisation APEL'), ('ET3J', 'Etude 3 jours'), ('FAMILLE2', 'Fratrie 2');
        INSERT INTO FAC_VALIDATION VALUES ('1', 'Toutes', '3', '1', '3', 'Le 15/09/2026'), ('2', 'Manuelles', '1', '4', '4', 'Le 01/10/2026');
        -- A (1) : facture cantine 2 j, passe a 3 j ; B (2) : nouvel eleve entre le 03/10, cantine 1 j ;
        -- C (3) : sorti le 15/11 ; D (4) : complement etude 3 j facture plein le 01/10 (couvre l'annee)
        INSERT INTO COM_ELEVES VALUES ('1', 'A', 'a', 'C1', '20260901', '', '1', '1', '1', '1', '0');
        INSERT INTO COM_ELEVES VALUES ('2', 'B', 'b', 'C1', '20261003', '', '1', '1', '0', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('3', 'C', 'c', 'C1', '20260901', '20261115', '1', '1', '1', '0', '0');
        INSERT INTO COM_ELEVES VALUES ('4', 'D', 'd', 'C1', '20260901', '', '2', '0', '0', '0', '0');
        INSERT INTO COM_RESPONSABLES VALUES ('10', 'RA', 'x', '', 'Prélèvement', 'FR76', 'F1');
        INSERT INTO COM_RESPONSABLES VALUES ('20', 'RB', 'x', '', 'Prélèvement', '', 'F2');
        INSERT INTO COM_RESPONSABLES VALUES ('30', 'RC', 'x', '', 'Chèque', '', 'F3');
        INSERT INTO COM_RESPONSABLES VALUES ('40', 'RD', 'x', '', 'Prélèvement', 'FR76', 'F4');
        INSERT INTO COM_FOYER VALUES ('F1', 'Ext'), ('F2', 'Non'), ('F3', 'Non'), ('F4', 'Non');
        INSERT INTO COM_LIENER VALUES ('10', '1', '1', '1', '100'), ('20', '2', '1', '1', '100'),
            ('30', '3', '1', '1', '100'), ('40', '4', '1', '1', '100');
        INSERT INTO ADM_ICR VALUES ('1', 'Ext. Scolarisée'), ('2', 'Justificatif Fraterie'), ('3', 'Justificatif APEL');
        INSERT INTO ADM_ICR_SAISIE VALUES ('3', '10', '1', NULL);   -- RA : APEL ext justifiee -> 8 au lieu de 20
        INSERT INTO PA_SUIVI_CONSOMMATEUR VALUES ('ETUDE', '4', '1', '1', '1', '0');
        -- facturation initiale du 15/09
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '1', '10', 'CONTRIB', '1000', '1', '1000', 'Contribution', '0', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '1', '10', 'CONTRIBUTION', '1000', '1', '1000', 'Contribution', '1', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '1', '10', 'CANT2J', '200', '1', '200', 'Cantine 2 jours', '0', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '0', '10', 'APEL', '20', '1', '20', 'APEL', '0', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '3', '30', 'CONTRIB', '1000', '1', '1000', 'Contribution', '0', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '3', '30', 'CANT2J', '200', '1', '200', 'Cantine 2 jours', '0', '0', '0');
        INSERT INTO FAC_HISTO_LIGNE VALUES ('1', '4', '40', 'CONTRIB', '1000', '1', '1000', 'Contribution', '0', '0', '0');
        -- complementaire manuelle du 01/10 : D etude 3 j au tarif plein
        INSERT INTO FAC_HISTO_LIGNE VALUES ('2', '4', '40', 'ET3J', '30', '1', '30', 'Etude 3 jours complement', '0', '0', '0');
        INSERT INTO FAC_HISTO_FAMILLE VALUES ('1', '10', '20260915', '1', '1220', '0', 'Prélèvement',
            '122','20270127','122','20270227','122','20270327','122','20270427','122','20270527','122','20270627',
            '0','','0','','122','20260929','122','20261027','122','20261127','122','20261227');
        INSERT INTO FAC_HISTO_FAMILLE VALUES ('1', '30', '20260915', '2', '1200', '0', 'Chèque',
            '0','','0','','0','','0','','0','','0','','0','','0','','1200','20260915','0','','0','','0','');
        INSERT INTO FAC_HISTO_FAMILLE VALUES ('1', '40', '20260915', '3', '1000', '0', 'Prélèvement',
            '100','20270127','100','20270227','100','20270327','100','20270427','100','20270527','100','20270627',
            '0','','0','','100','20260929','100','20261027','100','20261127','100','20261227');
        INSERT INTO FAC_HISTO_FAMILLE VALUES ('2', '40', '20261001', '4', '30', '900', 'Prélèvement',
            '103','20270127','103','20270227','103','20270327','103','20270427','103','20270527','106','20270627',
            '0','','0','','0','','103','20261027','103','20261127','103','20261227');
        -- ligne manuelle en attente : A cantine 3 j au prorata 9/10
        INSERT INTO FAC_GESTION_HISTO VALUES ('10', '1', 'CANT3J', '1', 'Cantine 3 jours complement', '270');
        -- piece recue : certificat ext. de RB, sans « Justificatif Fraterie » saisi
        INSERT INTO INS_PIECES_DOSSIER VALUES ('1', 'Certificat ext.'), ('2', 'Justif APEL');
        INSERT INTO COM_LIEN_PIECE_LISTE VALUES ('11', '1'), ('12', '2');
        INSERT INTO COM_LIEN_PIECE_PERSONNE VALUES ('100', '20');
        INSERT INTO COM_PIECE_RECU VALUES ('100', '11', 'Reçue');
    """)
    yield c
    c.close()


def test_prorata_au_mois():
    assert indice_mois("20260915", REGLES) == 1 and indice_mois("20270627", REGLES) == 10
    assert indice_mois("20260715", REGLES) is None and indice_mois(date(2026, 10, 5), REGLES) == 2
    assert mois_restants(2, REGLES) == 9 and mois_restants(None, REGLES) == 0


def test_forfait_modifie(conn):
    r = regularisations_a_preparer(conn, REGLES, aujourd_hui=AUJ)
    assert r["mois_restants"] == 9 and r["coefficient_prorata"] == 0.9
    a = next(x for x in r["regularisations"] if x["id_eleve"] == 1)
    lignes = {l["code"]: l for l in a["lignes"]}
    # 2 jours factures a l'annee, 3 jours desormais : avoir 9/10 de 200, complement 9/10 de 300
    assert lignes["CANT2J"]["sens"] == "avoir" and lignes["CANT2J"]["montant_prorata"] == -180
    assert lignes["CANT3J"]["sens"] == "complement" and lignes["CANT3J"]["montant_prorata"] == 270
    assert lignes["CANT2J"]["montant_plein"] == -200 and lignes["CANT3J"]["montant_plein"] == 300
    assert a["net_prorata"] == 90 and a["net_plein"] == 100
    assert lignes["CANT3J"]["quote_part_payeurs"] == {"RA x": 270}
    assert lignes["CANT3J"]["deja_en_preparation_manuelle"] == 270
    # la ligne manuelle deja saisie dans Charlemagne est reconnue conforme au prorata
    assert "conforme au prorata 9/10" in r["lignes_manuelles_en_attente"][0]["controle"]
    # la contribution n'est pas touchee pour un eleve deja facture
    assert "CONTRIB" not in lignes


def test_nouvel_eleve_et_depart(conn):
    r = regularisations_a_preparer(conn, REGLES, aujourd_hui=AUJ)
    b = next(x for x in r["regularisations"] if x["id_eleve"] == 2)
    assert b["nouvel_eleve"] and b["entre_le"] == "20261003"
    lignes = {l["code"]: l["montant_prorata"] for l in b["lignes"]}
    # contribution de la classe et cantine 1 jour, 9 mois sur 10
    assert lignes == {"CONTRIB": 900, "CANT1J": 90}
    assert r["resume"]["nouveaux_eleves"] == 1
    # C sorti le 15/11 : novembre du, avoir de decembre a juin (7/10) sur toutes ses lignes
    d = r["departs"][0]
    assert d["id_eleve"] == 3 and d["sorti_le"] == "20261115"
    assert {l["code"]: l["montant_prorata"] for l in d["lignes"]} == {"CONTRIB": -700, "CANT2J": -140}
    assert all(x["id_eleve"] != 3 for x in r["regularisations"])


def test_complement_au_tarif_plein_couvre_l_annee(conn):
    r = regularisations_a_preparer(conn, REGLES, aujourd_hui=AUJ)
    assert all(x["id_eleve"] != 4 for x in r["regularisations"])
    # facture au prorata (27 = 9/10 de 30) a la place : il manquerait 3 en plein, 0 au prorata -> rien a faire
    conn.execute("UPDATE FAC_HISTO_LIGNE SET HL_TOTAL = '27' WHERE IDVALIDATION = '2'")
    r = regularisations_a_preparer(conn, REGLES, aujourd_hui=AUJ)
    d = next((x for x in r["regularisations"] if x["id_eleve"] == 4), None)
    assert d is not None and d["lignes"][0]["montant_prorata"] == 0 and d["lignes"][0]["montant_plein"] == 3


def test_apel_justificatifs_et_filtres(conn):
    r = regularisations_a_preparer(conn, REGLES, aujourd_hui=AUJ)
    assert r["apel"] == [{"responsable": "RA x", "foyer": "Ext", "deja_facture": 20, "attendu": 8, "montant": -12,
                          "sens": "avoir", "saisie_proposee": r["apel"][0]["saisie_proposee"]}]
    assert r["apel"][0]["saisie_proposee"]["prix"] == -12
    # certificat recu pour RB mais « Justificatif Fraterie » non saisi ; RA a saisi le justificatif APEL sans piece
    assert [(x["responsable"], x["piece"]) for x in r["a_saisir_avant_de_facturer"]] == [("RB x", "Certificat ext.")]
    assert [(x["responsable"], x["piece"]) for x in r["information_saisie_sans_piece"]] == [("RA x", "Justif APEL")]
    # un seul eleve
    r1 = regularisations_a_preparer(conn, REGLES, id_eleve="1", aujourd_hui=AUJ)
    assert [x["id_eleve"] for x in r1["regularisations"]] == [1] and r1["apel"] == []
    with pytest.raises(ValueError):
        regularisations_a_preparer(conn, REGLES, id_eleve="99", aujourd_hui=AUJ)
    with pytest.raises(ValueError):
        regularisations_a_preparer(conn, REGLES, date_effet="2026-08-01", aujourd_hui=AUJ)
    # date d'effet explicite : janvier -> 6 mois
    assert regularisations_a_preparer(conn, REGLES, date_effet="2027-01-10", aujourd_hui=AUJ)["mois_restants"] == 6


def test_suivi_echeanciers(conn):
    # RA passe en cheque sur sa fiche apres la facture ; l'eleve A est desormais paye par RB
    conn.execute("UPDATE COM_RESPONSABLES SET RE_MODE_REGLEMENT = 'Chèque' WHERE IDRESPONSABLE = '10'")
    conn.execute("UPDATE COM_LIENER SET IDRESPONSABLE = '20' WHERE IDELEVE = '1'")
    r = suivi_echeanciers(conn, REGLES, aujourd_hui=AUJ)
    assert r["resume"]["familles"] == 3 and r["resume"]["familles_avec_plusieurs_factures"] == 1
    assert r["resume"]["total_facture"] == 1220 + 1200 + 1000 + 30
    assert set(r["nb_alertes"]) == {"mode_reglement_modifie", "payeur_modifie_depuis_facturation"}
    ra = next(f for f in r["familles"] if f["id_responsable"] == 10)
    assert [a["type"] for a in ra["alertes"]] == ["mode_reglement_modifie", "payeur_modifie_depuis_facturation"]
    assert len(ra["echeances_passees"]) == 1 and len(ra["echeances_a_venir"]) == 9 and ra["reste_a_prelever"] == 1098
    rd = next(f for f in r["familles"] if f["id_responsable"] == 40)
    assert [x["numero"] for x in rd["factures"]] == ["3", "4"] and rd["total_facture"] == 1030 and rd["alertes"] == []
    assert rd["reste_a_prelever"] == 930  # 900 repris + 30, re-etales sur 9 echeances
    # echeancier incoherent
    conn.execute("UPDATE FAC_HISTO_FAMILLE SET HF_ECHE_PRIX6 = '50' WHERE IDVALIDATION = '2'")
    r = suivi_echeanciers(conn, REGLES, id_responsable="40", aujourd_hui=AUJ)
    assert r["alertes"]["echeancier_incoherent"][0]["somme_echeances"] == 874
    with pytest.raises(ValueError):
        suivi_echeanciers(conn, REGLES, id_responsable="99", aujourd_hui=AUJ)


def test_suivi_echeanciers_avec_comptabilite(conn):
    sans = suivi_echeanciers(conn, REGLES, aujourd_hui=AUJ)
    assert all("comptabilite" not in f for f in sans["familles"]) and "statut paye/impaye" in sans["note"]
    a_jour = {"compte": "4111X", "solde": 0.0, "retard": 0.0, "en_avance": 0.0}
    en_retard = {"compte": "4111Y", "solde": 300.0, "retard": 120.0, "en_avance": 0.0,
                 "echeances_non_couvertes": [{"date": "2026-09-29", "montant": 120.0}], "impayes": None,
                 "dernier_reglement": None}
    comptes = {str(r): a_jour for r in (10, 20, 30, 40)}
    comptes["30"] = en_retard
    r = suivi_echeanciers(conn, REGLES, aujourd_hui=AUJ, comptes=comptes)
    assert r["nb_alertes"].get("retard_de_paiement") == 1
    rc = next(f for f in r["familles"] if f["id_responsable"] == 30)      # listee grace a l'alerte
    assert rc["comptabilite"]["retard"] == 120.0
    assert rc["alertes"][-1]["echeances_non_couvertes"][0]["montant"] == 120.0
    assert "FEC" in r["note"] and "statut paye/impaye" not in r["note"]
    # sous le seuil : pas d'alerte
    comptes["30"] = {**en_retard, "retard": 0.5}
    assert "retard_de_paiement" not in suivi_echeanciers(conn, REGLES, aujourd_hui=AUJ, comptes=comptes)["nb_alertes"]



def test_saisie_au_montant_plein(conn):
    """regles prorata.saisie = "plein" : la saisie proposee prend le montant plein
    (decision de l'etablissement), les deux montants restent renvoyes."""
    import copy
    regles = copy.deepcopy(REGLES)
    regles["prorata"]["saisie"] = "plein"
    r = regularisations_a_preparer(conn, regles, aujourd_hui=AUJ)
    assert r["mode_saisie"] == "plein"
    a = next(x for x in r["regularisations"] if x["id_eleve"] == 1)
    lignes = {l["code"]: l for l in a["lignes"]}
    assert lignes["CANT2J"]["saisie_proposee"]["prix"] == -200 and lignes["CANT2J"]["sens"] == "avoir"
    assert lignes["CANT3J"]["saisie_proposee"]["prix"] == 300 and lignes["CANT3J"]["montant_prorata"] == 270
    assert lignes["CANT3J"]["quote_part_payeurs"] == {"RA x": 300}
    assert lignes["CANT3J"]["saisie_proposee"]["libelle"].endswith("annuel")
    regles["prorata"]["saisie"] = "autre"
    with pytest.raises(ValueError):
        regularisations_a_preparer(conn, regles, aujourd_hui=AUJ)
