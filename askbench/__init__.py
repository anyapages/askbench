"""askbench: ask your single-cell data a question, a panel of agents answers it."""
__version__ = "0.1.0"

import os as _os
from pathlib import Path as _Path


def _load_dotenv() -> None:
    """Load a local, gitignored .env into the environment so the API key can live
    in a file rather than the shell or a chat log. Never overwrites existing env."""
    here = _Path(__file__).resolve().parent
    for p in (here.parent / ".env", here / ".env"):
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in _os.environ:
                    _os.environ[k] = v


_load_dotenv()
