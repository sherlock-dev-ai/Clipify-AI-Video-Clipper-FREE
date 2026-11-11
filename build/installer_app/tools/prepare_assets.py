"""Stage the supplied Clipify AI icon for app and installer UI assets.

The ICO is maintained separately, so package setup never needs Pillow or
invents a replacement mark.
"""

from __future__ import annotations

from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent.parent
SOURCE_ICON = PROJECT / "icon.png"
APP_MARK = PROJECT / "static" / "clipify-ai-mark.png"
OUT_DIR = HERE.parent / "build"


def main() -> None:
    if not SOURCE_ICON.is_file():
        raise SystemExit(f"Approved brand icon is missing: {SOURCE_ICON}")
    ico = OUT_DIR / "icon.ico"
    if not ico.is_file():
        raise SystemExit(f"Windows icon resource is missing: {ico}")
    for target in (APP_MARK, OUT_DIR / "logo.png", OUT_DIR / "logo-round.png"):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_ICON, target)
        print(f"[assets] copied {SOURCE_ICON} -> {target}")
    print(f"[assets] preserving Windows icon resource {ico}")


if __name__ == "__main__":
    main()
