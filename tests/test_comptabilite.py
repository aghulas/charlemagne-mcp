"""Tests du loader FEC et des outils comptables - donnees synthetiques uniquement."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loader import load_fec as L  # noqa: E402
from tools import comptabilite as C  # noqa: E402

ENTETE = "\t".join(L.COLONNES_FEC)


def ligne(j, jlib, d, cpt, aux, piece, lib, deb, cre, let=""):
    champs = [j, jlib, "", d, cpt, "Libelle " + cpt, aux, ("Famille " + aux) if aux else "", piece, d, lib,
              f"{deb:.2f}".replace(".", ","), f"{cre:.2f}".replace(".", ","), let, "", d, "", ""]
    return "\t".join(champs) + f"\t{j}+{piece}"


def fec_synthetique(dossier: Path) -> Path:
    L_ = [
        # a-nouveaux : famille A doit 10 depuis l'an dernier
        ligne("AN", "A.NOUVEAUX", "20250901", "4111000", "4111ALPHA", "AN1", "Report", 10, 0),
        ligne("AN", "A.NOUVEAUX", "20250901", "8900000", "", "AN1", "Report", 0, 10),
        # facturation du 15/09 : A 300 (prelevement), B 200 (cheque)
        ligne("70", "FACTURATIONS", "20260915", "4111000", "4111ALPHA", "1", "Facture", 300, 0),
        ligne("70", "FACTURATIONS", "20260915", "4111000", "4111BETA", "2", "Facture", 200, 0),
        ligne("70", "FACTURATIONS", "20260915", "7061000", "", "1", "Contribution", 0, 500),
        # remise du 29/09 comptabilisee le 01/10 : A paie 110 (100 + report 10)
        ligne("56", "BANQUE", "20261001", "4111000", "4111ALPHA", "10-26/1", "PA de ALPHA", 0, 110),
        ligne("56", "BANQUE", "20261001", "5127100", "", "10-26/1", "PA de ALPHA", 110, 0),
        # impaye de A le 03/10 + 15 EUR de frais refactures (credit 758)
        ligne("56", "BANQUE", "20261003", "4111000", "4111ALPHA", "10-26/2", "Impaye septembre famille ALPHA", 110, 0),
        ligne("56", "BANQUE", "20261003", "5127100", "", "10-26/2", "Impaye septembre famille ALPHA", 0, 110),
        ligne("56", "BANQUE", "20261003", "4111000", "4111ALPHA", "10-26/2", "Impaye septembre famille ALPHA", 15, 0),
        ligne("56", "BANQUE", "20261003", "7580000", "", "10-26/2", "Impaye septembre famille ALPHA", 0, 15),
        # paie : detail jamais conserve
        ligne("PA", "PAIES", "20260930", "4210000", "421DUPONT", "PA1", "Salaire DUPONT", 0, 1000),
        ligne("PA", "PAIES", "20260930", "6411000", "", "PA1", "Salaire DUPONT", 1000, 0),
    ]
    p = dossier / "123456789FEC20260831.txt"
    p.write_bytes(("\r\n".join([ENTETE] + L_) + "\r\n").encode("cp1252"))
    return p


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "compta.db"
    L.charger(fec_synthetique(tmp_path), db)
    c = sqlite3.connect(":memory:", uri=True)
    ech = ", ".join(f"HF_ECHE_PRIX{i} TEXT, HF_ECHE_DATE{i} TEXT" for i in range(1, 13))
    c.executescript(f"""
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_CODE_COMPTABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT);
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT);
        CREATE TABLE FAC_HISTO_FAMILLE (IDVALIDATION TEXT, IDRESPONSABLE TEXT, HF_MODE_REGLEMENT TEXT,
            HF_DATE_FACTURE TEXT, {ech});
        INSERT INTO COM_RESPONSABLES VALUES ('1', '4111ALPHA', 'ALPHA', 'Anne'), ('2', '4111BETA', 'BETA', 'Bruno');
        INSERT INTO COM_ELEVES VALUES ('10', 'ALPHA', 'Alice', '5', ''), ('20', 'BETA', 'Basile', '6', '');
        INSERT INTO COM_CLASSES VALUES ('5', 'CM1'), ('6', 'CP');
        INSERT INTO COM_LIENER VALUES ('1', '10'), ('2', '20');
    """)
    # A : 3 prelevements de 110, 100, 100 (29/09, 27/10, 27/11) ; B : une echeance cheque de 200 au 15/09
    c.execute("INSERT INTO FAC_HISTO_FAMILLE (IDVALIDATION, IDRESPONSABLE, HF_MODE_REGLEMENT, HF_DATE_FACTURE, "
              "HF_ECHE_DATE1, HF_ECHE_PRIX1, HF_ECHE_DATE2, HF_ECHE_PRIX2, HF_ECHE_DATE3, HF_ECHE_PRIX3) "
              "VALUES ('1', '1', 'Prélèvement', '20260915', '20261127', '100', '20260929', '110', '20261027', '100')")
    c.execute("INSERT INTO FAC_HISTO_FAMILLE (IDVALIDATION, IDRESPONSABLE, HF_MODE_REGLEMENT, HF_DATE_FACTURE, "
              "HF_ECHE_DATE1, HF_ECHE_PRIX1) VALUES ('1', '2', 'Chèque', '20260915', '20260915', '200')")
    c.execute("ATTACH DATABASE ? AS compta", (str(db),))
    yield c
    c.close()


def test_loader_resume_et_paie_masquee(tmp_path):
    db = tmp_path / "c.db"
    r = L.charger(fec_synthetique(tmp_path), db)
    assert r["nb_lignes"] == 13 and r["periode_debut"] == "20250901" and r["periode_fin"] == "20261003"
    assert r["total_debit"] == r["total_credit"]
    c = sqlite3.connect(db)
    paie = c.execute("SELECT libelle, compte_aux, debit + credit, masquee FROM CPT_ECRITURE WHERE journal = 'PA'").fetchall()
    assert all(lib == "" and aux == "" and m == 1 for lib, aux, _, m in paie)
    assert sorted(x[2] for x in paie) == [1000, 1000]
    assert c.execute("SELECT cle_piece FROM CPT_ECRITURE WHERE rang = 3").fetchone()[0] == "70+1"
    # rechargement : remplacement complet, pas de cumul
    r2 = L.charger(fec_synthetique(tmp_path), db)
    assert r2["avant"]["nb_lignes"] == 13
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM CPT_ECRITURE").fetchone()[0] == 13


def test_loader_refuse_un_fec_plus_court(tmp_path):
    db = tmp_path / "c.db"
    L.charger(fec_synthetique(tmp_path), db)
    court = tmp_path / "court.txt"
    court.write_text(ENTETE + "\n" + ligne("OD", "OD", "20260101", "4710000", "", "1", "x", 10, 0) + "\n"
                     + ligne("OD", "OD", "20260101", "4710001", "", "1", "x", 0, 10) + "\n", encoding="cp1252")
    with pytest.raises(ValueError, match="plus court"):
        L.charger(court, db)
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM CPT_ECRITURE").fetchone()[0] == 13
    assert L.charger(court, db, accepter_recul=True)["nb_lignes"] == 2


def test_loader_accepte_une_ecriture_recente_supprimee(tmp_path):
    # la derniere ecriture a ete supprimee dans Charlemagne : la periode recule de quelques lignes seulement
    db = tmp_path / "c.db"
    L.charger(fec_synthetique(tmp_path), db)
    p = tmp_path / "123456789FEC20260831.txt"
    lignes = p.read_bytes().decode("cp1252").split("\r\n")
    garde = [l for l in lignes if "20261003" not in l]          # 4 lignes du 03/10 supprimees
    p.write_bytes("\r\n".join(garde).encode("cp1252"))
    r = L.charger(p, db)
    assert r["periode_fin"] == "20261001" and r["nb_lignes"] == 9


def test_loader_refuse_un_fec_desequilibre(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text(ENTETE + "\n" + ligne("OD", "OD", "20260101", "4710000", "", "1", "x", 10, 0) + "\n", encoding="cp1252")
    with pytest.raises(ValueError, match="desequilibre"):
        L.charger(p, tmp_path / "x.db")


def test_classement_et_solde_famille(conn):
    r = C.encaissements_famille(conn, id_responsable="1", date_reference="2026-10-08")
    f = r["familles"][0]
    assert f["compte"] == "4111ALPHA" and f["responsable"] == "ALPHA Anne"
    assert f["enfants"] == ["Alice ALPHA (CM1)"]
    # 10 report + 300 facture - 110 paye + 110 impaye + 15 frais
    assert f["solde"] == 325.0
    assert f["totaux"] == {"a_nouveau": 10.0, "facture": 300.0, "reglement": -110.0, "impaye": 110.0,
                           "frais_impaye": 15.0}
    # echeances : 29/09 echue (non couverte), 27/10 et 27/11 a venir -> retard = 325 - 200 = 125
    assert f["retard"] == 125.0
    assert [e["statut"] for e in f["echeances"]] == ["non couverte", "a venir", "a venir"]
    assert f["dernier_reglement"]["mode"] == "prelevement"
    assert len(f["impayes"]) == 1


def test_delai_de_comptabilisation(conn):
    # au 30/09, l'echeance du 29/09 n'est pas encore comptee echue (delai 5 j)
    f = C.encaissements_famille(conn, compte="4111ALPHA", date_reference="2026-09-30")["familles"][0]
    assert f["retard"] == 0.0 and all(e["statut"] == "a venir" for e in f["echeances"])


def test_famille_par_eleve(conn):
    r = C.encaissements_famille(conn, id_eleve="20", date_reference="2026-10-08")
    assert [f["compte"] for f in r["familles"]] == ["4111BETA"]
    with pytest.raises(ValueError):
        C.encaissements_famille(conn)
    with pytest.raises(ValueError):
        C.encaissements_famille(conn, id_responsable="99")


def test_impayes_et_retards(conn):
    r = C.impayes_et_retards(conn, date_reference="2026-10-08")
    assert r["resume"]["familles_en_retard"] == 2
    a, b = sorted(r["familles_en_retard"], key=lambda x: x["compte"])
    assert a["retard"] == 125.0 and a["impayes_saisis"]["nombre"] == 1 and a["frais_impayes"] == 15.0
    assert a["plus_ancienne_non_couverte"] == "2026-09-29"
    assert b["retard"] == 200.0 and b["mode_reglement"] == "Chèque" and b["anciennete_jours"] == 23
    assert r["resume"]["par_mode_reglement"]["Chèque"]["montant"] == 200.0
    assert r["resume"]["impayes_saisis_sur_la_periode"] == {"lignes": 1, "familles": 1, "montant": 110.0}
    # filtres
    assert C.impayes_et_retards(conn, date_reference="2026-10-08", classe="CP")["resume"]["familles_en_retard"] == 1
    assert C.impayes_et_retards(conn, date_reference="2026-10-08", mode_reglement="prélèvement")[
        "resume"]["familles_en_retard"] == 1


def test_base_comptable_absente():
    c = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="Base comptable"):
        C.impayes_et_retards(c)


def test_chemin_de_la_base_comptable(monkeypatch, tmp_path):
    from db.connection_compta import chemin_compta
    monkeypatch.delenv("CHARLEMAGNE_COMPTA_DB", raising=False)
    monkeypatch.setenv("CHARLEMAGNE_DB", str(tmp_path / "administration_consolidee.db"))
    assert chemin_compta() == tmp_path / "comptabilite_consolidee.db"
    monkeypatch.setenv("CHARLEMAGNE_COMPTA_DB", str(tmp_path / "autre.db"))
    assert chemin_compta() == tmp_path / "autre.db"


def test_controle_prelevements(conn):
    # echeance du 29/09 : A attendu 110 (prelevement), preleve 110 le 01/10, puis rejete le 03/10 ; B paie par cheque
    r = C.controle_prelevements(conn)
    assert r["date_echeance"] == "2026-09-29" and r["statut"] == "conforme"
    assert r["attendu"] == {"familles": 1, "montant": 110.0}
    assert r["preleve"]["montant"] == 110.0 and r["preleve"]["comptabilise_le"] == {"2026-10-01": 1}
    assert r["rejets_saisis"] == {"familles": 1, "montant": 110.0} and r["encaisse_net"] == 0.0
    assert r["prochaine_echeance"] == {"date": "2026-10-27", "familles": 1, "montant": 100.0}
    # echeance future : remise pas encore comptabilisee, famille attendue signalee manquante
    r2 = C.controle_prelevements(conn, date_echeance="2026-10-27")
    assert r2["statut"] == "remise non encore comptabilisee" and r2["manquants"] == []
    assert r2["attendu"] == {"familles": 1, "montant": 100.0}
    with pytest.raises(ValueError, match="Pas d'echeance"):
        C.controle_prelevements(conn, date_echeance="2026-10-15")


def test_controle_prelevements_ecart_et_facture_complementaire(conn):
    # complementaire du 01/10 pour A : l'echeance du 29/09 reste celle de la facture initiale,
    # celle du 27/10 vient de la complementaire (120 au lieu de 100)
    conn.execute("INSERT INTO FAC_HISTO_FAMILLE (IDVALIDATION, IDRESPONSABLE, HF_MODE_REGLEMENT, HF_DATE_FACTURE, "
                 "HF_ECHE_DATE1, HF_ECHE_PRIX1, HF_ECHE_DATE2, HF_ECHE_PRIX2) "
                 "VALUES ('2', '1', 'Prélèvement', '20261001', '20261027', '120', '20261127', '120')")
    assert C.controle_prelevements(conn, date_echeance="2026-09-29")["attendu"]["montant"] == 110.0
    assert C.controle_prelevements(conn, date_echeance="2026-10-27")["attendu"]["montant"] == 120.0


def _facturation(conn):
    conn.executescript("""
        ALTER TABLE FAC_HISTO_FAMILLE ADD COLUMN HF_NUMERO_FACTURE TEXT;
        ALTER TABLE FAC_HISTO_FAMILLE ADD COLUMN HF_APAYER_FACTURE TEXT;
        UPDATE FAC_HISTO_FAMILLE SET HF_NUMERO_FACTURE = '1', HF_APAYER_FACTURE = '300' WHERE IDRESPONSABLE = '1';
        UPDATE FAC_HISTO_FAMILLE SET HF_NUMERO_FACTURE = '2', HF_APAYER_FACTURE = '200' WHERE IDRESPONSABLE = '2';
        CREATE TABLE FAC_VALIDATION (IDVALIDATION TEXT, VA_TYPE_FACTURE TEXT, VA_NB_FACTURES TEXT, VA_NUMERO_DEBUT TEXT,
            VA_NUMERO_FIN TEXT, VA_DATE_HEURE TEXT);
        INSERT INTO FAC_VALIDATION VALUES ('1', 'Toutes', '2', '1', '2', 'Le 29/09/2026');
        CREATE TABLE FAC_COMPTA_GENERAL (IDVALIDATION TEXT, CG_COMPTE TEXT, CG_DEBIT TEXT, CG_CREDIT TEXT, CG_DATE_FACTURE TEXT);
        INSERT INTO FAC_COMPTA_GENERAL VALUES ('1', '7061000', '0', '500', '20260915');
    """)


def test_pont_facturation_conforme(conn):
    _facturation(conn)
    r = C.pont_facturation_comptabilite(conn)
    v = r["validations"][0]
    assert v["statut"] == "passee en comptabilite" and v["numeros"] == "1 a 2"
    assert v["factures"] == {"nombre": 2, "montant": 500.0, "retrouvees": 2, "montant_comptabilite": 500.0}
    assert r["produits_par_date"][0]["ecarts"] == [] and r["produits_par_date"][0]["total_comptabilite"] == 500.0
    assert r["ecritures_familles_sans_facture"] == []


def test_pont_facturation_ecarts_et_validation_absente(conn):
    _facturation(conn)
    conn.executescript("""
        UPDATE FAC_HISTO_FAMILLE SET HF_APAYER_FACTURE = '250' WHERE IDRESPONSABLE = '2';
        INSERT INTO FAC_VALIDATION VALUES ('2', 'Manuelles', '1', '3', '3', 'Le 01/10/2026');
        INSERT INTO FAC_HISTO_FAMILLE (IDVALIDATION, IDRESPONSABLE, HF_MODE_REGLEMENT, HF_DATE_FACTURE, HF_NUMERO_FACTURE,
            HF_APAYER_FACTURE) VALUES ('2', '1', 'Prélèvement', '20261001', '3', '40');
        INSERT INTO FAC_COMPTA_GENERAL VALUES ('2', '7061000', '0', '40', '20261001');
    """)
    r = C.pont_facturation_comptabilite(conn)
    v1, v2 = r["validations"]
    assert v1["statut"] == "passee, avec ecarts"
    assert v1["ecarts_de_montant"] == [{"facture": "2", "responsable": "BETA Bruno", "id_responsable": 2,
                                        "montant_facture": 250.0, "montant_comptabilite": 200.0}]
    assert v2["statut"] == "non passee en comptabilite" and v2["factures_absentes"][0]["facture"] == "3"
    assert r["produits_par_date"][1]["ecarts"] == [{"compte": "7061000", "facturation": 40.0, "comptabilite": 0.0}]
    assert C.pont_facturation_comptabilite(conn, validation="2")["validations"][0]["validation"] == 2
    with pytest.raises(ValueError, match="inconnue"):
        C.pont_facturation_comptabilite(conn, validation="9")
