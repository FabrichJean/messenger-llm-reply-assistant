#!/usr/bin/env python3
"""Hub Relais : interface web + LLM (Claude CLI) pour les contacts choisis.

Lanceur : tout le code est dans le paquet `relais/` (voir relais/app.py).

    python3 hub/hub.py        puis ouvrir http://127.0.0.1:8787
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relais.app import main  # noqa: E402

if __name__ == "__main__":
    main()
