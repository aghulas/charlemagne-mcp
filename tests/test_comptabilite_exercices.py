"""Tests des exercices clos (loader) et des outils d'ecritures par compte - donnees synthetiques uniquement."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loader import load_fec as L  # noqa: E402
from tools import comptabilite_exercices as X  # noqa: E402

ENTETE = "\t".join(L.COLONNES_FEC)


def ligne(j, jlib, d, cpt, aux, piece, lib, deb, cre):
    champs = [j, jlib, "", d, cpt, "Libelle " + cpt, aux, ("Famille " + aux) if aux else "", piece, d, lib,
              f"{deb:.2f}".replace(".", ","), f"{cre:.2f}".replace(".", ","), "", "", d, "", ""]
    return "\t".join(champs) + f"\t{j}+{piece}"


def ecrire(dossier: Path, nom: str, lignes: list[str]) -> Path:
    p = dossier / nom
    p.write_bytes(("\r\n".join([ENTETE] + lignes) + "\r\n").encode("cp1252"))
    return p


def fec_courant(dossier: Path) -> Path:
    """Exercice 2025-2026 (+ debut de 2026-2027) : informatique, paie, famille, a-nouveaux."""
    return ecrire(dossier, "123456789FEC20260831.txt", [
        ligne("AN", "A.NOUVEAUX", "20250901", "5127000", "", "AN1", "Report", 500, 0),
        ligne("AN", "A.NOUVEAUX", "20250901", "1100000", "", "AN1", "Report", 0, 500),
        ligne("ACH", "ACHATS", "20250912", "6064100", "", "1", "AMAZON (routeur)", 100, 0),
        ligne("ACH", "ACHATS", "20250912", "4012000", "", "1", "AMAZON (routeur)", 0, 100),
        ligne("ACH", "ACHATS", "20251018", "6064100", "", "2", "Amazon", 50, 0),
        ligne("ACH", "ACHATS", "20251018", "4012000", "", "2", "Amazon", 0, 50),
        ligne("ACH", "ACHATS", "20251107", "6065700", "", "3", "Openai chatgpt", 23, 0),
        ligne("ACH", "ACHATS", "20251107", "4012000", "", "3", "Openai chatgpt", 0, 23),
        ligne("ACH", "ACHATS", "20260820", "6065700", "", "4", "FNP MICROSOFT AU 31/08/2026", 2000, 0),
        ligne("OD", "OPERATIONS DIVERSES", "20260831", "4081000", "", "4", "FNP MICROSOFT AU 31/08/2026", 0, 2000),
        ligne("70", "FACTURATIONS", "20250915", "4111000", "4111ALPHA", "9", "Facture", 300, 0),
        ligne("70", "FACTURATIONS", "20250915", "7061000", "", "9", "Contribution", 0, 300),
        ligne("PA", "PAIES", "20251031", "4210000", "421DUPONT", "PA1", "Salaire DUPONT", 0, 1000),
        ligne("PA", "PAIES", "20251031", "6411000", "", "PA1", "Salaire DUPONT", 1000, 0),
        ligne("ACH", "ACHATS", "20260915", "6064100", "", "5", "Amazon", 40, 0),      # exercice suivant, partiel
        ligne("ACH", "ACHATS", "20260915", "4012000", "", "5", "Amazon", 0, 40),
    ])


def fec_clos(dossier: Path, nom: str = "123456789FEC20250831.txt", extra: list[str] | None = None) -> Path:
    """Exercice 2024-2025."""
    return ecrire(dossier, nom, [
        ligne("AN", "A.NOUVEAUX", "20240901", "5127000", "", "AN0", "Report", 300, 0),
        ligne("AN", "A.NOUVEAUX", "20240901", "1100000", "", "AN0", "Report", 0, 300),
        ligne("ACH", "ACHATS", "20241005", "6064100", "", "1", "AMAZON", 30, 0),
        ligne("ACH", "ACHATS", "20241005", "4012000", "", "1", "AMAZON", 0, 30),
        ligne("ACH", "ACHATS", "20250310", "6065700", "", "2", "Microsoft", 90, 0),
        ligne("ACH", "ACHATS", "20250310", "4012000", "", "2", "Microsoft", 0, 90),
        ligne("70", "FACTURATIONS", "20240915", "4111000", "4111ALPHA", "9", "Facture", 280, 0),
        ligne("70", "FACTURATIONS", "20240915", "7061000", "", "9", "Contribution", 0, 280),
        ligne("PA", "PAIES", "20241031", "4210000", "421DUPONT", "PA1", "Salaire DUPONT", 0, 800),
        ligne("PA", "PAIES", "20241031", "6411000", "", "PA1", "Salaire DUPONT", 800, 0),
    ] + (extra or []))


@pytest.fixture
def base(tmp_path):
    db = tmp_path / "compta.db"
    L.charger(fec_courant(tmp_path), db)
    return db


@pytest.fixture
def base_clos(tmp_path, base):
    L.charger(fec_clos(tmp_path), base)
    return base


def connexion(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH DATABASE ? AS compta", (str(db),))
    return c


# --- chargeur --------------------------------------------------------------------------------------

def test_exercice_de():
    assert L.exercice_de("20250831") == "2024-2025"
    assert L.exercice_de("20250901") == "2025-2026"
    assert L.exercice_de("20260115") == "2025-2026"


def test_fec_clos_range_a_part_sans_toucher_la_periode_courante(tmp_path, base):
    avant = sqlite3.connect(base).execute("SELECT COUNT(*), SUM(debit) FROM CPT_ECRITURE").fetchone()
    r = L.charger(fec_clos(tmp_path), base)
    assert r["clos"] and r["exercice"] == "2024-2025" and r["avant"] is None
    c = sqlite3.connect(base)
    assert c.execute("SELECT COUNT(*), SUM(debit) FROM CPT_ECRITURE").fetchone() == avant
    assert c.execute("SELECT COUNT(*) FROM CPT_ECRITURE_CLOS").fetchone()[0] == 10
    assert c.execute("SELECT exercice, nb_lignes FROM CPT_EXPORT_CLOS").fetchall() == [("2024-2025", 10)]
    assert c.execute("SELECT COUNT(*) FROM CPT_EXPORT").fetchone()[0] == 1       # la periode courante reste seule
    # paie masquee aussi pour les exercices clos
    paie = c.execute("SELECT libelle, compte_aux, masquee FROM CPT_ECRITURE_CLOS WHERE journal = 'PA'").fetchall()
    assert paie and all(lib == "" and aux == "" and m == 1 for lib, aux, m in paie)


def test_recharger_la_periode_courante_conserve_les_exercices_clos(tmp_path, base_clos):
    r = L.charger(fec_courant(tmp_path), base_clos)
    assert not r.get("clos")
    c = sqlite3.connect(base_clos)
    assert c.execute("SELECT COUNT(*) FROM CPT_ECRITURE_CLOS").fetchone()[0] == 10
    assert c.execute("SELECT COUNT(*) FROM CPT_EXPORT_CLOS").fetchone()[0] == 1


def test_recharger_un_exercice_clos_remplace_sans_doublon(tmp_path, base_clos):
    r = L.charger(fec_clos(tmp_path), base_clos)
    assert r["avant"]["nb_lignes"] == 10
    c = sqlite3.connect(base_clos)
    assert c.execute("SELECT COUNT(*) FROM CPT_ECRITURE_CLOS").fetchone()[0] == 10
    assert c.execute("SELECT COUNT(*) FROM CPT_EXPORT_CLOS").fetchone()[0] == 1


def test_fec_clos_a_cheval_sur_deux_exercices_refuse(tmp_path, base):
    p = fec_clos(tmp_path, nom="x_cheval.txt")
    p.write_bytes(p.read_bytes().replace(b"20240901", b"20230901", 1))     # a-nouveaux dates de l'exercice precedent
    with pytest.raises(ValueError, match="plusieurs exercices"):
        L.charger(p, base)
    assert sqlite3.connect(base).execute("SELECT COUNT(*) FROM CPT_ECRITURE_CLOS").fetchone()[0] == 0


def test_fec_clos_desequilibre_refuse(tmp_path, base):
    p = fec_clos(tmp_path, nom="x_desequilibre.txt", extra=[ligne("ACH", "ACHATS", "20250301", "6064100", "", "9", "Amazon", 5, 0)])
    with pytest.raises(ValueError, match="desequilibre"):
        L.charger(p, base)


def test_fec_clos_plus_court_refuse_sauf_option(tmp_path, base):
    lignes = []
    for i in range(30):
        lignes += [ligne("ACH", "ACHATS", "20250310", "6064100", "", f"x{i}", "Amazon", 1, 0),
                   ligne("ACH", "ACHATS", "20250310", "4012000", "", f"x{i}", "Amazon", 0, 1)]
    L.charger(ecrire(tmp_path, "gros.txt", lignes), base)
    court = fec_clos(tmp_path, nom="court.txt")
    with pytest.raises(ValueError, match="plus court"):
        L.charger(court, base)
    L.charger(court, base, accepter_recul=True)
    assert sqlite3.connect(base).execute("SELECT COUNT(*) FROM CPT_ECRITURE_CLOS").fetchone()[0] == 10


# --- ecritures_par_compte --------------------------------------------------------------------------

def test_exercices_disponibles(tmp_path, base_clos):
    dispo = {e["exercice"]: e for e in X.exercices_disponibles(connexion(base_clos))}
    assert list(dispo) == ["2024-2025", "2025-2026", "2026-2027"]
    assert dispo["2024-2025"]["source"] == "clos" and dispo["2025-2026"]["source"] == "courant"
    assert dispo["2026-2027"]["partiel"] is True and dispo["2025-2026"]["partiel"] is False


def test_par_compte_sur_deux_exercices(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), ["6064100", "6065700"], exercices=["2024-2025", "2025-2026"])
    cles = {(l["exercice"], l["compte"]): l["montant"] for l in r["lignes"]}
    assert cles == {("2024-2025", "6064100"): 30, ("2024-2025", "6065700"): 90,
                    ("2025-2026", "6064100"): 150, ("2025-2026", "6065700"): 2023}
    assert r["totaux"]["2025-2026"]["montant"] == 2173
    assert r["totaux"]["2024-2025"]["nb"] == 2


def test_a_nouveaux_exclus_par_defaut(base_clos):
    c = connexion(base_clos)
    assert X.ecritures_par_compte(c, "5127000", exercices="2025-2026")["lignes"] == []
    r = X.ecritures_par_compte(c, "5127000", exercices="2025-2026", inclure_a_nouveaux=True)
    assert r["lignes"][0]["montant"] == 500


def test_par_libelle_regroupe_les_variantes(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), "6064100", exercices="2025-2026", grouper_par="libelle")
    assert {l["libelle"]: l["montant"] for l in r["lignes"] if l["exercice"] == "2025-2026"} == {"AMAZON": 150}
    r = X.ecritures_par_compte(connexion(base_clos), "6065700", exercices="2025-2026", grouper_par="libelle")
    assert r["lignes"][0]["libelle"] == "FNP MICROSOFT AU"      # tri par montant decroissant


def test_par_ecriture_et_recherche(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), "606", exercices="2025-2026", grouper_par="ecriture",
                               recherche="chatgpt")
    assert [(l["date"], l["compte"], l["debit"]) for l in r["lignes"]] == [("20251107", "6065700", 23.0)]


def test_par_mois(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), "6064100", exercices="2025-2026", grouper_par="mois")
    assert [(l["mois"], l["montant"]) for l in r["lignes"]] == [("2025-09", 100), ("2025-10", 50)]
    r = X.ecritures_par_compte(connexion(base_clos), "6064100", exercices=["2025-2026", "2026-2027"], grouper_par="mois")
    assert [(l["exercice"], l["mois"]) for l in r["lignes"]][-1] == ("2026-2027", "2026-09")


def test_paie_et_familles_jamais_detaillees(base_clos):
    c = connexion(base_clos)
    detail = X.ecritures_par_compte(c, ["64", "411"], exercices="2025-2026", grouper_par="ecriture")
    assert detail["lignes"] == [] and "detail non communique" in detail["exclus_du_detail"]
    libelles = X.ecritures_par_compte(c, ["64"], grouper_par="libelle")
    assert libelles["lignes"] == []
    assert X.ecritures_par_compte(c, "64", exercices="2025-2026", recherche="DUPONT")["lignes"] == []
    # totaux par compte et par mois : autorises
    tot = X.ecritures_par_compte(c, "64", exercices=["2024-2025", "2025-2026"])
    assert {(l["exercice"], l["compte"]): l["montant"] for l in tot["lignes"]} == \
        {("2024-2025", "6411000"): 800, ("2025-2026", "6411000"): 1000}
    mois = X.ecritures_par_compte(c, "64", exercices="2025-2026", grouper_par="mois")
    assert mois["lignes"][0]["mois"] == "2025-10" and "DUPONT" not in str(mois)


def test_produits_au_sens_naturel(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), "706", exercices=["2024-2025", "2025-2026"])
    assert {(l["exercice"], l["montant"]) for l in r["lignes"]} == {("2024-2025", 280), ("2025-2026", 300)}


def test_exercice_inconnu_ou_invalide(base_clos):
    c = connexion(base_clos)
    with pytest.raises(ValueError, match="non charge"):
        X.ecritures_par_compte(c, "606", exercices="2022-2023")
    with pytest.raises(ValueError, match="AAAA-AAAA"):
        X.ecritures_par_compte(c, "606", exercices="2025")
    with pytest.raises(ValueError, match="Compte invalide"):
        X.ecritures_par_compte(c, "60; DROP TABLE")
    with pytest.raises(ValueError, match="au moins un compte"):
        X.ecritures_par_compte(c, [])


def test_tronque(base_clos):
    r = X.ecritures_par_compte(connexion(base_clos), "6", exercices="2025-2026", grouper_par="ecriture", limite=2)
    assert len(r["lignes"]) == 2 and "tronque" in r and r["nb_lignes_totales"] > 2


# --- comparer_exercices_compta ---------------------------------------------------------------------

def test_comparer_par_compte(base_clos):
    r = X.comparer_exercices_compta(connexion(base_clos), "6064100,6065700", exercices=["2024-2025", "2025-2026"])
    par = {l["compte"]: l for l in r["lignes"]}
    assert par["6064100"]["montants"] == {"2024-2025": 30, "2025-2026": 150}
    assert par["6064100"]["ecart"] == 120 and par["6064100"]["ecart_pct"] == 400.0
    assert par["6065700"]["ecart"] == 1933
    assert r["totaux"] == {"2024-2025": 120, "2025-2026": 2173}
    assert r["ecart_entre"] == ["2024-2025", "2025-2026"]


def test_comparer_par_mois_rang_septembre_premier(base_clos):
    r = X.comparer_exercices_compta(connexion(base_clos), "6", exercices=["2024-2025", "2025-2026"], par="mois")
    par = {l["rang_mois"]: l for l in r["lignes"]}
    assert par[1]["mois"] == "septembre" and par[1]["montants"]["2025-2026"] == 100 and par[1]["montants"]["2024-2025"] is None
    assert par[2]["mois"] == "octobre" and par[2]["montants"] == {"2024-2025": 30 + 800, "2025-2026": 50 + 1000}
    assert par[12]["mois"] == "aout" and par[12]["montants"]["2025-2026"] == 2000


def test_comparer_signale_un_exercice_partiel(base_clos):
    r = X.comparer_exercices_compta(connexion(base_clos), "606")
    assert any("2026-2027" in a and "partiel" in a for a in r["avertissements"])
    with pytest.raises(ValueError, match="deux exercices"):
        X.comparer_exercices_compta(connexion(base_clos), "606", exercices="2025-2026")


def test_base_sans_tables_clos(tmp_path):
    """Base creee avant l'ajout des exercices clos : les outils marchent sur la periode courante seule."""
    db = tmp_path / "ancienne.db"
    L.charger(fec_courant(tmp_path), db)
    c = sqlite3.connect(db)
    c.executescript("DROP TABLE CPT_ECRITURE_CLOS; DROP TABLE CPT_EXPORT_CLOS;")
    c.commit()
    c.close()
    cx = connexion(db)
    assert [e["exercice"] for e in X.exercices_disponibles(cx)] == ["2025-2026", "2026-2027"]
    assert X.ecritures_par_compte(cx, "6064100", exercices="2025-2026")["totaux"]["2025-2026"]["montant"] == 150
    # et un exercice clos peut ensuite y etre ajoute (tables creees a la demande)
    L.charger(fec_clos(tmp_path), db)
    assert [e["exercice"] for e in X.exercices_disponibles(connexion(db))] == ["2024-2025", "2025-2026", "2026-2027"]


