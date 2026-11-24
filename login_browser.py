#!/usr/bin/env python3
"""Fenêtre de connexion à Messenger.

Ouvre la VRAIE page officielle dans Google Chrome. Tu te connectes toi-même (mot de passe, code de vérification, etc.) DANS cette
fenêtre : ce programme ne voit, ne demande et ne stocke jamais ton mot de passe. Dès que la session est établie, il enregistre
seulement les cookies de session dans un fichier (permissions 600), puis ferme la fenêtre.

Dialogue avec le hub : une ligne JSON par évènement sur la sortie standard.
"""
import argparse
import json
import os
import signal
import sys
import time

NEEDED = ("c_user", "xs", "datr")
KEEP = ("c_user", "xs", "datr", "sb", "fr", "wd", "presence", "dpr", "oo")
BAD_PATH = ("login", "checkpoint", "two_step", "auth_platform", "recover", "confirmemail", "device-based")


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def collect(ctx, domains):
    """Cookies de session : on préfère ceux du domaine principal (messenger.com), puis les suivants."""
    jar = {}
    for dom in domains:
        for c in ctx.cookies():
            host = c["domain"].lstrip(".")
            if (host == dom or host.endswith("." + dom)) and c["name"] not in jar:
                jar[c["name"]] = c["value"]
    return jar


# ---- mode distant : navigateur SANS fenêtre sur le serveur, affiché dans une fenêtre modale du hub ------------------------------
ALLOWED_HOSTS = ("messenger.com", "facebook.com", "fbcdn.net", "facebook.net", "fbsbx.com", "fb.com", "akamaihd.net")
RECAPTCHA_HOSTS = ("www.google.com", "www.gstatic.com", "www.recaptcha.net", "recaptcha.net", "google.com", "gstatic.com")
BAD_WORDS = ("mot de passe que vous avez saisi", "mot de passe est incorrect", "incorrect", "n'est pas valide", "n’est pas valide", "wrong password", "password that you",
             "isn't associated", "isn’t associated", "n'est associé", "n’est associé", "ne correspond", "doesn't match", "doesn’t match", "invalid")
CHALLENGE_PATH = ("checkpoint", "two_step", "auth_platform", "device-based", "recover", "confirmemail", "authentication", "captcha")
KEYS = {"Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"}


TEST_HOST = os.environ.get("LOGIN_TEST_HOST", "")   # réservé aux tests automatiques (jamais défini en production)


def host_allowed(host, path):
    host = (host or "").lower().rstrip(".")
    if TEST_HOST and host == TEST_HOST:
        return True
    if any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        return True
    return host in RECAPTCHA_HOSTS and path.startswith("/recaptcha")   # captcha de sécurité de Facebook, rien d'autre chez Google


def resolver_rules():
    """Au niveau DNS : tout nom hors Meta (et captcha) est introuvable, y compris pour les WebSocket (le serveur ne devient pas un proxy)."""
    ex = []
    for h in ALLOWED_HOSTS + RECAPTCHA_HOSTS + ((TEST_HOST,) if TEST_HOST else ()):
        ex += [f"EXCLUDE {h}", f"EXCLUDE *.{h}"]
    return "MAP * ~NOTFOUND , " + " , ".join(ex)


