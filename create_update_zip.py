import os
import zipfile
from pathlib import Path

ROOT = Path(r"L:\ClipifyAI")
ZIP_OUT = ROOT / "update-v6.0.12.zip"

files_to_pack = [
    "app.py",
    "main.py",
    "trending_service.py",
    "hindi_transliterator.py",
    "version.json",
    "real_supporters.json",
]

dirs_to_pack = [
    "static",
    "templates",
    "clipify",
    "live",
]

if ZIP_OUT.exists():
    ZIP_OUT.unlink()

with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in files_to_pack:
        p = ROOT / f
        if p.is_file():
            zf.write(p, arcname=f)
            print(f"  + Added file: {f}")
    
    for d in dirs_to_pack:
        dp = ROOT / d
        for root, dirs, files in os.walk(dp):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(ROOT)
                zf.write(full_path, arcname=str(rel_path).replace("\\", "/"))
                print(f"  + Added: {rel_path}")

print(f"\n[Zip Complete] Created {ZIP_OUT} ({ZIP_OUT.stat().st_size} bytes)")
