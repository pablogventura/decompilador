"""
Entry point del comando instalable ``external-ch1-smoke`` (``pyproject.toml``).

Delega en ``tools/external_ch1_smoke.py`` para no duplicar lógica.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> None:
    pkg_root = Path(__file__).resolve().parent.parent
    script = pkg_root / "tools" / "external_ch1_smoke.py"
    spec = importlib.util.spec_from_file_location("_hantek_external_ch1_smoke", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raise SystemExit(mod.main())