def run_remote(args, domains):
    import queue
    import threading
    from urllib.parse import urlparse
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say(state="error", error="outil de connexion non installé (playwright)")
        return 2
    try:
        W, H = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        W, H = 420, 600
    W, H = max(280, min(W, 900)), max(320, min(H, 1200))
    cmds = queue.Queue()

    def reader():   # le hub nous parle sur l'entrée standard (une commande JSON par ligne) ; sa fermeture = arrêt
        try:
            for line in sys.stdin:
                try:
                    cmds.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            cmds.put({"t": "stop"})
    threading.Thread(target=reader, daemon=True).start()

    launch = {"headless": True, "args": ["--no-first-run", "--disable-extensions", "--disable-background-networking", "--disable-gpu",
                                          "--disable-dev-shm-usage", "--host-resolver-rules=" + resolver_rules()]}
    if os.environ.get("LOGIN_NO_SANDBOX") == "1":      # dans le conteneur (déjà cloisonné, sans privilèges) le bac à sable de Chromium n'est pas disponible
        launch["args"].append("--no-sandbox")
    if os.environ.get("LOGIN_CHANNEL"):
        launch["channel"] = os.environ["LOGIN_CHANNEL"]
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch)
        except Exception as ex:
            say(state="error", error=f"navigateur indisponible : {str(ex)[:160]}")
            return 3
        ver = browser.version.split(".")[0] if browser.version else "126"
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=2, accept_downloads=False, locale="fr-FR", timezone_id=os.environ.get("TZ") or "Europe/Paris",
                                  user_agent=f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36")

        def gate(route):
            u = urlparse(route.request.url)
            if (u.scheme == "https" or (TEST_HOST and u.scheme == "http")) and host_allowed(u.hostname, u.path) or u.scheme in ("data", "blob", "about"):
                route.continue_()
            else:
                route.abort()
        ctx.route("**/*", gate)
        ctx.on("page", lambda pg: pg.close() if len(ctx.pages) > 1 else None)   # pas de fenêtres supplémentaires
        page = ctx.new_page()
        page.on("dialog", lambda d: d.dismiss())
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        except Exception as ex:
            say(state="error", error=f"page injoignable : {str(ex)[:120]}")
            browser.close()
            return 4
        say(state="waiting_login")
        deadline = time.time() + args.timeout
        ok_since, last_nudge, last_shot, last_check = 0.0, time.time() - 15, 0.0, 0.0
        submit_at, chal_sent = 0.0, False
        try:
            while time.time() < deadline:
                # --- commandes de l'utilisateur (validées côté hub ET ici)
                try:
                    while True:
                        c = cmds.get_nowait()
                        t = c.get("t")
                        if t == "stop":
                            say(state="error", error="connexion annulée")
                            return 5
                        if t == "click":
                            page.mouse.click(max(0, min(float(c["x"]), W)), max(0, min(float(c["y"]), H)))
                        elif t == "text":
                            txt = "".join(ch for ch in str(c.get("s", ""))[:200] if ch.isprintable())
                            if txt:
                                page.keyboard.insert_text(txt)
                        elif t == "login":
                            # le formulaire du hub recopié dans la VRAIE page de Messenger (identifiants jamais conservés ni journalisés)
                            em, pw = str(c.get("email", ""))[:200], str(c.get("pass", ""))[:256]
                            try:
                                if "login" not in page.url.lower():
                                    page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                                pwf = page.locator('input[type="password"]:visible').first
                                emf = page.locator('input[type="email"]:visible, input[type="text"]:visible, input[name="email"]:visible').first
                                emf.fill(em, timeout=8000)
                                pwf.fill(pw, timeout=8000)
                                try:
                                    cb = page.locator('input[type="checkbox"]:visible').first
                                    if cb.count() and not cb.is_checked():
                                        cb.check(timeout=1500)   # « Rester connecté(e) »
                                except Exception:
                                    pass
                                pwf.press("Enter")
                                submit_at, chal_sent = time.time(), False
                                say(phase="submitted")
                            except Exception:
                                say(phase="challenge")   # page inattendue : l'utilisateur reprend la main avec l'affichage de la page
                            em = pw = None
                        elif t == "key" and c.get("k") in KEYS:
                            page.keyboard.press(c["k"])
                        elif t == "scroll":
                            page.mouse.wheel(0, max(-1500, min(float(c.get("dy", 0)), 1500)))
                except queue.Empty:
                    pass
                except Exception:
                    pass   # un clic sur une page en cours de navigation ne doit pas tout arrêter
                now = time.time()
                # --- image de la page (≈ 4 par seconde), écrite de façon atomique
                if args.frame and now - last_shot > 0.25:
                    last_shot = now
                    try:
                        jpg = page.screenshot(type="jpeg", quality=55, timeout=3000)
                        tmp = args.frame + ".tmp"
                        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, "wb") as f:
                            f.write(jpg)
                        os.replace(tmp, args.frame)
                    except Exception:
                        pass
                # --- la session est-elle établie ? (même logique que la fenêtre locale)
                if now - last_check > 1.0:
                    last_check = now
                    try:
                        url = page.url.lower()
                    except Exception:
                        url = ""
                    jar = collect(ctx, domains[:1])
                    connected = all(k in jar for k in NEEDED) and not any(b in url for b in BAD_PATH)
                    if not connected and all(k in collect(ctx, domains) for k in NEEDED) and not any(b in url for b in BAD_PATH):
                        if now - last_nudge > 20:
                            last_nudge = now
                            try:
                                page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                            except Exception:
                                pass
                    if connected:
                        ok_since = ok_since or now
                        if now - ok_since >= 6:
                            break
                    else:
                        ok_since = 0.0
                        if submit_at and not chal_sent and now - submit_at > 2.0:   # que répond Messenger à la tentative ?
                            if any(b in url for b in CHALLENGE_PATH):
                                chal_sent = True
                                say(phase="challenge")
                            else:
                                try:
                                    body = page.inner_text("body", timeout=1500).lower()
                                except Exception:
                                    body = ""
                                if "login" in url and any(w in body for w in BAD_WORDS):
                                    submit_at = 0.0
                                    say(phase="badcreds")
                                elif now - submit_at > 25:
                                    chal_sent = True
                                    say(phase="challenge")   # réponse inhabituelle (code, confirmation…) : on affiche la page
                time.sleep(0.05)
            else:
                say(state="error", error="délai dépassé : connexion non terminée")
                return 6
            jar = collect(ctx, domains)
            out = {k: jar[k] for k in KEEP if k in jar}
            fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(out, f, indent=2)
            say(state="captured", names=sorted(out), user_id=out.get("c_user"))
            return 0
        finally:
            try:
                browser.close()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="fichier cookies.json à écrire")
    ap.add_argument("--profile", default="", help="dossier de profil Chrome temporaire")
    ap.add_argument("--url", default="https://www.messenger.com/")
    ap.add_argument("--domains", default="messenger.com,facebook.com")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--headless", action="store_true", help="réservé aux tests automatiques")
    ap.add_argument("--remote", action="store_true", help="navigateur sans fenêtre piloté par le hub (serveur)")
    ap.add_argument("--size", default="420x600", help="taille de la page en mode distant (LxH)")
    ap.add_argument("--frame", default="", help="fichier image mis à jour en mode distant")
    args = ap.parse_args()
    domains = [d for d in args.domains.split(",") if d]
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(7))   # annulation depuis le hub : on ferme proprement Chrome (sinon il survit et réécrit son profil)

    if args.remote:
        return run_remote(args, domains)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say(state="error", error="outil de connexion non installé (playwright)")
        return 2

    os.makedirs(args.profile, mode=0o700, exist_ok=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                args.profile, channel="chrome", headless=args.headless, viewport={"width": 1100, "height": 820},
                args=["--no-first-run", "--no-default-browser-check"])
        except Exception as ex:
            say(state="error", error=f"impossible d'ouvrir Google Chrome : {str(ex)[:160]}")
            return 3
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        except Exception as ex:
            say(state="error", error=f"page injoignable : {str(ex)[:120]}")
            ctx.close()
            return 4
        say(state="waiting_login")
        deadline = time.time() + args.timeout
        ok_since = 0.0
        last_nudge = time.time() - 15   # premier coup de pouce après ~5 s
        try:
            while time.time() < deadline:
                if not ctx.pages:
                    say(state="error", error="fenêtre fermée avant la fin de la connexion")
                    return 5
                url = ""
                try:
                    url = page.url.lower()
                except Exception:
                    page = ctx.pages[0]
                # la session doit exister sur le domaine PRINCIPAL (messenger.com) : des cookies facebook.com seuls ne suffisent pas,
                # le client les refuserait (« user id in initial data is zero »)
                jar = collect(ctx, domains[:1])
                connected = all(k in jar for k in NEEDED) and not any(b in url for b in BAD_PATH)
                if not connected and all(k in collect(ctx, domains) for k in NEEDED) and not any(b in url for b in BAD_PATH):
                    # connecté côté facebook.com seulement : on ouvre messenger.com pour y établir la session (une fois, puis toutes les 20 s)
                    if time.time() - last_nudge > 20:
                        last_nudge = time.time()
                        try:
                            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass
                if connected:
                    ok_since = ok_since or time.time()
                    if time.time() - ok_since >= 6:  # laisse les cookies se stabiliser (rotation après connexion)
                        break
                else:
                    ok_since = 0.0
                time.sleep(1.0)
            else:
                say(state="error", error="délai dépassé : connexion non terminée")
                return 6
            jar = collect(ctx, domains)
            out = {k: jar[k] for k in KEEP if k in jar}
            fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(out, f, indent=2)
            say(state="captured", names=sorted(out), user_id=out.get("c_user"))
            return 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
