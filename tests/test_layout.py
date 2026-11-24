"""Organisation du dépôt : les chemins dont dépendent Docker, le hub, les outils et la documentation existent."""
import os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

os.environ.setdefault("HUB_DATA", tempfile.mkdtemp(prefix="relais-layout-"))      # l'import de la configuration crée des dossiers : on les isole
from hubtest.imp import HUB_DIR  # noqa: E402

ROOT = Path(HUB_DIR).parent
# ce qui n'est pas dans git mais que le Dockerfile attend (construit avant l'image)
BUILD_ARTIFACTS = {"dist/relais.apk"}


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return set(out.split("\n")) - {""}


class Docker(unittest.TestCase):
    def copy_sources(self):
        return [m.group(1) for m in re.finditer(r"^COPY (?!--from)(\S+) \S+", (ROOT / "Dockerfile").read_text(), re.M)]

    def test_sources_du_dockerfile_existent(self):
        for src in self.copy_sources():
            if src.rstrip("/") in BUILD_ARTIFACTS:
                continue
            self.assertTrue((ROOT / src).exists(), f"COPY {src} : introuvable")

    def test_dockerignore_n_exclut_aucune_source_copiee(self):
        ignored = {l.strip().lstrip("/").rstrip("/") for l in (ROOT / ".dockerignore").read_text().splitlines() if l.strip() and not l.startswith("#")}
        for src in self.copy_sources():
            top = src.rstrip("/").split("/")[0]
            self.assertNotIn(top, ignored, f"{top} est copié par le Dockerfile mais exclu par .dockerignore")
            self.assertNotIn(src.rstrip("/"), ignored, src)

    def test_fichiers_du_compose_existent(self):
        for ref in re.findall(r"\./([\w./-]+):", (ROOT / "docker-compose.yml").read_text()):
            self.assertTrue((ROOT / ref).exists(), ref)

    def test_construction_du_client_go_pointe_vers_cmd(self):
        self.assertIn("./cmd/messenger-lite", (ROOT / "Dockerfile").read_text())
        self.assertTrue((ROOT / "cmd" / "messenger-lite" / "main.go").exists())


class HubPaths(unittest.TestCase):
    def test_chemins_de_la_configuration(self):
        from relais import config
        self.assertEqual(config.HERE, ROOT / "hub")
        self.assertTrue(config.LOGIN_SCRIPT.exists(), config.LOGIN_SCRIPT)
        self.assertTrue(config.EXT_DIR.is_dir() and (config.EXT_DIR / "manifest.template.json").exists())
        self.assertTrue((config.HERE / "ui" / "index.html").exists())
        self.assertEqual(config.ACCOUNTS_ROOT.name, "accounts") if "HUB_ACCOUNTS_ROOT" not in os.environ else None

    def test_binaire_client_prefere_bin_puis_la_racine(self):
        from relais import config
        d = Path(tempfile.mkdtemp())
        (d / "hub").mkdir()
        orig = config.HERE
        try:
            config.HERE = d / "hub"
            self.assertEqual(config._default_client_bin(), str(d / "bin" / "messenger-lite"))          # rien : emplacement par défaut
            (d / "messenger-lite").write_text("x")
            self.assertEqual(config._default_client_bin(), str(d / "messenger-lite"))                  # ancien emplacement toléré
            (d / "bin").mkdir(); (d / "bin" / "messenger-lite").write_text("x")
            self.assertEqual(config._default_client_bin(), str(d / "bin" / "messenger-lite"))          # bin/ a priorité
        finally:
            config.HERE = orig


class Tools(unittest.TestCase):
    def test_import_cookies_ecrit_dans_accounts_a_la_racine(self):
        """Le script a changé de dossier : il doit toujours écrire dans <racine>/accounts/ (et non dans tools/accounts/)."""
        d = Path(tempfile.mkdtemp())
        (d / "tools").mkdir()
        shutil.copy(ROOT / "tools" / "import_cookies.py", d / "tools" / "import_cookies.py")
        env = {k: v for k, v in os.environ.items() if k != "HUB_ACCOUNTS_ROOT"}
        r = subprocess.run([sys.executable, str(d / "tools" / "import_cookies.py"), "demo"], input="c_user=100012345; xs=aaaa%3Abbbb; datr=cccc\n",
                           capture_output=True, text=True, env=env, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = d / "accounts" / "demo" / "cookies.json"
        self.assertTrue(out.exists(), "écrit au mauvais endroit")
        self.assertFalse((d / "tools" / "accounts").exists())
        self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")
        self.assertNotIn("aaaa", r.stdout + r.stderr)                                                  # les valeurs ne sont jamais affichées


class Documentation(unittest.TestCase):
    def test_liens_relatifs_existent(self):
        for md in ("README.md", "deploy/README.md", "docs/multiuser.md", "tests/README.md", "hub/ui/README.md"):
            path = ROOT / md
            text = path.read_text(encoding="utf-8")
            refs = re.findall(r'\]\(([^)#\s]+)\)|(?:src|href)="([^"#]+)"', text)
            for a, b in refs:
                ref = a or b
                if re.match(r"[a-z]+:", ref) or ref.startswith("#"):
                    continue
                self.assertTrue((path.parent / ref).exists(), f"{md} : lien cassé → {ref}")

    def test_racine_rangee(self):
        """Seuls les fichiers standards restent à la racine (le reste vit dans un dossier)."""
        top_files = {p for p in tracked() if "/" not in p}
        self.assertEqual(top_files, {".dockerignore", ".gitignore", "Dockerfile", "LICENSE", "README.md", "docker-compose.yml", "go.mod", "go.sum"})


if __name__ == "__main__":
    unittest.main()
