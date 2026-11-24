"""Audit : requêtes malformées ou hostiles envoyées directement au hub (sans proxy) : le hub doit répondre vite, proprement, et rester debout."""
import json, socket, threading, time, unittest
from hubtest.harness import ADMIN_PW, Http, TestHub, raw_http


def post(path, headers, body=b"", extra=""):
    h = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Hub: 1\r\nContent-Type: application/json\r\n{headers}{extra}\r\n"
    return h.encode() + body


class Hostile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()
        cls.admin = cls.hub.admin()      # session ouverte AVANT les attaques : elles bloquent l'adresse locale pour les connexions

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def alive(self):
        return Http(self.hub.base).get("/healthz")[0] == 200

    def status(self, out):
        """Code HTTP ; 0 si le hub a coupé la connexion d'emblée (refus immédiat d'un corps trop grand)."""
        return 0 if out == b"RESET" else int(out.split(b" ", 2)[1]) if out else None

    # ---- longueur du contenu
    def test_content_length_negatif_ou_non_numerique_rejete_vite(self):
        for cl in ("-1", "-9999999999", "abc", "1e9", " ", "0x10", "1, 2"):
            out, dt = raw_http(self.hub.port, post("/api/login", f"Content-Length: {cl}\r\n"))
            with self.subTest(content_length=cl):
                self.assertIsNotNone(out, f"aucune réponse (connexion retenue {dt:.1f}s)")
                self.assertIn(self.status(out), (400, 401) if cl.strip() == "" else (400,))        # un en-tête vide vaut « pas de corps »
                self.assertLess(dt, 3, f"réponse après {dt:.1f}s : le fil d'exécution est retenu")
        self.assertTrue(self.alive())

    def test_corps_annonce_enorme_refuse_sans_attendre_les_octets(self):
        for cl in (str(2_000_001), str(10**9), str(10**15), "9" * 30):
            out, dt = raw_http(self.hub.port, post("/api/login", f"Content-Length: {cl}\r\n", b'{"username":"a"}'))
            with self.subTest(content_length=cl):
                self.assertIsNotNone(out, f"aucune réponse (connexion retenue {dt:.1f}s)")
                self.assertIn(self.status(out), (0, 400, 413))
                self.assertLess(dt, 3)

    def test_corps_plus_court_que_annonce_ferme_par_le_delai(self):
        out, dt = raw_http(self.hub.port, post("/api/login", "Content-Length: 500\r\n", b'{"a":1}'), timeout=20)
        self.assertLess(dt, 16, "la connexion à corps incomplet n'est pas fermée par le délai")
        self.assertTrue(self.alive())

    # ---- JSON hostile
    def test_json_hostile_ne_fait_pas_tomber_le_hub(self):
        bombs = [b"[" * 200000, b'{"a":' * 50000, b"9" * 100000, b'{"username":"' + b"A" * 1_500_000 + b'"}', b"\xff\xfe\x00", b'{"username": NaN}', b'{"username":"a","password":' + b"[" * 1000 + b"]" * 1000 + b"}",
                 b'{"username":"\\ud800"}', b"null", b"[]", b"1", b'"x"', b"true"]
        for body in bombs:
            out, dt = raw_http(self.hub.port, post("/api/login", f"Content-Length: {len(body)}\r\n", body), timeout=10)
            with self.subTest(taille=len(body), debut=body[:20]):
                self.assertIsNotNone(out, "aucune réponse")
                self.assertIn(self.status(out), (0, 400, 401, 413, 429, 500))
                self.assertNotIn(b"Traceback", out); self.assertNotIn(b"/Users/", out); self.assertNotIn(b"hub.py", out)
        self.assertTrue(self.alive())

    def test_json_hostile_apres_connexion(self):
        h = self.admin
        for path in ("/api/send", "/api/chat/settings", "/api/settings", "/api/draft", "/api/chat/add", "/api/users/create", "/api/me/password"):
            for body in ([], "texte", 1, None, [{"a": 1}], {"key": None}, {"id": 10**400 if False else 10**30}, {"key": {"a": {"b": [1] * 50}}}, {"text": "x" * 500_000, "key": "a:1"}):
                st, _, raw, _ = h.req("POST", path, body, timeout=8)
                with self.subTest(path=path, body=str(body)[:40]):
                    self.assertIn(st, (200, 400, 413, 500))
                    self.assertNotIn(b"Traceback", raw); self.assertNotIn(b"File \"", raw)
        self.assertTrue(self.alive())

    # ---- ligne de requête et en-têtes
    def test_requete_malformee(self):
        cases = {"URI trop longue": b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
                 "en-tête géant": b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nX: " + b"a" * 70000 + b"\r\n\r\n",
                 "trop d'en-têtes": b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n" + b"".join(b"X%d: a\r\n" % i for i in range(500)) + b"\r\n",
                 "méthode inconnue": b"BREW / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", "HTTP/9": b"GET / HTTP/9.9\r\nHost: 127.0.0.1\r\n\r\n",
                 "octets nuls": b"GET /\x00admin HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", "retours à la ligne dans le chemin": b"GET /%0d%0aSet-Cookie:%20a=b HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
                 "Host en double": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: evil.example\r\n\r\n", "Host vide": b"GET /api/state HTTP/1.1\r\nHost:\r\n\r\n",
                 "Transfer-Encoding": b"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Hub: 1\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nabcde\r\n0\r\n\r\n"}
        for name, data in cases.items():
            out, dt = raw_http(self.hub.port, data, timeout=8)
            with self.subTest(cas=name):
                if out is not None:
                    self.assertNotIn(b"Set-Cookie: a=b", out)
                    self.assertNotIn(b"Traceback", out)
                self.assertLess(dt, 9)
        self.assertTrue(self.alive())

    def test_injection_d_en_tetes_dans_les_reponses(self):
        """Une valeur contrôlée par le client ne doit jamais se retrouver dans un en-tête de réponse."""
        st, hd, _, _ = Http(self.hub.base).get("/login?next=%0d%0aX-Evil:%201", headers={"X-Evil": "1\r\nX-Injected: 1"} if False else None)
        self.assertIsNone(hd.get("X-Evil")); self.assertIsNone(hd.get("X-Injected"))

    # ---- ressources
    def test_beaucoup_de_connexions_lentes_n_empechent_pas_de_servir(self):
        socks = []
        try:
            for _ in range(150):
                s = socket.create_connection(("127.0.0.1", self.hub.port), timeout=3); s.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n"); socks.append(s)    # en-têtes jamais terminés
            t0 = time.time(); st = Http(self.hub.base).get("/healthz")[0]
            self.assertEqual(st, 200); self.assertLess(time.time() - t0, 5, "le hub est ralenti par 150 connexions lentes")
        finally:
            for s in socks:
                s.close()

    def test_rafale_de_requetes_authentifiees_non_bloquante(self):
        h = self.admin; t0 = time.time()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(20) as ex:
            codes = list(ex.map(lambda _: h.get("/api/state", timeout=10)[0], range(200)))
        self.assertTrue(all(c == 200 for c in codes)); self.assertLess(time.time() - t0, 30)


