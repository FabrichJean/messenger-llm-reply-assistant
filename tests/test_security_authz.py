"""Audit : matrice d'autorisation. Alice tente CHAQUE route d'écriture sur les ressources de Bob ; rien de ce qui appartient à Bob ne doit changer."""
import json, unittest
from hubtest.harness import Http, TestHub

PW_A, PW_B = "Alice-motdepasse-1", "Bob--motdepasse-2"
B_KEY, A_KEY = "b1:22", "a1:11"


class AuthzMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(accounts={"a1": "alice", "b1": "bob"}).start()
        cls.hub.fast_replies()
        admin = cls.hub.admin()
        for n, pw, acct in (("alice", PW_A, "a1"), ("bob", PW_B, "b1")):
            admin.post("/api/users/create", {"name": n, "password": pw}); admin.post("/api/users/assign", {"name": n, "account": acct})
        cls.hub.add_chat("a1", 11, "Alice-chat"); cls.hub.add_chat("b1", 22, "Bob-chat", memory="- [identité|confirmé] SECRET-BOB", instructions="INSTR-BOB")
        cls.hub.add_chat("b1", 23, "Bob-chat-2", enabled=0)
        now = 1_800_000_000_000
        cls.hub.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES('mA1',?,?,?,?,?)", (A_KEY, now, "11", "message d'Alice", "contact"))
        cls.hub.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES('mB1',?,?,?,?,?)", (B_KEY, now, "22", "message de Bob", "contact"))
        cls.hub.run_sql("INSERT INTO drafts(id,chat_key,text,created,status) VALUES(901,?,?,?,'pending')", (B_KEY, "brouillon de Bob", now))
        cls.hub.run_sql("INSERT INTO account_settings(account,k,v) VALUES('b1','owner','Bob Réel')")
        cls.alice = Http(cls.hub.base); cls.alice.login("alice", PW_A)

    @classmethod
    def tearDownClass(cls):
        cls.hub.stop()

    def bob_state(self):
        h = self.hub
        return json.dumps({
            "chats": h.sql("SELECT * FROM chats WHERE account='b1' ORDER BY key"),
            "messages": h.sql("SELECT id,chat_key,text,src,edited,deleted,local_edit FROM messages WHERE chat_key LIKE 'b1:%' ORDER BY id"),
            "drafts": h.sql("SELECT id,chat_key,text,status FROM drafts WHERE chat_key LIKE 'b1:%' ORDER BY id"),
            "acct": h.sql("SELECT * FROM account_settings WHERE account='b1' ORDER BY k"),
            "ops": [o for o in h.ops("b1") if o.get("op") not in ("threads", "history_status")],      # ordres automatiques du hub au démarrage : sans rapport avec une attaque
            "accounts_json": json.loads((h.data / "accounts.json").read_text()),
        }, sort_keys=True, ensure_ascii=False)

    ATTACKS = [
        ("/api/send", {"key": B_KEY, "text": "intrusion"}), ("/api/chat/import", {"key": B_KEY}), ("/api/chat/prepare", {"key": B_KEY}), ("/api/chat/prepare/discard", {"key": B_KEY}),
        ("/api/message/edit", {"key": B_KEY, "id": "mB1", "text": "falsifié"}), ("/api/message/edit", {"key": A_KEY, "id": "mB1", "text": "falsifié via ma clé"}),
        ("/api/message/edit", {"key": A_KEY, "id": "mB1", "revert": True}),
        ("/api/chat/sync", {"key": B_KEY}), ("/api/chat/raise_limit", {"key": B_KEY}), ("/api/chat/unmute", {"key": B_KEY}), ("/api/chat/preview", {"key": B_KEY}),
        ("/api/chat/send_preview", {"key": B_KEY, "text": "x"}), ("/api/chat/force", {"key": B_KEY, "send": True}), ("/api/chat/pin", {"key": B_KEY, "pinned": True}),
        ("/api/chat/delete", {"key": B_KEY, "confirm": True}), ("/api/chat/rename", {"key": B_KEY, "name": "piraté"}), ("/api/clear_attention", {"key": B_KEY}),
        ("/api/chat/settings", {"key": B_KEY, "instructions": "pirate", "memory": "pirate", "mode": "draft", "enabled": False, "trusted": True, "max_per_hour": 1}),
        ("/api/chat/memory/refresh", {"key": B_KEY}), ("/api/draft", {"id": 901, "action": "send"}), ("/api/draft", {"id": 901, "action": "discard"}),
        ("/api/settings/reset", {"account": "b1"}), ("/api/settings", {"account": "b1", "owner": "pirate", "security_level": "off", "paused": "1"}),
        ("/api/accounts/register_e2ee", {"name": "b1", "confirm": True}), ("/api/accounts/remove", {"name": "b1", "confirm": True}),
        ("/api/chat/add", {"id": 999, "account": "b1", "name": "x"}), ("/api/history/enroll", {"pin": "123456", "confirm": True, "account": "b1"}),
        ("/api/style/analyze", {"account": "b1"}), ("/api/style/learn", {"account": "b1"}),
        ("/api/users/assign", {"name": "alice", "account": "b1"}), ("/api/users/reset", {"name": "bob", "password": "Pirate-motdepasse-1"}),
        ("/api/users/delete", {"name": "bob", "confirm": True, "remove_accounts": True}),
        # formes inattendues : types étranges, listes, imbrications
        ("/api/send", {"key": [B_KEY], "text": "x"}), ("/api/send", {"key": {"$ne": ""}, "text": "x"}), ("/api/settings", {"account": ["b1"], "owner": "x"}),
        ("/api/draft", {"id": "901 OR 1=1", "action": "send"}), ("/api/draft", {"id": [901], "action": "send"}), ("/api/chat/settings", {"key": "b1:22' OR '1'='1", "mode": "auto"}),
        ("/api/send", {"key": "B1:22", "text": "x"}), ("/api/send", {"key": " b1:22", "text": "x"}), ("/api/send", {"key": "b1:22\x00", "text": "x"}), ("/api/send", {"key": "a1:11/../b1:22", "text": "x"}),
    ]

    def test_aucune_attaque_ne_modifie_l_etat_de_bob(self):
        before = self.bob_state()
        for path, body in self.ATTACKS:
            self.alice.req("POST", path, body, timeout=8)
        self.hub.wait(lambda: False, timeout=2)
        after = self.bob_state()
        if before != after:
            b, a = json.loads(before), json.loads(after)
            diff = [k for k in b if b[k] != a[k]]
            self.fail(f"l'état de Bob a changé : {diff}\n" + "\n".join(f"  {k}: {json.dumps(a[k], ensure_ascii=False)[:400]}" for k in diff))

    def test_chaque_attaque_individuelle(self):
        """Une attaque à la fois : en cas d'échec on sait laquelle."""
        for path, body in self.ATTACKS:
            before = self.bob_state()
            st, _, _, js = self.alice.req("POST", path, body, timeout=8)
            self.hub.wait(lambda: False, timeout=0.3)
            after = self.bob_state()
            with self.subTest(route=path, corps=json.dumps(body)[:90]):
                self.assertEqual(before, after, f"{path} a modifié l'état de Bob (réponse {st} {json.dumps(js)[:120]})")

    def test_lectures_croisees(self):
        for path in (f"/api/chat?key={B_KEY}", f"/api/avatar?key={B_KEY}", "/api/chat?key=b1:22%20", "/api/chat?key=B1:22", f"/api/chat?key={A_KEY}/../{B_KEY}"):
            st, _, raw, _ = self.alice.get(path)
            with self.subTest(path=path):
                self.assertNotIn(b"SECRET-BOB", raw); self.assertNotIn(b"INSTR-BOB", raw); self.assertNotIn(b"message de Bob", raw)

    def test_etat_et_statistiques_ne_fuient_rien(self):
        for path in ("/api/state", "/api/stats"):
            _, _, raw, _ = self.alice.get(path)
            for secret in (b"SECRET-BOB", b"INSTR-BOB", b"message de Bob", b"Bob-chat", b"Bob R\xc3\xa9el", b"Bob R\\u00e9el", b"b1:22", b'"b1"'):
                with self.subTest(path=path, secret=secret):
                    self.assertNotIn(secret, raw)


if __name__ == "__main__":
    unittest.main()