# --- outils du serveur MCP -------------------------------------------------------------------------

def test_outils_du_serveur(monkeypatch, base_clos):
    pytest.importorskip("mcp.server.mcpserver")
    import mcp_server

    outils = {}

    class FauxServeur:
        def tool(self, description="", **kw):
            def deco(f):
                outils[f.__name__] = f
                return f
            return deco

    mcp_server.register_tools(FauxServeur())
    assert {"ecritures_par_compte", "comparer_exercices_compta"} <= set(outils)

    monkeypatch.setattr(mcp_server, "get_compta_connection", lambda *a, **k: connexion(base_clos))
    r = outils["ecritures_par_compte"]("6064100", exercices="2024-2025,2025-2026")
    assert r["totaux"]["2025-2026"]["montant"] == 150 and r["totaux"]["2024-2025"]["montant"] == 30
    assert "error" in outils["ecritures_par_compte"]("6064100", exercices="2019-2020")
    assert "error" in outils["ecritures_par_compte"]("6064100", grouper_par="n'importe quoi")
    r = outils["comparer_exercices_compta"]("6064100", exercices="2024-2025,2025-2026")
    assert r["lignes"][0]["ecart"] == 120

    def absente(*a, **k):
        raise FileNotFoundError("absente")
    monkeypatch.setattr(mcp_server, "get_compta_connection", absente)
    assert "error" in outils["comparer_exercices_compta"]("6064100")


