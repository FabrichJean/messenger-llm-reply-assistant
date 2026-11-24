"""Importe un module du hub qu'il soit à plat (hub/humanize.py) ou rangé dans le paquet (hub/relais/humanize.py)."""
import importlib, sys
from pathlib import Path
HUB_DIR = str(Path(__file__).resolve().parents[2] / "hub")
if HUB_DIR not in sys.path:
    sys.path.insert(0, HUB_DIR)

def load(name):
    for mod in (f"relais.{name}", f"relais.llm.{name}", name):
        try:
            return importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name not in (mod, mod.split(".")[0], "relais", "relais.llm"):
                raise
    raise ModuleNotFoundError(name)
