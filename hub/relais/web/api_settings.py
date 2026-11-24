"""Routes de réglages (généraux et propres à un compte)."""

from ..accounts import ACCOUNTS
from ..context import acct_of, log
from ..db import set_setting, x
from ..llm.timers import cancel_timer, timers


def settings(b):
    # POST /api/settings
    scope = b.get("account") or None
    if scope and scope not in ACCOUNTS:
        return {"error": "compte inconnu"}
    for k in ("paused", "model", "owner", "persona", "max_per_hour_global", "takeover_min",
              "style_profile", "style_cross", "style_auto", "late_reply_min", "sync_s", "judge", "security_level", "classifier", "attack_mode", "link_preview", "link_preview_fb", "typing", "read_delay", "token_mode"):
        if k in b:
            set_setting(k, b[k], scope)
    if b.get("paused") in (1, "1", True):
        for k in list(timers):
            if not scope or acct_of(k) == scope:
                cancel_timer(k)
    return {"ok": True}


def settings_reset(b):
    # POST /api/settings/reset
    if b.get("account") not in ACCOUNTS:
        return {"error": "compte inconnu"}
    x("DELETE FROM account_settings WHERE account=? AND k NOT IN ('style_profile','style_n')", (b["account"],))
    log("info", f"[{b['account']}] réglages propres au compte réinitialisés (valeurs générales)")
    return {"ok": True}


ROUTES = {
    "/api/settings": settings,
    "/api/settings/reset": settings_reset,
}