# --- selection des FEC du dossier d'echange --------------------------------------------------------

def test_selection_du_dossier_d_echange(tmp_path):
    from loader import fec_a_charger as S

    inbox, stage = tmp_path / "compta", tmp_path / "stage"
    inbox.mkdir()
    stage.mkdir()
    db = tmp_path / "compta.db"

    def sel():
        return S.selectionner(str(inbox), str(stage), str(db), attente=0, essais=2)

    assert sel() == []                                     # dossier vide
    (inbox / "notes.txt").write_text("pas un FEC")
    assert sel() == []                                     # fichier sans « fec » dans le nom
    courant = fec_courant(inbox)
    clos = fec_clos(inbox)
    sous = inbox / "exercices_clos"
    sous.mkdir()
    fec_clos(sous, nom="123456789FEC20240831.txt")         # sous-dossier : ignore
    r = sel()
    assert [Path(x["copie"]).name for x in r] == [courant.name, clos.name]      # le plus recent d'abord
    assert (stage / courant.name).exists() and (stage / clos.name).exists()

    # chargement dans l'ordre rendu : la periode courante puis l'exercice clos ; plus rien a faire ensuite
    for x in r:
        L.charger(Path(x["copie"]), db)
    assert sel() == [{"deja": True}]

    # un nouvel export de la periode courante est repris, pas l'exercice clos deja charge
    courant.write_bytes(courant.read_bytes().replace(b"\r\n", b"\r\n", 1) + b"\r\n")
    courant.write_bytes(courant.read_bytes() + (ligne("ACH", "ACHATS", "20260916", "6064100", "", "6", "Amazon", 1, 0) + "\r\n").encode("cp1252")
                        + (ligne("ACH", "ACHATS", "20260916", "4012000", "", "6", "Amazon", 0, 1) + "\r\n").encode("cp1252"))
    r = sel()
    assert [Path(x["copie"]).name for x in r] == [courant.name]

    # un FEC refuse n'est pas represente tant qu'il ne change pas
    (stage / "refus").mkdir()
    (stage / "refus" / r[0]["sha"]).write_text("")
    assert sel() == [{"deja": True}]