if __name__ == "__main__":
    unittest.main()


class HostHeader(unittest.TestCase):
    """L'en-tête Host est contrôlé par le client : il ne doit jamais pouvoir injecter quoi que ce soit dans le paquet d'extension généré."""
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()
        cls.cookie = cls.hub.admin().cookie

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def zip_with_host(self, host):
        data = f"GET /relais-connect.zip HTTP/1.1\r\nHost: {host}\r\nCookie: {self.cookie}\r\n\r\n".encode()
        out, _ = raw_http(self.hub.port, data, timeout=8, read=1_000_000)
        return out

    def test_host_piege_ne_s_injecte_pas_dans_le_manifeste(self):
        import io, zipfile
        for host in ('localhost:1","evil":"x', 'localhost:1"],"permissions":["<all_urls>"],"x":["', "127.0.0.1:8787/../../x", "localhost:80\\u0022", "localhost:1<script>", "localhost:", "localhost:99999999",
                     "localhost:80 evil.example", "localhost@evil.example", "[::1]:80\"x", "localhost:8787\r\nX-Evil: 1"):
            out = self.zip_with_host(host)
            with self.subTest(host=host):
                if out is None or out == b"RESET" or not out.startswith(b"HTTP/1.") or b" 200 " in out.split(b"\r\n", 1)[0] is False:
                    continue
                status = int(out.split(b" ", 2)[1])
                if status != 200:
                    continue                                                  # refusé : parfait
                body = out.split(b"\r\n\r\n", 1)[1]
                z = zipfile.ZipFile(io.BytesIO(body))
                manifest = json.loads(z.read("relais-connect/manifest.json"))
                self.assertEqual(set(manifest) & {"evil", "x"}, set(), "clé injectée dans le manifeste")
                self.assertNotIn("<all_urls>", json.dumps(manifest["permissions"]), "permission injectée")
                for hp in manifest["host_permissions"]:
                    self.assertRegex(hp, r"^https?://[a-z0-9.\[\]:*-]+/\*$", f"host_permissions suspect : {hp}")
                cfg = z.read("relais-connect/config.js").decode()
                self.assertNotIn("evil", cfg)

    def test_host_malforme_refuse_partout(self):
        for host in ('localhost:1"', "localhost:abc", "local host", "localhost:99999999", "localhost:80:80", "localhost\\", "[::1]x", ""):
            out, _ = raw_http(self.hub.port, f"GET /login HTTP/1.1\r\nHost: {host}\r\n\r\n".encode(), timeout=8)
            with self.subTest(host=host):
                self.assertIn(self.status(out) if out else 0, (0, 400, 403), f"Host malformé accepté : {host!r}")

    def status(self, out):
        return 0 if out == b"RESET" else int(out.split(b" ", 2)[1]) if out else None
