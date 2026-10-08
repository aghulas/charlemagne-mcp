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
