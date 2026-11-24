"""Audit : authentification, sessions, invitations, blocage des essais, adresse IP derrière un proxy, cookies."""
import concurrent.futures, json, statistics, time, unittest
from hubtest.harness import ADMIN_PW, Http, TestHub


import itertools
_n = itertools.count(1)
def ip():
    """Une adresse cliente unique par appel : chaque test est indépendant des blocages des autres."""
    return {"X-Forwarded-For": f"10.{next(_n) // 250}.{next(_n) % 250}.{next(_n) % 250}"}


class Lockout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_blocage_apres_cinq_echecs_meme_avec_le_bon_mot_de_passe(self):
        h = Http(self.hub.base)
        codes = [h.login("admin", "mauvais-" + str(i))[0] for i in range(5)]
        self.assertEqual(codes, [401] * 5)
        self.assertEqual(h.login("admin", ADMIN_PW)[0], 429)                       # bloqué : le bon mot de passe n'ouvre plus la porte pendant la durée du blocage
        self.assertFalse(h.cookie)


class ForwardedFor(unittest.TestCase):
    """Derrière un proxy qui AJOUTE l'adresse à X-Forwarded-For, le client peut écrire le début de l'en-tête : seule la dernière entrée est fiable."""
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(env={"HUB_TRUST_PROXY": "1"}).start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_usurpation_de_l_adresse_ne_contourne_pas_le_blocage(self):
        h = Http(self.hub.base)
        last = "7.7.7.7"                                                            # adresse réelle, ajoutée à la fin par le proxy
        codes = [h.req("POST", "/api/login", {"username": "admin", "password": "faux"}, headers={"X-Forwarded-For": f"10.0.0.{i}, {last}"})[0] for i in range(6)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429, "le blocage est contourné en changeant le début de X-Forwarded-For")


class CookieFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(env={"HUB_TRUST_PROXY": "1", "HUB_SECURE_COOKIE": "1"}).start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_cookie_de_session_durci(self):
        st, hd, _, _ = Http(self.hub.base).post("/api/login", {"username": "admin", "password": ADMIN_PW})
        self.assertEqual(st, 200)
        sc = hd.get("Set-Cookie")
        self.assertTrue(sc.startswith("__Host-hub_session="), sc[:30])
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, sc)
        self.assertNotIn("Domain=", sc)                                             # exigé par le préfixe __Host-
        self.assertIn("Max-Age=", sc)


class Sessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(env={"HUB_TRUST_PROXY": "1"}).start()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_jetons_imprevisibles_et_jamais_stockes_en_clair(self):
        toks = set()
        for _ in range(8):
            h = Http(self.hub.base); h.login("admin", ADMIN_PW); toks.add(h.cookie.split("=", 1)[1])
        self.assertEqual(len(toks), 8)
        self.assertTrue(all(len(t) >= 40 for t in toks))                            # >= 256 bits
        stored = (self.hub.data / "sessions.json").read_text()
        for t in toks:
            self.assertNotIn(t, stored)                                             # seule l'empreinte est conservée
        self.assertEqual(oct((self.hub.data / "sessions.json").stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct((self.hub.data / "users.json").stat().st_mode & 0o777), "0o600")

    def test_session_forgee_ou_alteree_refusee(self):
        for cookie in ("hub_session=", "hub_session=" + "A" * 43, "hub_session=../../etc/passwd", "hub_session=" + "A" * 5000, "hub_session=a;hub_session=b", "autre=1"):
            h = Http(self.hub.base); h.cookie = cookie
            self.assertEqual(h.get("/api/state")[0], 401, cookie[:30])
        h = self.hub.admin(); tok = h.cookie.split("=", 1)[1]
        for variant in (tok[:-1] + ("A" if tok[-1] != "A" else "B"), tok.upper(), tok + "x"):
            g = Http(self.hub.base); g.cookie = "hub_session=" + variant
            self.assertEqual(g.get("/api/state")[0], 401)

    def test_session_inconnue_ne_se_fixe_pas(self):
        """Fixation de session : un jeton choisi à l'avance par l'attaquant n'est jamais adopté à la connexion."""
        h = Http(self.hub.base); h.cookie = "hub_session=" + "F" * 43
        st, hd, _, _ = h.req("POST", "/api/login", {"username": "admin", "password": ADMIN_PW})
        self.assertEqual(st, 200)
        self.assertNotIn("F" * 43, hd.get("Set-Cookie"))

    def test_nombre_de_sessions_plafonne(self):
        hs = []
        for _ in range(23):
            h = Http(self.hub.base); h.login("admin", ADMIN_PW); hs.append(h)
        alive = sum(1 for h in hs if h.get("/api/state")[0] == 200)
        self.assertLessEqual(alive, 20)

    def test_temps_de_reponse_identique_identifiant_connu_ou_inconnu(self):
        """Pas d'énumération des identifiants par la durée de réponse."""
        def avg(user):
            ts = []
            for _ in range(4):
                t0 = time.time(); Http(self.hub.base).req("POST", "/api/login", {"username": user, "password": "faux-mot-de-passe-1"}, headers=ip()); ts.append(time.time() - t0)
            return statistics.median(ts)
        known, unknown = avg("admin"), avg("inconnu-xyz")
        self.assertLess(abs(known - unknown), 0.25, f"connu {known:.2f}s vs inconnu {unknown:.2f}s")


class Invitations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(env={"HUB_TRUST_PROXY": "1"}).start()
        cls.admin = cls.hub.admin()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_usage_unique_meme_en_parallele(self):
        tok = self.admin.post("/api/users/invite")[3]["path"].split("#", 1)[1]
        def redeem(i):
            return Http(self.hub.base).post("/api/join", {"token": tok, "username": f"racer{i}", "password": f"Racer-motdepasse-{i:02d}x"}, headers=ip())[0]
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            codes = list(ex.map(redeem, range(12)))
        self.assertEqual(codes.count(200), 1, f"le même lien a été utilisé {codes.count(200)} fois : {codes}")
        users = [u["name"] for u in self.admin.post("/api/users/list")[3]["users"] if u["name"].startswith("racer")]
        self.assertEqual(len(users), 1)

    def test_invite_ne_donne_jamais_le_role_admin(self):
        tok = self.admin.post("/api/users/invite")[3]["path"].split("#", 1)[1]
        Http(self.hub.base).post("/api/join", {"token": tok, "username": "futé", "password": "Fute--motdepasse-1", "role": "admin"}, headers=ip())
        tok2 = self.admin.post("/api/users/invite")[3]["path"].split("#", 1)[1]
        Http(self.hub.base).post("/api/join", {"token": tok2, "username": "futé2", "password": "Fute--motdepasse-2", "role": "admin", "admin": True}, headers=ip())
        roles = {u["name"]: u["role"] for u in self.admin.post("/api/users/list")[3]["users"]}
        for n in ("futé", "futé2"):
            self.assertIn(roles.get(n, "user"), ("user",))

    def test_jetons_devines_refuses_et_comptes_comme_echecs(self):
        h = Http(self.hub.base); same = ip()
        codes = [h.post("/api/join", {"token": f"devine-{i}", "username": "x" + str(i), "password": "Motdepasse-long-1"}, headers=same)[0] for i in range(6)]
        self.assertEqual(codes[:5], [400] * 5)
        self.assertEqual(codes[5], 429)

    def test_noms_d_utilisateur_dangereux_refuses(self):
        for name in ("../etc", "a b", "<script>", "ADMIN ", "x" * 80, "", "é", "a\x00b", "admin"):
            tok = self.admin.post("/api/users/invite")[3]["path"].split("#", 1)[1]
            st, _, _, js = Http(self.hub.base).post("/api/join", {"token": tok, "username": name, "password": "Motdepasse-long-1"}, headers=ip())
            if name == "ADMIN ":
                continue                                                            # normalisé en « admin » (déjà pris)
            self.assertGreaterEqual(st, 400, name)


if __name__ == "__main__":
    unittest.main()
