"""Geseidl Edition — overlay framework for Mail-in-a-Box.

Customizarile Geseidl traiesc aici, ca addon peste un upstream curat.
Cuplarea in codul upstream se face prin blocuri marcate `# >>> GESEIDL ... <<<`,
reinserabile cu `apply_overlay.py`. Vezi OVERLAY.md.
"""

__edition__ = "Geseidl Edition"

# Importat de hook-urile din daemon.py / status_checks.py.
from .engine import apply_overlay, apply_overlay_buffer  # noqa: E402,F401
