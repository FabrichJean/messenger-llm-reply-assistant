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


def prune(entries, day=None):
    """Retire les lignes expirées et plafonne le nombre de lignes (garde les plus utiles)."""
    keep = [e for e in entries if not expired(e, day)]
    rank = {"engagement": 0, "en-cours": 1, "événement": 2, "relation": 3, "identité": 4, "préférence": 5, "intérêt": 6, "note": 7, "historique": 8}
    if len(keep) > MAX_LINES:
        order = sorted(range(len(keep)), key=lambda i: (rank.get(keep[i]["cat"], 9), i))[:MAX_LINES]
        keep = [keep[i] for i in sorted(order)]
    return keep


def render(entries):
    return "\n".join(e["raw"] for e in entries)[:MAX_CHARS]


def clean_model_output(out, bad, suspicious):
    """Filtre la sortie du modèle ligne par ligne : format, contenu sensible, instructions piégées."""
    entries = []
    for e in parse(out, "probable"):   # une ligne sans balise produite par le modèle n'est jamais « observé »
        e.pop("legacy", None)
        if bad.search(re.sub(r"\d{4}-\d{2}-\d{2}", "", e["text"])) or suspicious([e["text"]]):   # les dates AAAA-MM-JJ ne sont pas des numéros de téléphone
            continue
        if e["cat"] == "engagement" and not STATUS.search(e["text"]):
            e["text"] += " (inconnu)"           # un engagement sans statut n'est jamais « effectué »
            e["raw"] = f"- [{e['cat']}|{e['conf']}] {e['text']}"
        entries.append(e)
    return prune(entries)


def _words(t):
    """Racines de mots (5 premières lettres, sans pluriel) : « match » et « matchs », « examen » et « examens » se rejoignent."""
    return {w.rstrip("sx")[:5] for w in re.findall(r"[a-zà-ÿ0-9]{4,}", (t or "").lower()) if w not in _STOP}


def select(text, recent_texts, day=None):
    """Récupération ciblée : toujours l'identité, la relation, le style, le contexte courant et les engagements ouverts ;
    le reste seulement si le sujet recoupe les derniers messages ou si l'événement est proche. -> (texte, nb_total, nb_gardées)"""
    day = day or today()
    entries = [e for e in parse(text) if not expired(e, day)]
    want = set()
    for t in recent_texts:
        want |= _words(t)
    out = []
    for e in entries:
        cat, keep = e["cat"], False
        st = (STATUS.search(e["text"]) or [None, "inconnu"])[1].lower() if cat == "engagement" else ""
        if cat in ALWAYS or e.get("legacy"):   # les lignes de l'ancien format (sans balise) restent lues : on ne sait pas les classer
            keep = True
        elif cat == "engagement":
            keep = st in ("en attente", "inconnu")
        elif cat == "événement":
            due = _date(e, "échéance")
            keep = bool(due and due >= day and due <= time.strftime("%Y-%m-%d", time.localtime(time.time() + 7 * 86400)))
        if not keep and cat != "historique":
            keep = bool(_words(e["text"]) & want)
        if not keep and cat == "historique":
            keep = bool(len(_words(e["text"]) & want) >= 2)
        if keep:
            out.append(e)
    return "\n".join(e["raw"] for e in out)[:MAX_CHARS], len(entries), len(out)
