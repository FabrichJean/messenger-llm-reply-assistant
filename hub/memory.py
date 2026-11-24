"""Mémoire relationnelle par conversation : fiche structurée, récupération ciblée, expiration.

Format d'une ligne (modifiable à la main par le propriétaire) :
    - [catégorie|confiance] contenu (vu AAAA-MM-JJ) (échéance AAAA-MM-JJ) (expire AAAA-MM-JJ) (statut)
catégories : identité, relation, événement, intérêt, préférence, engagement, en-cours, historique, note
confiance  : confirmé (dit par le propriétaire ou la personne), observé (plusieurs fois), probable, incertain
"""
import re
import time

CATS = ("identité", "relation", "événement", "intérêt", "préférence", "engagement", "en-cours", "historique", "note")
CONF = ("confirmé", "observé", "probable", "incertain")
LINE = re.compile(r"^\s*-\s*\[\s*([^|\]]+?)\s*(?:\|\s*([^\]]+?))?\s*\]\s*(.+?)\s*$")
DATE = re.compile(r"\((expire|échéance|vu)\s+(\d{4}-\d{2}-\d{2})\)", re.I)
STATUS = re.compile(r"\((en attente|effectué|annulé|inconnu)\)", re.I)
ALWAYS = {"identité", "relation", "préférence", "en-cours"}
_STOP = set("avec dans pour mais plus tout tous cette cela sont être avoir fait faire comme très bien même aussi donc alors encore quand "
            "elle elles nous vous leur leurs ceux celui ça est les des une que qui quoi pas sur par ces ses mes tes mon ton son".split())
MAX_LINES = 14
MAX_CHARS = 2000


def today():
    return time.strftime("%Y-%m-%d")


def norm_cat(c):
    c = (c or "").strip().lower().replace("evenement", "événement").replace("identite", "identité").replace("interet", "intérêt").replace("preference", "préférence")
    return c if c in CATS else "note"


def norm_conf(c):
    c = (c or "").strip().lower().replace("confirme", "confirmé").replace("observe", "observé")
    return c if c in CONF else "probable"


def parse(text, default_conf="observé"):
    """-> liste de dicts {cat, conf, text, raw}. Les lignes sans balise (ancien format) deviennent des notes « observé »."""
    out = []
    for l in (text or "").splitlines():
        if not l.strip():
            continue
        m = LINE.match(l)
        if m:
            out.append({"cat": norm_cat(m.group(1)), "conf": norm_conf(m.group(2)), "text": m.group(3)})
        elif l.strip().startswith("-"):
            out.append({"cat": "note", "conf": default_conf, "text": l.strip()[1:].strip(), "legacy": True})
    for e in out:
        e["raw"] = f"- [{e['cat']}|{e['conf']}] {e['text']}"
    return out


def _date(e, kind):
    m = [d for k, d in DATE.findall(e["text"]) if k.lower() == kind]
    return m[0] if m else None


def expired(e, day=None):
    d = _date(e, "expire")
    return bool(d and d < (day or today()))

