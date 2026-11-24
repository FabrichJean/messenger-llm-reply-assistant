"""Surface HTTP du hub : pages publiques, authentification, CSRF, en-têtes de sécurité, CSP."""
import base64, hashlib, re, unittest
from hubtest.harness import ADMIN_PW, Http, TestHub


class HubHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def anon(self):
        return Http(self.hub.base)

    # --- pages publiques
    def test_healthz(self):
        st, _, raw, _ = self.anon().get("/healthz")
        self.assertEqual(st, 200)

    def test_landing_publique(self):
        st, _, raw, _ = self.anon().get("/")
        self.assertEqual(st, 200)
        self.assertIn(b'data-public="1"', raw)            # la landing n'embarque aucune donnée privée
        self.assertIn(b"Relais", raw)

    def test_login_et_join(self):
        for p in ("/login", "/join"):
            st, _, raw, _ = self.anon().get(p)
            self.assertEqual(st, 200, p)
            self.assertIn(b"<html", raw.lower())

    # --- API protégée
    def test_api_sans_session_refusee(self):
        for p in ("/api/state", "/api/stats", "/api/chat?key=x:1", "/relais.apk"):
            st, *_ = self.anon().get(p)
            self.assertEqual(st, 401, p)

    def test_post_sans_session_refuse(self):
        st, *_ = self.anon().post("/api/send", {"key": "x:1", "text": "salut"})
        self.assertIn(st, (401, 403))

    def test_login_mauvais_mot_de_passe(self):
        h = self.anon()
        st, js = h.login("admin", "mauvais-mot-de-passe")
        self.assertEqual(st, 401)
        self.assertFalse(h.cookie)

    def test_login_ok_pose_un_cookie_http_only(self):
        h = self.anon()
        st, hd, raw, js = h.post("/api/login", {"username": "admin", "password": ADMIN_PW})
        self.assertEqual(st, 200)
        sc = hd.get("Set-Cookie")
        self.assertIn("hub_session=", sc)
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)
        st, *_, js = h.get("/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(js["me"]["name"], "admin")
        self.assertEqual(js["me"]["role"], "admin")

    def test_logout_ferme_la_session(self):
        h = self.hub.admin()
        self.assertEqual(h.get("/api/state")[0], 200)
        h.post("/api/logout")
        self.assertEqual(h.get("/api/state")[0], 401)

    def test_csrf_post_sans_entete_refuse(self):
        h = self.hub.admin()
        st, *_ = h.post("/api/settings", {"k": "x"}, csrf=False)
        self.assertEqual(st, 403)

    def test_hote_inconnu_refuse(self):
        """Protection contre le rebinding DNS : un en-tête Host inconnu est refusé (sauf /healthz, sonde Docker sans donnée)."""
        for p in ("/", "/login", "/api/state"):
            st, *_ = self.anon().get(p, host="evil.example")
            self.assertEqual(st, 403, p)
        st, *_ = self.anon().post("/api/login", {"username": "admin", "password": ADMIN_PW}, host="evil.example")
        self.assertEqual(st, 403)
        self.assertEqual(self.anon().get("/healthz", host="evil.example")[0], 200)

    # --- en-têtes et CSP
    def test_en_tetes_de_securite(self):
        for p in ("/", "/login", "/join"):
            _, hd, *_ = self.anon().get(p)
            self.assertEqual(hd.get("X-Content-Type-Options"), "nosniff", p)
            self.assertIn("frame-ancestors", hd.get("Content-Security-Policy", ""), p)
            self.assertEqual(hd.get("Cache-Control"), "no-store", p) if hd.get("Cache-Control") else None

    def test_csp_autorise_exactement_les_scripts_en_ligne(self):
        """Chaque <script> en ligne doit avoir son empreinte dans la CSP (sinon la page casse), et aucun 'unsafe-inline' côté scripts."""
        h = self.hub.admin()
        for p in ("/", "/login", "/join"):
            cli = h if p == "/" else self.anon()
            st, hd, raw, _ = cli.get(p)
            csp = hd.get("Content-Security-Policy", "")
            script_src = re.search(r"script-src ([^;]*)", csp).group(1)
            self.assertNotIn("unsafe-inline", script_src, p)
            scripts = re.findall(rb"<script>(.*?)</script>", raw, re.S)
            for s in scripts:
                digest = base64.b64encode(hashlib.sha256(s).digest()).decode()
                self.assertIn(f"'sha256-{digest}'", script_src, f"{p}: script sans empreinte")

    def test_index_connecte_sans_mode_public(self):
        st, _, raw, _ = self.hub.admin().get("/")
        self.assertEqual(st, 200)
        self.assertNotIn(b'data-public="1"', raw)


if __name__ == "__main__":
    unittest.main()
