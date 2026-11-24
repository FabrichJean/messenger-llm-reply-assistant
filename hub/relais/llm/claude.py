"""Appel du Claude CLI (sans outils) et mesure de la consommation."""

import json
import os
import subprocess
import threading

from ..config import CLAUDE, SANDBOX
from ..db import NOW, setting, x


LLM_SEM = threading.Semaphore(2)


def call_claude(system, user, model=None, account=None, kind="gen"):
    mdl = model or setting("model", account)
    cmd = [CLAUDE, "-p", "--model", mdl, "--tools", "", "--no-session-persistence",
           "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "",
           "--system-prompt", system, "--output-format", "json"]
    keep = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SHELL", "TERM")
    env = {k: v for k, v in os.environ.items() if k in keep or k.startswith(("ANTHROPIC_", "CLAUDE_", "XDG_"))}
    r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=120, cwd=SANDBOX, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "échec Claude CLI").strip()[:300])
    try:
        d = json.loads(r.stdout)
        if not isinstance(d, dict) or "result" not in d:
            raise ValueError("format")
    except ValueError:
        return r.stdout.strip()   # sortie texte (ancienne version du CLI) : pas de mesure
    if d.get("is_error"):
        raise RuntimeError(str(d.get("result") or "échec Claude CLI")[:300])
    u = d.get("usage") or {}
    try:
        x("INSERT INTO llm_usage(ts,kind,model,input,cache_read,cache_write,output,cost,account) VALUES(?,?,?,?,?,?,?,?,?)",
          (NOW(), kind, mdl, int(u.get("input_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
           int(u.get("cache_creation_input_tokens") or 0), int(u.get("output_tokens") or 0), float(d.get("total_cost_usd") or 0), account or ""))
    except Exception:
        pass
    return str(d.get("result") or "").strip()
