import shutil
import os

src = r"L:\ClipifyAI"
dst = r"C:\Users\Dell\AppData\Local\Programs\ClipifyAI"

files = [
    "app.py",
    "live/stream_connector.py",
    "live/smart_editor.py",
    "clipify/platform/gpu_manager.py",
    "clipify/platform/hardware.py",
    "static/trending.js",
    "static/trending.css",
    "static/style.css",
    "static/app.js",
    "static/gpu_selector.js",
    "templates/index.html",
    "templates/live.html",
]

for f in files:
    s = os.path.join(src, f.replace("/", os.sep))
    d = os.path.join(dst, f.replace("/", os.sep))
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(s, d)

print("Copied all modified files successfully!")

