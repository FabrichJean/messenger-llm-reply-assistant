"""Multi-utilisateurs : création, invitations, mots de passe et ISOLATION stricte des données."""
import unittest
from hubtest.harness import ADMIN_PW, Http, TestHub

PW_A, PW_B = "Alice-motdepasse-1", "Bob--motdepasse-2"


def denied(resp, secret=None):
    st, _, raw, js = resp
    ok = st >= 400 or (isinstance(js, dict) and js.get("error"))
    if secret:
        ok = ok and secret.encode() not in raw
    return bool(ok)


class HubUsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(accounts={"a1": "alice", "b1": "bob"}).start()
        cls.admin = cls.hub.admin()
        for n, pw in (("alice", PW_A), ("bob", PW_B)):
            st, _, _, js = cls.admin.post("/api/users/create", {"name": n, "password": pw})
            assert st == 200 and js.get("ok"), (st, js)
        # comme en production : au démarrage un compte dont le propriétaire n'existe pas encore revient à l'admin ; on l'attribue ensuite
        for n, acct in (("alice", "a1"), ("bob", "b1")):
            assert cls.admin.post("/api/users/assign", {"name": n, "account": acct})[3].get("ok")
        cls.ka = cls.hub.add_chat("a1", 11, "Léa Martin")
        cls.kb = cls.hub.add_chat("b1", 22, "Hugo Bernard")
        cls.hub.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES('sa',?,?,?,?,?)", (cls.ka, 1_800_000_000_000, "11", "SECRET-ALICE-ZEBRA", "contact"))
        cls.hub.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES('sb',?,?,?,?,?)", (cls.kb, 1_800_000_000_000, "22", "SECRET-BOB-OSLO", "contact"))
        cls.alice, cls.bob = Http(cls.hub.base), Http(cls.hub.base)
        assert cls.alice.login("alice", PW_A)[0] == 200 and cls.bob.login("bob", PW_B)[0] == 200

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    # --- chacun ne voit que ses comptes et ses conversations
    def test_etat_filtre_par_utilisateur(self):
        _, _, raw, js = self.alice.get("/api/state")
        self.assertEqual({c["key"] for c in js["chats"]}, {self.ka})
        self.assertEqual({a["name"] for a in js["accounts"]}, {"a1"})
        self.assertEqual({c["name"] for c in js["chats"]}, {"Léa Martin"})
        self.assertNotIn(b"SECRET-BOB", raw)
        _, _, raw, js = self.bob.get("/api/state")
        self.assertEqual({c["key"] for c in js["chats"]}, {self.kb})
        self.assertEqual({c["name"] for c in js["chats"]}, {"Hugo Bernard"})
        self.assertNotIn(b"SECRET-ALICE", raw)

    def test_lecture_de_la_conversation_d_autrui_refusee(self):
        self.assertTrue(denied(self.alice.get(f"/api/chat?key={self.kb}"), "SECRET-BOB"))
        self.assertTrue(denied(self.bob.get(f"/api/chat?key={self.ka}"), "SECRET-ALICE"))

    def test_lecture_de_sa_propre_conversation_ok(self):
        st, _, raw, js = self.alice.get(f"/api/chat?key={self.ka}")
        self.assertEqual(st, 200)
        self.assertIn(b"SECRET-ALICE-ZEBRA", raw)

    def test_ecriture_dans_la_conversation_d_autrui_refusee(self):
        before = len(self.hub.ops("b1"))
        self.assertTrue(denied(self.alice.post("/api/send", {"key": self.kb, "text": "intrusion"})))
        self.assertTrue(denied(self.alice.post("/api/chat/settings", {"key": self.kb, "mode": "auto", "instructions": "pirate"})))
        self.assertTrue(denied(self.alice.post("/api/chat/delete", {"key": self.kb})))
        self.assertTrue(denied(self.alice.post("/api/chat/pin", {"key": self.kb})))
        self.assertEqual(len(self.hub.ops("b1")), before)                                  # rien n'est parti vers le compte de Bob
        row = self.hub.sql("SELECT instructions FROM chats WHERE key=?", (self.kb,))[0]
        self.assertNotIn("pirate", row["instructions"])
        self.assertEqual(self.hub.sql("SELECT COUNT(*) c FROM chats WHERE key=?", (self.kb,))[0]["c"], 1)

    def test_comptes_d_autrui_inaccessibles(self):
        self.assertTrue(denied(self.alice.post("/api/accounts/remove", {"name": "b1"})))
        # la synchronisation globale ignore tout compte demandé : elle ne traite que les comptes de l'utilisateur connecté
        before = len(self.hub.ops("b1"))
        _, _, _, js = self.alice.post("/api/sync/all", {"account": "b1"})
        self.assertEqual(js.get("count"), 1)
        self.hub.wait(lambda: False, timeout=1)
        self.assertEqual(len(self.hub.ops("b1")), before)

    def test_statistiques_et_avatars_filtres(self):
        _, _, raw, js = self.alice.get("/api/stats")
        self.assertNotIn(b"b1", raw)

    def test_admin_ne_lit_pas_les_conversations_des_autres(self):
        _, _, raw, js = self.admin.get("/api/state")
        self.assertEqual(js["chats"], [])
        self.assertNotIn(b"SECRET", raw)
        self.assertTrue(denied(self.admin.get(f"/api/chat?key={self.ka}"), "SECRET-ALICE"))

    def test_utilisateur_simple_ne_gere_pas_les_utilisateurs(self):
        for path, body in (("/api/users/list", {}), ("/api/users/create", {"name": "eve", "password": "Eve-motdepasse-123"}),
                           ("/api/users/invite", {}), ("/api/users/assign", {"name": "alice", "account": "b1"}),
                           ("/api/users/delete", {"name": "bob", "confirm": True, "remove_accounts": True})):
            self.assertTrue(denied(self.alice.post(path, body)), path)
        self.assertEqual(self.hub.sql("SELECT COUNT(*) c FROM chats")[0]["c"], 2)

    # --- gestion des utilisateurs par l'administrateur
    def test_mot_de_passe_trop_court_refuse(self):
        st, _, _, js = self.admin.post("/api/users/create", {"name": "court", "password": "abc"})
        self.assertTrue(js.get("error"))

    def test_liste_des_utilisateurs(self):
        _, _, _, js = self.admin.post("/api/users/list")
        names = {u["name"] for u in js["users"]}
        self.assertTrue({"admin", "alice", "bob"} <= names)
        self.assertNotIn("password", str(js).lower().replace("passwords", ""))

    def test_invitation_usage_unique(self):
        _, _, _, js = self.admin.post("/api/users/invite")
        tok = js["path"].split("#", 1)[1]
        anon = Http(self.hub.base)
        st, _, _, r = anon.post("/api/join", {"token": tok, "username": "carol", "password": "Carol-motdepasse-3"})
        self.assertEqual(st, 200, r)
        self.assertEqual(Http(self.hub.base).login("carol", "Carol-motdepasse-3")[0], 200)
        st, _, _, r = Http(self.hub.base).post("/api/join", {"token": tok, "username": "dave", "password": "Dave-motdepasse-4"})
        self.assertGreaterEqual(st, 400)                                                    # le jeton est consommé
        self.assertNotEqual(Http(self.hub.base).login("dave", "Dave-motdepasse-4")[0], 200)

    def test_invitation_revoquee_inutilisable(self):
        _, _, _, js = self.admin.post("/api/users/invite")
        tok = js["path"].split("#", 1)[1]
        _, _, _, lst = self.admin.post("/api/users/list")
        inv = [i for i in lst["invites"]][-1]
        self.assertEqual(self.admin.post("/api/users/invite_revoke", {"id": inv["id"]})[3].get("ok"), True)
        st, *_ = Http(self.hub.base).post("/api/join", {"token": tok, "username": "frank", "password": "Frank-motdepasse-5"})
        self.assertGreaterEqual(st, 400)

    def test_changement_de_mot_de_passe_ferme_les_sessions(self):
        self.admin.post("/api/users/create", {"name": "zoe", "password": "Zoe--motdepasse-8"})
        h1, h2 = Http(self.hub.base), Http(self.hub.base)
        self.assertEqual(h1.login("zoe", "Zoe--motdepasse-8")[0], 200)
        self.assertEqual(h2.login("zoe", "Zoe--motdepasse-8")[0], 200)
        st, _, _, js = h1.post("/api/me/password", {"old": "Zoe--motdepasse-8", "new": "Zoe--nouveau-passe-9"})
        self.assertTrue(js.get("ok"), js)
        self.assertEqual(h2.get("/api/state")[0], 401)                                      # l'autre session est fermée
        self.assertEqual(Http(self.hub.base).login("zoe", "Zoe--motdepasse-8")[0], 401)
        self.assertEqual(Http(self.hub.base).login("zoe", "Zoe--nouveau-passe-9")[0], 200)

    def test_suppression_demande_confirmation(self):
        self.admin.post("/api/users/create", {"name": "tmpuser", "password": "Tmp--motdepasse-6"})
        self.assertTrue(self.admin.post("/api/users/delete", {"name": "tmpuser"})[3].get("error"))
        self.assertTrue(self.admin.post("/api/users/delete", {"name": "admin", "confirm": True})[3].get("error"))   # pas soi-même
        self.assertTrue(self.admin.post("/api/users/delete", {"name": "tmpuser", "confirm": True})[3].get("ok"))
        self.assertEqual(Http(self.hub.base).login("tmpuser", "Tmp--motdepasse-6")[0], 401)

    def test_attribution_d_un_compte(self):
        self.admin.post("/api/users/create", {"name": "gina", "password": "Gina-motdepasse-7"})
        self.assertTrue(self.admin.post("/api/users/assign", {"name": "gina", "account": "b1"})[3].get("ok"))
        g = Http(self.hub.base); g.login("gina", "Gina-motdepasse-7")
        self.assertEqual({c["key"] for c in g.get("/api/state")[3]["chats"]}, {self.kb})
        self.admin.post("/api/users/assign", {"name": "bob", "account": "b1"})              # remise en l'état


if __name__ == "__main__":
    unittest.main()
