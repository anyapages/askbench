"""Shared path setup for Vercel serverless handlers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Loads .env when present; safe when absent (deterministic demo).
import askbench  # noqa: F401,E402
