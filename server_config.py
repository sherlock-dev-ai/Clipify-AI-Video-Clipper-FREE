"""Server configuration helpers."""

from __future__ import annotations

import os
from typing import Mapping


def configured_port(env: Mapping[str, str] | None = None) -> int:
    """Return the HTTP port configured in the environment, or 5000 by default.

    Valid ports are in the range 1..65535. An invalid port raises a ValueError
    naming the environment variable so the misconfiguration is obvious.
    """
    if env is None:
        env = os.environ
    raw = env.get("CLIPPEDAI_PORT", "").strip() if isinstance(env, (dict, os._Environ)) or hasattr(env, "get") else ""
    if not raw:
        return 5000
    try:
        port = int(raw)
        if 1 <= port <= 65535:
            return port
    except (ValueError, TypeError):
        pass
    raise ValueError(f"CLIPPEDAI_PORT must be an integer between 1 and 65535, got: {raw!r}")

