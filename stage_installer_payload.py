import os
import shutil
from pathlib import Path

ROOT = Path(r"L:\ClipifyAI")
PAYLOAD = ROOT / "build" / "installer_app" / "resources" / "payload"
UNPACKED = ROOT / "build" / "installer_app" / "out" / "win-unpacked" / "resources" / "payload"

targets = [PAYLOAD, UNPACKED]

files_to_sync = [
    "app.py",
    "main.py",
    "trending_service.py",
    "hindi_transliterator.py",
    "version.json",
    "real_supporters.json",
]

dirs_to_sync = [
    "static",
    "templates",
    "clipify",
    "live",
]

for t in targets:
    if not t.exists():
        t.mkdir(parents=True, exist_ok=True)
    print(f"[Stage Payload] Syncing to {t}...")
    for f in files_to_sync:
        src = ROOT / f
        if src.is_file():
            shutil.copy2(src, t / f)
            print(f"  ✓ Copied {f}")
        else:
            print(f"  ⚠ Missing {src}")
    for d in dirs_to_sync:
        src = ROOT / d
        dst = t / d
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  ✓ Synced directory {d} ({len(list(src.iterdir()))} items)")

print("[Stage Payload] Finished successfully.")

