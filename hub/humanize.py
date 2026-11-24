"""Rendre les réponses automatiques naturelles : longueur proportionnée, pas de répétition, emojis mesurés, et ne jamais répondre
à la place de l'utilisateur quand l'interlocuteur se demande s'il parle à une IA. Fonctions pures (aucun accès base de données)."""
import difflib
import re
import statistics

EMO1 = re.compile("[\U0001F000-\U0001FAFF☀-➿⭐❤](?:[️\U0001F3FB-\U0001F3FF]|‍[\U0001F000-\U0001FAFF☀-➿])*")
_AI = re.compile(r"(?:\bia\b|\bi\.a\.?|\bai\b|\bbots?\b|\brobots?\b|\brobotis\w*|chat\s?gpt|\bgpt\b|intelligence artificielle|algorithme|automatis\w+|\bautomatique\b|\bmachine\b)", re.I)
_YOU = re.compile(r"(?:\btu\b|\bt['’]es\b|\bt['’]as\b|\btoi\b|\bvous\b|\bes-tu\b|\bparles?\b|\b[ée]cris\b|\br[ée]ponds?\b|\bc['’]est (?:vraiment |bien )?(?:toi|un|une)\b)", re.I)
_REAL = re.compile(r"(?:c['’]est (?:vraiment|bien) toi|t['’]es (?:un |une )?(?:vrai|vraie|humain|humaine|r[ée]el)|tu es (?:un |une )?(?:vrai|vraie|humain|humaine|r[ée]el)|es-tu (?:un |une )?(?:vrai|vraie|humain|humaine)|t['’]es (?:vraiment )?(?:une? )?personne|tu es (?:vraiment )?(?:une? )?personne)", re.I)


def words(t):
    return len(re.findall(r"[\w'’]+", t or ""))


def asks_if_bot(text):
    """Vrai si le message demande (ou taquine) si l'interlocuteur est un robot / une IA / pas un vrai humain."""
    t = text or ""
    if _REAL.search(t):
        return True
    return bool(_AI.search(t) and _YOU.search(t))


def norm(t):
    t = EMO1.sub(" ", (t or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def similarity(a, b):
    """0..1 : à quel point deux messages se ressemblent (séquence et vocabulaire)."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    ta, tb = {w for w in na.split() if len(w) >= 3}, {w for w in nb.split() if len(w) >= 3}
    jac = len(ta & tb) / len(ta | tb) if (ta and tb) else 0.0
    return max(difflib.SequenceMatcher(None, na, nb).ratio(), jac)


def emoji_rate(texts):
    texts = [t for t in texts if t]
    return (sum(1 for t in texts if EMO1.search(t)) / len(texts)) if texts else 0.0


def target_words(owner_texts, last_contact):
    """Longueur visée (en mots) : celle de l'utilisateur, sans dépasser ce que le message reçu appelle (on ne répond pas en roman à trois mots)."""
    ow = [words(t) for t in owner_texts if t and words(t) > 0]
    lc = words(last_contact)
    base = statistics.median(ow) if len(ow) >= 6 else max(6, lc)
    tw = round(base * 1.6)
    tw = min(tw, max(8, round(lc * 2.5) + 4))
    return max(4, min(tw, 30))


def cut_sentences(text, tw):
    """Garde les premières phrases tant qu'on reste sous `tw` mots (au moins une). Une phrase unique trop longue est coupée à la dernière virgule
    avant la limite ; sans virgule, elle est gardée telle quelle si elle reste raisonnable, sinon rendue vide (on préfère se taire qu'envoyer un morceau de phrase)."""
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    out, n = [], 0
    for p in parts:
        w = words(p)
