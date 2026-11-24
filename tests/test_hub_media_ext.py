"""Médias (isolation, types sûrs, Range), avatars (liste blanche d'hôtes) et connexion par extension (code à usage unique)."""
import hashlib, unittest
from hubtest.harness import Http, TestHub

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
AID_PNG, AID_SVG = "a" * 24, "b" * 24
PW_A, PW_B = "Alice-motdepasse-1", "Bob--motdepasse-2"


class MediaAndAvatars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(accounts={"a1": "alice", "b1": "bob"}).start()
        admin = cls.hub.admin()
        for n, pw, acct in (("alice", PW_A, "a1"), ("bob", PW_B, "b1")):
            admin.post("/api/users/create", {"name": n, "password": pw})
            admin.post("/api/users/assign", {"name": n, "account": acct})
        cls.ka = cls.hub.add_chat("a1", 11, "Léa")
        cls.alice, cls.bob = Http(cls.hub.base), Http(cls.hub.base)
        cls.alice.login("alice", PW_A); cls.bob.login("bob", PW_B)
        media = cls.hub.acct_dir("a1") / "media"; media.mkdir(exist_ok=True)
        for aid, blob, mime in ((AID_PNG, PNG, "image/png"), (AID_SVG, SVG, "image/svg+xml")):
            (media / aid).write_bytes(blob)
            cls.hub.run_sql("INSERT INTO attachments(id,account,chat_key,msg_id,idx,kind,name,mime,size,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (aid, "a1", cls.ka, "m1", 0, "image", "photo", mime, len(blob), "classic"))

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def test_proprietaire_lit_son_media(self):
        st, hd, raw, _ = self.alice.get(f"/media/{AID_PNG}")
        self.assertEqual(st, 200)
        self.assertEqual(hd.get("Content-Type"), "image/png")
        self.assertEqual(raw, PNG)
        self.assertEqual(hd.get("X-Content-Type-Options"), "nosniff")

    def test_media_d_autrui_et_anonyme_refuses(self):
        self.assertEqual(self.bob.get(f"/media/{AID_PNG}")[0], 404)                          # un autre utilisateur ne distingue pas « absent » de « interdit »
        self.assertEqual(Http(self.hub.base).get(f"/media/{AID_PNG}")[0], 401)
        self.assertEqual(self.hub.admin().get(f"/media/{AID_PNG}")[0], 404)                  # l'administrateur non plus

    def test_identifiant_invalide(self):
        for aid in ("../../etc/passwd", "zz", "A" * 24, "a" * 23):
            self.assertEqual(self.alice.get(f"/media/{aid}")[0], 404, aid)

    def test_svg_jamais_affiche_dans_la_page(self):
        st, hd, raw, _ = self.alice.get(f"/media/{AID_SVG}")
        self.assertEqual(st, 200)
        self.assertNotIn("svg", hd.get("Content-Type", "").lower())                          # le type annoncé n'est jamais cru : seul le contenu reconnu compte
        self.assertIn("attachment", hd.get("Content-Disposition", ""))                       # téléchargement forcé, jamais d'exécution

    def test_requete_partielle_range(self):
        st, hd, raw, _ = self.alice.get(f"/media/{AID_PNG}", headers={"Range": "bytes=0-9"})
        self.assertEqual(st, 206)
        self.assertEqual(raw, PNG[:10])
        self.assertTrue(hd.get("Content-Range", "").startswith("bytes 0-9/"))

    def test_avatar_hote_non_autorise_refuse(self):
        self.hub.run_sql("UPDATE chats SET pic=? WHERE key=?", ("https://evil.example/photo.jpg", self.ka))
        self.assertEqual(self.alice.get(f"/api/avatar?key={self.ka}")[0], 404)               # aucune requête sortante vers un hôte arbitraire (SSRF)
        self.hub.run_sql("UPDATE chats SET pic=? WHERE key=?", ("http://scontent.fbcdn.net/p.jpg", self.ka))
        self.assertEqual(self.alice.get(f"/api/avatar?key={self.ka}")[0], 404)               # http (non chiffré) refusé

    def test_avatar_en_cache_et_isolation(self):
        url = "https://scontent.fbcdn.net/photo-test.jpg"
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 40
        (self.hub.data / "avatars").mkdir(exist_ok=True)
        (self.hub.data / "avatars" / (hashlib.sha1(url.encode()).hexdigest() + ".img")).write_bytes(jpeg)
        self.hub.run_sql("UPDATE chats SET pic=? WHERE key=?", (url, self.ka))
        st, hd, raw, _ = self.alice.get(f"/api/avatar?key={self.ka}")
        self.assertEqual((st, raw, hd.get("Content-Type")), (200, jpeg, "image/jpeg"))
        self.assertEqual(self.bob.get(f"/api/avatar?key={self.ka}")[0], 404)                 # la photo d'un contact d'autrui reste privée


class ExtensionConnect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub().start()
        cls.admin = cls.hub.admin()

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    COOKIES = "c_user=100012345; xs=aaaa%3Abbbb%3A2; datr=cccc; fr=dddd"

    def test_code_requiert_une_session(self):
        self.assertIn(Http(self.hub.base).post("/api/accounts/ext_code")[0], (401, 403))
        js = self.admin.post("/api/accounts/ext_code")[3]
        self.assertTrue(js.get("code") and len(js["code"]) >= 20, js)

    def test_import_sans_code_valide_refuse(self):
        js = Http(self.hub.base).post("/api/accounts/import_ext", {"code": "faux", "cookies": self.COOKIES})[3]
        self.assertIn("expiré", js.get("error", ""))
        self.assertEqual(Http(self.hub.base).post("/api/accounts/import_ext", {"cookies": self.COOKIES})[3].get("error") is not None, True)

    def test_import_cree_le_compte_pour_l_emetteur_du_code_usage_unique(self):
        code = self.admin.post("/api/accounts/ext_code")[3]["code"]
        anon = Http(self.hub.base)                                                           # l'extension n'a pas de session du hub : le code prouve l'émetteur
        js = anon.post("/api/accounts/import_ext", {"code": code, "cookies": self.COOKIES})[3]
        self.assertTrue(js.get("ok"), js)
        name = js["name"]
        state = self.admin.get("/api/state")[3]
        self.assertIn(name, {a["name"] for a in state["accounts"]})
        cj = self.hub.data / "acc" / name / "cookies.json"
        self.assertTrue(cj.exists())
        self.assertEqual(oct(cj.stat().st_mode & 0o777), "0o600")                            # secret : lisible par le seul processus
        js2 = Http(self.hub.base).post("/api/accounts/import_ext", {"code": code, "cookies": self.COOKIES})[3]
        self.assertTrue(js2.get("error"))                                                    # le code est consommé

    def test_cookies_sans_session_messenger_refuses(self):
        code = self.admin.post("/api/accounts/ext_code")[3]["code"]
        js = Http(self.hub.base).post("/api/accounts/import_ext", {"code": code, "cookies": "foo=bar"})[3]
        self.assertTrue(js.get("error"))
        js = Http(self.hub.base).post("/api/accounts/import_ext", {"code": code, "cookies": self.COOKIES})[3]
        self.assertTrue(js.get("ok"), "le code reste valable après un échec")


if __name__ == "__main__":
    unittest.main()
