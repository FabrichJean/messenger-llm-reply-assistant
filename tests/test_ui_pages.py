"""Interface web : assemblage des sources (hub/ui/), page servie, rechargement à chaud, JavaScript valide."""
import os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

os.environ.setdefault("HUB_DATA", tempfile.mkdtemp(prefix="relais-ui-"))      # l'import de la configuration crée des dossiers : on les isole
from hubtest.imp import HUB_DIR  # noqa: E402  (ajoute hub/ au chemin d'import)
from hubtest.harness import TestHub  # noqa: E402
from relais.web import pages  # noqa: E402

UI = Path(HUB_DIR) / "ui"


class AssembledPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_page_servie_egale_a_l_assemblage_des_sources(self):
        st, _, raw, _ = self.hub.admin().get("/")
        self.assertEqual(st, 200)
        self.assertEqual(raw, pages.assemble("index.html"))

    def test_aucun_repere_d_inclusion_ne_fuit(self):
        for p in ("/", "/login", "/join"):
            _, _, raw, _ = (self.hub.admin() if p == "/" else __import__("hubtest.harness", fromlist=["Http"]).Http(self.hub.base)).get(p)
            self.assertNotIn(b"{{include", raw, p)

    def test_les_sources_existent_et_sont_decoupees(self):
        for f in ("index.html", "login.html", "join.html", "css/base.css", "css/v3.css"):
            self.assertTrue((UI / f).exists(), f)
        self.assertGreaterEqual(len(list((UI / "js").glob("*.js"))), 8)
        self.assertLess(len((UI / "index.html").read_text(encoding="utf-8").splitlines()), 800)     # le squelette n'embarque plus ni CSS ni JS

    def test_chaque_inclusion_du_squelette_est_resolue(self):
        skeleton = (UI / "index.html").read_text(encoding="utf-8")
        for pattern in re.findall(r"\{\{include ([^}]+)\}\}", skeleton):
            self.assertTrue(list(UI.glob(pattern)), pattern)

    def test_un_seul_bloc_script_applicatif_avec_empreinte(self):
        """Le JavaScript reste en ligne (un bloc, donc une empreinte dans la CSP) : aucun script externe n'est introduit."""
        raw = pages.assemble("index.html").decode()
        self.assertNotRegex(raw, r"<script[^>]+src=")
        self.assertEqual(raw.count("<script>"), 3)                                                # 2 petits scripts d'en-tête + l'application


class IncludeMechanism(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="relais-pages-"))
        (self.d / "js").mkdir()
        (self.d / "js" / "b.js").write_text("B;", encoding="utf-8")
        (self.d / "js" / "a.js").write_text("A;\n", encoding="utf-8")
        (self.d / "p.html").write_text("<script>{{include js/*.js}}</script>", encoding="utf-8")
        self.old, pages.UI = pages.UI, self.d
        pages._cache.clear()

    def tearDown(self):
        pages.UI = self.old
        pages._cache.clear()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_inclusion_triee_et_sans_separateur(self):
        self.assertEqual(pages.assemble("p.html"), b"<script>A;\nB;</script>")

    def test_chemins_dangereux_refuses(self):
        for bad in ("../secret", "/etc/passwd", "js/../../x"):
            (self.d / "q.html").write_text("{{include " + bad + "}}", encoding="utf-8")
            with self.assertRaises(ValueError):
                pages.assemble("q.html")

    def test_inclusion_introuvable_signalee(self):
        (self.d / "q.html").write_text("{{include js/absent.js}}", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            pages.assemble("q.html")

    def test_rechargement_a_chaud(self):
        self.assertIn(b"B;", pages.page("p.html"))
        time.sleep(1.1)                                                                           # la vérification des sources est limitée à une par seconde
        (self.d / "js" / "b.js").write_text("MODIFIE;", encoding="utf-8")
        os.utime(self.d / "js" / "b.js", None)
        time.sleep(1.1)
        self.assertIn(b"MODIFIE;", pages.page("p.html"))


@unittest.skipUnless(shutil.which("node"), "node absent : contrôle de syntaxe JavaScript ignoré")
class JavaScriptSyntax(unittest.TestCase):
    def test_chaque_fichier_et_l_ensemble_sont_valides(self):
        files = sorted((UI / "js").glob("*.js"))
        for f in files:
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr[:300]}")
        whole = Path(tempfile.mkdtemp()) / "all.js"
        whole.write_bytes(b"".join(f.read_bytes() for f in files))
        r = subprocess.run(["node", "--check", str(whole)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[:300])


if __name__ == "__main__":
    unittest.main()
