"""Audit : secrets au repos et dans les journaux. Permissions des fichiers, aucune valeur secrète dans les journaux, les réponses ni les erreurs."""
import json, os, stat, unittest
from pathlib import Path
from hubtest.harness import ADMIN_PW, Http, TestHub

COOKIES = "c_user=100099887; xs=SECRETXS%3Avaleur-secrete%3A2; datr=SECRETDATR123; fr=SECRETFR456"
SECRETS = ["SECRETXS", "valeur-secrete", "SECRETDATR123", "SECRETFR456", ADMIN_PW, "Alice-motdepasse-1"]


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class Secrets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()
        cls.admin = cls.hub.admin()
        cls.admin.post("/api/users/create", {"name": "alice", "password": "Alice-motdepasse-1"})
        Http(cls.hub.base).login("alice", "Alice-motdepasse-1")
        Http(cls.hub.base).login("alice", "mauvais-mot-de-passe-xx")                                  # un échec : il est journalisé
        cls.code = cls.admin.post("/api/accounts/ext_code")[3]["code"]
        cls.imp = Http(cls.hub.base).post("/api/accounts/import_ext", {"code": cls.code, "cookies": COOKIES})
        cls.resp = {"import": cls.imp[2].decode()}
        cls.admin.post("/api/accounts/import_curl", {"curl": "curl 'https://www.messenger.com' -H 'cookie: " + COOKIES + "'"})
        cls.hub.wait(lambda: False, timeout=2)
        cls.name = cls.imp[3].get("name")

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_le_compte_a_bien_ete_cree(self):
        self.assertTrue(self.imp[3].get("ok"), self.imp[3])

    def test_permissions_des_fichiers_secrets(self):
        acc = self.hub.data / "acc" / self.name
        self.assertEqual(oct(mode(acc)), "0o700", "dossier du compte")
        self.assertEqual(oct(mode(acc / "cookies.json")), "0o600")
        for f in ("users.json", "sessions.json", "hub.db", "accounts.json"):
            p = self.hub.data / f
            if p.exists():
                self.assertEqual(mode(p) & 0o077, 0, f"{f} lisible par d'autres : {oct(mode(p))}")
        for p in self.hub.data.rglob("*"):
            if p.is_file() and p.name != "ops.jsonl":
                self.assertEqual(mode(p) & 0o007, 0, f"{p.relative_to(self.hub.data)} accessible à tous : {oct(mode(p))}")

    def test_aucun_secret_dans_les_journaux_du_hub(self):
        log = (self.hub.tmp / "hub.out").read_text(errors="replace")
        for s in SECRETS:
            self.assertNotIn(s, log, f"la valeur « {s[:12]}… » apparaît dans le journal du processus")
        state = self.admin.get("/api/state")[2].decode()
        for s in SECRETS:
            self.assertNotIn(s, state, f"« {s[:12]}… » apparaît dans le journal exposé par l'API")

    def test_aucun_secret_dans_les_fichiers_de_donnees_hors_cookies(self):
        for p in self.hub.data.rglob("*"):
            if p.is_file() and p.name not in ("cookies.json",):
                raw = p.read_bytes()
                for s in (b"SECRETXS", b"SECRETDATR123", b"valeur-secrete", ADMIN_PW.encode(), b"Alice-motdepasse-1"):
                    self.assertNotIn(s, raw, f"secret en clair dans {p.relative_to(self.hub.data)}")

    def test_mots_de_passe_jamais_en_clair_et_hachage_lent(self):
        users = json.loads((self.hub.data / "users.json").read_text())["users"]
        self.assertNotIn("Alice-motdepasse-1", json.dumps(users))
        for name, u in users.items():
            self.assertGreaterEqual(len(u["hash"]), 64, name)                                          # scrypt 32 octets
            self.assertGreaterEqual(len(u["salt"]), 32, name)                                          # sel de 16 octets
        salts = [u["salt"] for u in users.values()]
        self.assertEqual(len(set(salts)), len(salts), "sel réutilisé entre utilisateurs")

    def test_erreurs_sans_trace_ni_chemin_interne(self):
        for path, body in (("/api/send", {"key": "x:1"}), ("/api/chat/settings", {"key": "zz", "delay_s": "oups"}), ("/api/draft", {"id": {}}), ("/api/chat/add", {"id": [1]}),
                           ("/api/users/create", {"name": 5, "password": None}), ("/api/settings", [1]), ("/api/accounts/import_curl", {"curl": 12})):
            st, _, raw, _ = self.admin.req("POST", path, body, timeout=8)
            text = raw.decode(errors="replace")
            for banned in ("Traceback", "File \"", "/Users/", "/opt/", "hub.py", "relais/", "sqlite3.", "KeyError", "TypeError", "line "):
                self.assertNotIn(banned, text, f"{path} laisse échapper « {banned} » : {text[:150]}")

    def test_pages_d_erreur_http_sans_version_ni_chemin(self):
        h = Http(self.hub.base)
        for path in ("/inexistant", "/api/inexistant", "/%00", "/media/zz"):
            st, hd, raw, _ = h.get(path)
            self.assertNotIn("Python", hd.get("Server", "")); self.assertNotIn(b"Traceback", raw); self.assertNotIn(b"/Users/", raw)
        self.assertNotIn("BaseHTTP", Http(self.hub.base).get("/healthz")[1].get("Server", ""))


if __name__ == "__main__":
    unittest.main()
