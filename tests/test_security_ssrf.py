"""Audit SSRF : le hub ne doit jamais faire de requête vers une adresse non publique, quelle que soit son écriture ou son chemin (redirection, IPv6, nom d'hôte)."""
import ipaddress, os, tempfile, unittest
os.environ.setdefault("HUB_DATA", tempfile.mkdtemp(prefix="relais-ssrf-"))
from hubtest.imp import load

media = load("media")

INTERNES = ["127.0.0.1", "127.255.255.254", "0.0.0.0", "10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255", "192.168.0.1", "169.254.169.254", "169.254.0.1",
            "100.64.0.1", "100.100.100.200", "100.127.255.255", "192.0.0.1", "192.0.2.1", "198.18.0.1", "198.19.255.255", "198.51.100.1", "203.0.113.1", "224.0.0.1", "239.255.255.250",
            "240.0.0.1", "255.255.255.255", "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:100.64.0.1", "::ffff:169.254.169.254",
            "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::6440:1", "2002:7f00:1::", "2002:a00:1::", "2002:6440:1::", "2001:db8::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2"]
PUBLICS = ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:4700:4700::1111", "2001:4860:4860::8888", "::ffff:8.8.8.8"]


class Adresses(unittest.TestCase):
    def test_adresses_internes_refusees(self):
        for a in INTERNES:
            with self.subTest(adresse=a):
                self.assertFalse(media._is_public(ipaddress.ip_address(a)), f"{a} est jugée publique")

    def test_adresses_publiques_acceptees(self):
        for a in PUBLICS:
            with self.subTest(adresse=a):
                self.assertTrue(media._is_public(ipaddress.ip_address(a)), f"{a} est refusée à tort")

    def test_noms_d_hotes_internes_refuses(self):
        for h in ("localhost", "localhost.", "LOCALHOST", "127.0.0.1", "0x7f000001", "2130706433", "127.1", "::1", "0", "broadcasthost", "127.0.0.1\x00.example.com"):
            with self.subTest(hote=h):
                with self.assertRaises(Exception):
                    media._public_ips(h, 80)

    def test_une_seule_adresse_interne_parmi_plusieurs_suffit_a_refuser(self):
        import socket
        orig = socket.getaddrinfo
        try:
            socket.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.1.2.3", 80))]       # DNS qui mélange public et interne
            with self.assertRaises(ValueError):
                media._public_ips("piege.example", 80)
        finally:
            socket.getaddrinfo = orig


class Requetes(unittest.TestCase):
    def test_adresses_refusees_avant_toute_connexion(self):
        for url in ("http://127.0.0.1/", "http://localhost/", "http://10.0.0.5:80/", "http://169.254.169.254/latest/meta-data/", "http://100.100.100.200/", "http://[::1]/",
                    "http://user:pass@exemple.com/", "http://exemple.com:8080/", "http://exemple.com:22/", "https://exemple.com:6379/", "file:///etc/passwd", "ftp://exemple.com/",
                    "gopher://exemple.com/", "javascript:alert(1)", "data:text/html,x", "//exemple.com/", "http:///x", "http://"):
            with self.subTest(url=url):
                with self.assertRaises(Exception):
                    media.fetch_public(url, 1000, timeout=2)

    def test_redirection_vers_une_adresse_interne_refusee(self):
        """Un site public qui redirige vers le réseau interne ne doit pas être suivi (chaque saut est revalidé)."""
        import http.client
        calls = []
        class FakeResp:
            status = 302
            def getheader(self, k, d=None): return "http://169.254.169.254/latest/meta-data/" if k == "Location" else d
            def read(self, n=-1): return b""
        class FakeConn:
            def __init__(self, *a, **k): calls.append(a)
            def request(self, *a, **k): pass
            def getresponse(self): return FakeResp()
            def close(self): pass
        orig_ips, orig_p, orig_h = media._public_ips, media._Pinned, media._PinnedHTTP
        try:
            media._public_ips = lambda host, port: ["93.184.216.34"] if host == "exemple.com" else orig_ips(host, port)       # l'hôte de départ est « public »
            media._Pinned = media._PinnedHTTP = FakeConn
            with self.assertRaises(ValueError):
                media.fetch_public("https://exemple.com/", 1000, timeout=2)
            self.assertEqual(len(calls), 1, "le hub s'est connecté au saut interne")
        finally:
            media._public_ips, media._Pinned, media._PinnedHTTP = orig_ips, orig_p, orig_h

    def test_cookie_de_session_jamais_envoye_hors_des_domaines_autorises(self):
        sent = []
        class FakeResp:
            def __init__(self, loc): self.status = 302 if loc else 200; self.loc = loc
            def getheader(self, k, d=None): return self.loc if k == "Location" else ("text/html" if k == "Content-Type" else d)
            def read(self, n=-1): return b"<html></html>"
        hops = ["https://www.facebook.com/a", "https://evil.example/b", None]
        class FakeConn:
            def __init__(self, host, ip, **k): self.host = host
            def request(self, m, path, headers=None): sent.append((self.host, headers.get("Cookie")))
            def getresponse(self): return FakeResp(hops.pop(0) if False else (hops[len(sent) - 1] if len(sent) - 1 < len(hops) else None))
            def close(self): pass
        orig_ips, orig_p = media._public_ips, media._Pinned
        try:
            media._public_ips = lambda host, port: ["93.184.216.34"]
            media._Pinned = FakeConn
            media.fetch_public("https://www.facebook.com/start", 1000, timeout=2, cookie="c_user=SECRET; xs=SECRET", cookie_hosts=("facebook.com",))
        finally:
            media._public_ips, media._Pinned = orig_ips, orig_p
        by_host = {h: c for h, c in sent}
        self.assertEqual(by_host.get("www.facebook.com"), "c_user=SECRET; xs=SECRET")
        self.assertIsNone(by_host.get("evil.example"), "la session a été envoyée à un domaine tiers après une redirection")


if __name__ == "__main__":
    unittest.main()
