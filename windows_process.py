"""Process execution utilities for Windows desktop environment."""

from __future__ import annotations

import os
import subprocess


def clear_ffmpeg_report_environment() -> None:
    """Clear FFREPORT if present to prevent accidental report file generation."""
    os.environ.pop("FFREPORT", None)


def install_hidden_subprocess_defaults():
    """Wrap subprocess.run to add CREATE_NO_WINDOW creation flag on Windows by default."""
    orig_run = subprocess.run

    def hidden_run(*args, **kwargs):
        if os.name == "nt":
            flags = kwargs.get("creationflags", 0)
            kwargs["creationflags"] = flags | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return orig_run(*args, **kwargs)

    subprocess.run = hidden_run
    return hidden_run

