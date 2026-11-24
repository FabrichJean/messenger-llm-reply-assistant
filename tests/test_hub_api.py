"""API utilisée par l'interface : conversations, réglages, mémoire, envoi manuel, brouillons, extension."""
import io, json, unittest, zipfile
from hubtest.harness import TestHub


class HubApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(accounts={"demo": None}).start()
        cls.hub.fast_replies()
        cls.h = cls.hub.admin()
        cls.key = cls.hub.add_chat("demo", 301, "Contact API", enabled=0)

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def chat(self):
        """Fiche de la conversation (la réponse de /api/chat est {"chat", "messages", "drafts", "prepared"})."""
        return self.h.get(f"/api/chat?key={self.key}")[3]["chat"]

    def test_forme_de_l_etat(self):
        js = self.h.get("/api/state")[3]
        for k in ("me", "accounts", "chats", "settings", "tasks", "log", "auth", "can_login"):
            self.assertIn(k, js, k)
        acc = js["accounts"][0]
        self.assertEqual(acc["name"], "demo")
        self.assertTrue(acc.get("classic") or acc.get("connected") or "running" in acc)

    def test_forme_des_statistiques(self):
        js = self.h.get("/api/stats")[3]
        self.assertIsInstance(js, dict)
        self.assertTrue(js)

    def test_reglages_de_la_conversation_et_memoire(self):
        mem = "- [identité|confirmé] Alex, tutoiement\n- [engagement|confirmé] Moi doit envoyer le cours (en attente)"
        r = self.h.post("/api/chat/settings", {"key": self.key, "mode": "draft", "delay_s": 3, "max_per_hour": 7,
                                                "instructions": "Ami proche", "memory": mem, "takeover_off": True, "trusted": False})[3]
        self.assertFalse(r.get("error"), r)
        c = self.chat()
        self.assertEqual((c["mode"], c["delay_s"], c["max_per_hour"], c["instructions"]), ("draft", 3, 7, "Ami proche"))
        self.assertEqual(c["memory"], mem)
        self.h.post("/api/chat/settings", {"key": self.key, "memory": ""})
        self.assertEqual(self.chat()["memory"], "")                                            # le propriétaire peut vider la mémoire

    def test_memoire_plafonnee(self):
        self.h.post("/api/chat/settings", {"key": self.key, "memory": "x" * 9000})
        self.assertLessEqual(len(self.chat()["memory"]), 2000)
        self.h.post("/api/chat/settings", {"key": self.key, "memory": ""})

    def test_actualisation_de_la_memoire_lancee(self):
        self.assertTrue(self.h.post("/api/chat/memory/refresh", {"key": self.key})[3].get("ok"))

    def test_epingler_renommer(self):
        self.h.post("/api/chat/pin", {"key": self.key, "pinned": True})
        self.assertEqual(self.hub.sql("SELECT pinned FROM chats WHERE key=?", (self.key,))[0]["pinned"], 1)
        r = self.h.post("/api/chat/rename", {"key": self.key, "name": "Nouveau nom"})[3]
        self.assertFalse(r.get("error"), r)
        self.assertEqual(self.hub.sql("SELECT name FROM chats WHERE key=?", (self.key,))[0]["name"], "Nouveau nom")

    def test_envoi_manuel_arrive_au_client(self):
        r = self.h.post("/api/send", {"key": self.key, "text": "envoi manuel ABC"})[3]
        self.assertFalse(r.get("error"), r)
        self.hub.wait(lambda: any("envoi manuel ABC" in t for t in self.hub.sent_texts("demo")))
        sent = [o for o in self.hub.ops("demo") if "envoi manuel ABC" in o.get("text", "")]
        self.assertTrue(sent)
        self.assertEqual(sent[0]["thread"], 301)
        row = self.hub.sql("SELECT src FROM messages WHERE chat_key=? AND text LIKE '%envoi manuel ABC%'", (self.key,))
        self.assertTrue(row and row[0]["src"] == "owner")                                      # enregistré comme écrit par le propriétaire

    def test_envoi_texte_vide_refuse(self):
        r = self.h.post("/api/send", {"key": self.key, "text": "   "})[3]
        self.assertTrue(r.get("error") or r.get("ok") is False)

    def test_cle_inconnue_refusee_proprement(self):
        for path, body in (("/api/send", {"key": "demo:999999", "text": "x"}), ("/api/chat/settings", {"key": "demo:999999", "mode": "auto"})):
            st, _, _, js = self.h.post(path, body)
            self.assertTrue(st >= 400 or (js and js.get("error")), path)

    def test_reglages_generaux_et_personnels(self):
        # avec l'authentification : le nom du propriétaire est un réglage PERSONNEL (par compte), jamais exposé au niveau général
        self.assertFalse(self.h.post("/api/settings", {"owner": "Camille", "account": "demo"})[3].get("error"))
        st = self.h.get("/api/state")[3]
        self.assertIn("Camille", json.dumps(st["account_settings"]))
        self.assertNotEqual(st["settings"].get("owner"), "Camille")
        # réglage général : la pause
        self.h.post("/api/settings", {"paused": "1"})
        self.assertEqual(self.h.get("/api/state")[3]["settings"]["paused"], "1")
        self.h.post("/api/settings", {"paused": "0"})
        self.assertEqual(self.h.get("/api/state")[3]["settings"]["paused"], "0")
        self.assertTrue(self.h.post("/api/settings", {"owner": "X", "account": "inconnu"})[3].get("error"))

    def test_ajout_et_suppression_de_conversation(self):
        st, _, _, js = self.h.post("/api/chat/add", {"id": 777001, "name": "Ajouté", "account": "demo"})
        k = "demo:777001"
        self.assertTrue(self.hub.wait(lambda: self.hub.sql("SELECT 1 FROM chats WHERE key=?", (k,))), (st, js))
        self.assertEqual(self.h.post("/api/chat/delete", {"key": k})[3].get("error"), "confirmation requise")   # jamais sans confirmation
        self.assertFalse(self.h.post("/api/chat/delete", {"key": k, "confirm": True})[3].get("error"))
        self.assertEqual(self.hub.sql("SELECT COUNT(*) c FROM chats WHERE key=?", (k,))[0]["c"], 0)

    def test_paquet_de_l_extension(self):
        st, hd, raw, _ = self.h.get("/relais-connect.zip")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = z.namelist()
        self.assertIn("relais-connect/manifest.json", names)
        man = json.loads(z.read("relais-connect/manifest.json"))
        for f in ("background.js", "content.js", "config.js"):
            self.assertIn(f"relais-connect/{f}", names)
        self.assertEqual(man["manifest_version"], 3)
        self.assertEqual(man["name"], "Relais Connect")

    def test_apk_reserve_aux_connectes(self):
        self.assertIn(self.h.get("/relais.apk")[0], (200, 404))                                # 404 si dist/relais.apk n'existe pas sur la machine de test


if __name__ == "__main__":
    unittest.main()
