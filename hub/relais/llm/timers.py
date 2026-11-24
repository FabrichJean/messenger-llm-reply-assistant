"""Minuteries de réponse en attente (une par conversation) et leur annulation."""


timers = {}          # chat_key -> (threading.Timer, version)


versions = {}


def cancel_timer(key):
    versions[key] = versions.get(key, 0) + 1
    t = timers.pop(key, None)
    if t:
        t.cancel()
