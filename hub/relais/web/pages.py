"""Pages HTML de l'interface, assemblées à partir de leurs sources (hub/ui/).

Une page peut contenir des repères `{{include chemin}}` (ou `{{include dossier/*.js}}`, fichiers triés par nom) : ils sont
remplacés tels quels par le contenu des fichiers. La page servie est donc un seul document, comme avant : la CSP continue
d'autoriser chaque script en ligne par son empreinte (aucun script externe, aucun 'unsafe-inline' pour les scripts).
Les sources sont relues si l'un des fichiers change (au plus une vérification par seconde), sans redémarrer le hub.
"""
import re
import time

from ..config import HERE

UI = HERE / "ui"
_INCLUDE = re.compile(r"\{\{include ([A-Za-z0-9_./*-]+)\}\}")
_cache = {}     # nom -> (dernière vérification, empreinte des fichiers, octets)


def _read(path):
    return path.read_bytes().decode("utf-8")      # sans conversion de fins de ligne : l'assemblage reste identique octet pour octet


def _expand(match):
    pattern = match.group(1)
    if ".." in pattern or pattern.startswith("/"):
        raise ValueError(f"chemin d'inclusion refusé : {pattern}")
    files = sorted(UI.glob(pattern))
    if not files:
        raise FileNotFoundError(f"inclusion introuvable : {pattern}")
    return "".join(_read(f) for f in files)


def _stamp():
    return tuple(sorted((str(p), p.stat().st_mtime_ns) for p in UI.rglob("*") if p.is_file()))


def assemble(name):
    """Page `name` (ex. « index.html ») avec ses inclusions résolues, en octets."""
    return _INCLUDE.sub(_expand, _read(UI / name)).encode("utf-8")


def page(name):
    now = time.time()
    hit = _cache.get(name)
    if hit and now - hit[0] < 1:
        return hit[2]
    stamp = _stamp()
    if hit and hit[1] == stamp:
        _cache[name] = (now, stamp, hit[2])
        return hit[2]
    body = assemble(name)
    _cache[name] = (now, stamp, body)
    return body
