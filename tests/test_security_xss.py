"""Audit XSS de bout en bout : une charge hostile placée dans CHAQUE champ qu'un contact ou un message peut contrôler ne doit jamais devenir
du HTML actif dans l'interface (vérifié dans un vrai navigateur). Nécessite Playwright (le .venv du dépôt) ; sinon le test est ignoré."""
import json, time, unittest
from hubtest.harness import ADMIN_PW, Http, TestHub

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                                # pragma: no cover
    sync_playwright = None

P = ('<img src=x data-xss=1 onerror="window.__xss=1"><b data-xss=1>gras</b><script>window.__xss=2</script>'
     '"\'><svg data-xss=1 onload="window.__xss=3"></svg><a data-xss=1 href="javascript:window.__xss=4">clic</a>{{7*7}}${7*7}')


@unittest.skipUnless(sync_playwright, "Playwright absent (utiliser .venv/bin/python)")
class Xss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = TestHub(accounts={"demo": None}).start()
        cls.hub.fast_replies()
        h = cls.hub
        # champs contrôlés par le propriétaire / le contact, injectés par la chaîne normale (évènements du client) ou directement en base
        h.inject("demo", 0, "", type="self", name=P)                                             # nom du profil Messenger = libellé du compte
        key = h.add_chat("demo", 777, P, instructions=P, memory="- [identité|confirmé] " + P)
        h.inject("demo", 777, P)                                                                 # texte du message
        for kind, extra in (("link", {"title": P, "subtitle": P, "descr": P, "site": P, "url": "https://exemple.com/a", "action": "javascript:window.__xss=5"}),
                            ("file", {"name": P, "mime": "text/html", "size": 10}), ("image", {"name": P, "mime": "image/svg+xml", "url": "https://exemple.com/x.svg"}),
                            ("link", {"title": P, "action": "https://exemple.com/\"onmouseover=\"window.__xss=6", "url": "data:text/html,<script>window.__xss=7</script>"})):
            h.inject("demo", 777, "", type="attachment", id=f"att{kind}{time.time_ns()}", idx=0, kind=kind, **extra)
        h.run_sql("INSERT INTO drafts(chat_key,text,created,status) VALUES(?,?,?,'pending')", (key, P, int(time.time() * 1000)))
        h.run_sql("INSERT INTO security_events(ts,chat_key,kind,detail) VALUES(?,?,?,?)", (int(time.time() * 1000), key, "input", P))
        h.run_sql("INSERT INTO account_settings(account,k,v) VALUES('demo','owner',?)", (P,))
        h.setting("persona", P, "demo")
        h.wait(lambda: h.sql("SELECT 1 FROM attachments LIMIT 1"), timeout=8)
        cls.http = h.admin()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.hub.stop()

    def open_page(self, width=1400):
        ctx = self.browser.new_context(viewport={"width": width, "height": 900})
        ctx.add_cookies([{"name": "hub_session", "value": self.http.cookie.split("=", 1)[1], "url": self.hub.base}])
        page = ctx.new_page(); logs = []
        page.on("console", lambda m: logs.append(m.text)); page.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
        page.on("dialog", lambda d: (logs.append("DIALOG " + d.message), d.dismiss()))
        page.goto(self.hub.base + "/"); page.wait_for_timeout(1800)
        return ctx, page, logs

    def verdict(self, page, logs, where):
        r = page.evaluate("""() => ({
            flag: window.__xss === undefined ? null : window.__xss,
            injected: document.querySelectorAll('[data-xss]').length,
            scripts: [...document.querySelectorAll('script')].filter(s => (s.textContent||'').includes('__xss=2')).length,
            badLinks: [...document.querySelectorAll('a[href],img[src],iframe,object,embed,form[action],link[href]:not([rel~=icon])')].filter(e => /^\\s*(javascript|data|vbscript):/i.test(e.getAttribute('href')||e.getAttribute('src')||e.getAttribute('action')||'')).map(e => e.outerHTML.slice(0,120)),
            handlers: [...document.querySelectorAll('*')].filter(e => [...e.attributes].some(a => /^on/i.test(a.name))).length,
        })""")
        self.assertIsNone(r["flag"], f"{where} : du code de la charge s'est exécuté (window.__xss={r['flag']})")
        self.assertEqual(r["injected"], 0, f"{where} : du HTML de la charge est devenu des éléments du DOM ({r['injected']})")
        self.assertEqual(r["scripts"], 0, where)
        self.assertEqual(r["badLinks"], [], f"{where} : lien ou source dangereux dans le DOM")
        self.assertEqual(r["handlers"], 0, f"{where} : attribut on* présent")
        self.assertFalse([l for l in logs if l.startswith("DIALOG")], f"{where} : boîte de dialogue ouverte par la charge")

    def test_vues_principales(self):
        ctx, page, logs = self.open_page()
        try:
            self.assertGreater(page.evaluate("document.querySelectorAll('.row').length"), 0, "aucune conversation affichée : le test ne prouverait rien")
            self.verdict(page, logs, "liste des conversations")
            page.evaluate("document.querySelectorAll('.row')[0].click()"); page.wait_for_timeout(1500)
            body = page.inner_text("body")
            self.assertIn("<img src=x", body, "la charge doit apparaître comme TEXTE")      # prouve qu'elle est affichée, mais inerte
            self.verdict(page, logs, "conversation ouverte")
            for nav in ("nv_stats", "nv_sec", "nv_set", "nv_log", "nv_hub"):
                page.evaluate(f"document.getElementById('{nav}') && document.getElementById('{nav}').click()"); page.wait_for_timeout(700)
                self.verdict(page, logs, nav)
            page.evaluate("document.getElementById('bacc').click()"); page.wait_for_timeout(900)
            self.verdict(page, logs, "fenêtre des comptes")
        finally:
            ctx.close()

    def test_vue_mobile(self):
        ctx, page, logs = self.open_page(width=390)
        try:
            self.verdict(page, logs, "mobile : accueil")
            for tab in ("tb_hub", "tb_stats", "tb_sec", "tb_set"):
                page.evaluate(f"document.getElementById('{tab}') && document.getElementById('{tab}').click()"); page.wait_for_timeout(600)
                self.verdict(page, logs, tab)
        finally:
            ctx.close()

    def test_csp_bloque_les_gestionnaires_en_ligne(self):
        """Même si du HTML était injecté, la politique de sécurité empêche l'exécution (filet de sécurité)."""
        ctx, page, logs = self.open_page()
        try:
            page.evaluate("""() => { const d = document.createElement('div'); d.innerHTML = '<img src=x onerror="window.__csp=1"><a id=zz href="javascript:window.__csp=2">x</a>'; document.body.append(d); document.getElementById('zz').click(); }""")
            page.wait_for_timeout(700)
            self.assertIsNone(page.evaluate("window.__csp === undefined ? null : window.__csp"), "la CSP laisse exécuter du code injecté")
            self.assertTrue([l for l in logs if "Content Security Policy" in l or "Refused to" in l], "aucune violation de CSP enregistrée")
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
