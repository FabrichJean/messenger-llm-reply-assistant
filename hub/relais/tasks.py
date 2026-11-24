"""Tâches de fond avec progression (plateau flottant de l'interface)."""

import threading

from .accounts import ACCOUNTS, mine
from .context import AUTH, cur_name
from .db import L, NOW
from .login import LOGIN


BUSY = {"style": False, "import": ""}


# Tâches asynchrones visibles dans l'interface (avec progression)
TASKS = {}


_TL = threading.local()


_TASK_SEQ = [0]


class task:
    """Contexte d'une tâche longue : `with task("Libellé", total=12) as t: ... tp(done, detail=...)`.
    Une tâche imbriquée dans une autre ne crée pas de nouvelle ligne : elle met à jour celle de son parent."""
    def __init__(self, label, total=0, key="", owner=None):
        self.label, self.total, self.key, self.id, self.nested = label, total, key, None, False
        self.owner = owner if owner is not None else cur_name()

    def __enter__(self):
        stack = getattr(_TL, "stack", None)
        if stack is None:
            stack = _TL.stack = []
        if stack:
            self.nested, self.id = True, stack[-1]
        else:
            with L:
                _TASK_SEQ[0] += 1
                self.id = f"t{_TASK_SEQ[0]}"
                TASKS[self.id] = {"id": self.id, "label": self.label, "detail": "", "done": 0, "total": int(self.total or 0), "state": "running",
                                  "started": NOW(), "ended": 0, "error": "", "key": self.key, "owner": self.owner}
        stack.append(self.id)
        return self

    def __exit__(self, et, ev, tb):
        _TL.stack.pop()
        if not self.nested:
            with L:
                t = TASKS.get(self.id)
                if t:
                    t.update(state="error" if et else "done", ended=NOW(), error=str(ev)[:160] if et else "")
                    if not et and t["total"]:
                        t["done"] = t["total"]
                for k in [k for k, v in TASKS.items() if v["ended"] and NOW() - v["ended"] > 60_000]:
                    del TASKS[k]
        return False


def tp(done=None, total=None, detail=None):
    """Met à jour la tâche en cours du fil courant (sans effet s'il n'y en a pas)."""
    stack = getattr(_TL, "stack", None)
    if not stack:
        return
    t = TASKS.get(stack[-1])
    if not t:
        return
    if total is not None:
        t["total"] = int(total)
    if done is not None:
        t["done"] = int(done)
    if detail is not None:
        t["detail"] = str(detail)[:80]


def tasks_view():
    now = NOW()
    me = cur_name()
    out = [{k: v for k, v in t.items() if k != "owner"} for t in TASKS.values()
           if (t["state"] == "running" or now - t["ended"] < 7000) and (not AUTH.enabled or t.get("owner") == me)]
    for a in ACCOUNTS.values():
        if a.name not in mine():
            continue
        if a.state.get("history") == "enrolling":
            out.append({"id": "h-" + a.name, "label": "Restauration de l'historique chiffré", "detail": a.label or a.name, "done": 0, "total": 0,
                        "state": "running", "started": now, "ended": 0, "error": "", "key": "history"})
    for v in LOGIN.values():
        if v.get("state") in ("starting", "waiting_login", "captured") and (not AUTH.enabled or v.get("owner") == me):
            out.append({"id": "login", "label": "Connexion d'un compte Messenger", "detail": ("Saisis tes identifiants dans la fenêtre de connexion" if v.get("remote") else "Termine la connexion dans la fenêtre Chrome") if v["state"] == "waiting_login" else "",
                        "done": 0, "total": 0, "state": "running", "started": v.get("started") or now, "ended": 0, "error": "", "key": "login"})
    return sorted(out, key=lambda t: t["started"])


TASK_LABELS = {"import": "Import de l'historique", "sync": "Synchronisation des conversations", "names": "Recherche des noms et photos",
               "learn": "Apprentissage de ton style"}


BG = {}   # utilisateur -> nom de sa tâche de fond en cours (une à la fois PAR utilisateur)


def run_bg(name, fn, *a):
    owner = cur_name()

    def go():
        try:
            with task(TASK_LABELS.get(name, name), key=name, owner=owner):
                fn(*a)
        finally:
            BG.pop(owner, None)
    with L:
        if BG.get(owner):
            return False
        BG[owner] = name
    threading.Thread(target=go, daemon=True).start()
    return True
