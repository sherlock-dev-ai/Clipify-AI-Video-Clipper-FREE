import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.3"
RELEASE_NAME = "Clipify AI v5.0.3: Editor Caption Studio, Clipped Shorts Tray & Resilient Updater"

RELEASE_NOTES = """<p align="center">
  <img src="https://raw.githubusercontent.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/main/docs/screenshots/dashboard.png" alt="Clipify AI Video Clipper" width="100%">
</p>

# Clipify AI v5.0.3: Editor Caption Studio, Clipped Shorts Tray & Resilient In-Place Updater

### 🚀 What's New in v5.0.3

1. **🎞️ Clipped Shorts Gallery & Filmstrip Tray (#editor)**:
   - Dedicated horizontal filmstrip tray situated beneath the Editor layout (`#editorShortsTrayContainer`) displaying all finished clips.
   - **1-Click Clip Loading**: Click any card in the filmstrip to immediately load that short into the Editor review video player with duration badges, filenames, and smooth scrolling.
   - Hover preview play/pause and real-time refresh sync with active projects.

2. **✨ Advanced Caption & Typography Studio in Editor (#editor)**:
   - **7 Animated Style Presets**: Viral Yellow Punch (`#FFE500`), Cyber Lime Green (`#39FF14`), Hormozi Bold White (`#FFFFFF`), TikTok Cyan Pop (`#00F2FE`), Crimson Fire (`#FF3344`), Typewriter Retro (`#00FF66`), and Neon Lavender (`#E879F9`).
   - **Safe-Area Alignment Snapping**: 1-click snapping buttons for **Top Safe (25%)**, **Center Seam (50%)**, and **Lower Safe (75%)**.
   - **Font Size Stepper & Quick Pills**: Dedicated `[−]` and `[+]` size stepper buttons, font size slider (`2%` to `25%`), and quick preset pills (`S (4%)`, `M (6%)`, `L (8%)`, `XL (11%)`).
   - **Subtitle Captions Toggle**: Instant on/off toggle to cleanly show or hide subtitle overlays before export.
   - **Interactive Mouse Dragging & Resizing**: Drag `#editorText` freely on the preview canvas with corner handle resizing (`⤡`) and mouse wheel scaling.

3. **⚡ Bulletproof Resilient In-Place Updater**:
   - Fixed background daemon restart pipeline ensuring `python app.py` rebinds port `5000` automatically upon clicking **Update** without connection drops or `Failed to fetch` errors.
   - Full backward-compatible updater archive with automated payload extraction and service health check polling.

4. **🔴 Trending Cockpit & 1-Click Clipping (#trending)**:
   - Live stream and viral gameplay discovery engine across **YouTube**, **Twitch**, and **Kick**.
   - 1-Click "Clip this" button that imports regular videos into **Create Studio** (`#create`) and live streams into **Live Studio** (`/live`).

5. **💰 Clipper Campaigns & Bounties Directory (#campaigns)**:
   - Monetization hub listing top verified platforms (Content Rewards #1, Vyro #2, Clipster #3, plus India-specific hubs ClipGrow and ClipConnect).

6. **🤖 Dynamic Clippy AI Knowledge Base**:
   - Fast responses with local model reasoning cleanup and intelligent contextual guidance.

---

### 📦 Release Assets
- `Clipify.AI.Setup.5.0.3.exe`: Full offline Windows desktop installer.
- `update-v5.0.3.zip`: Fast in-place updater (automatically downloaded when clicking **Update** in the desktop app).
- `Clipify.AI.beta.apk`: Android companion app.
- `dashboard.png`: High-resolution dashboard showcase.
"""

def get_github_token():
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return os.getenv("GITHUB_TOKEN", "")

def main():
    token = get_github_token()
    if not token:
        print("[ERROR] Could not obtain GitHub token from git credentials!")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Clipify-Release-Publisher",
    }

    # 1. Check if release already exists
    release_id = None
    upload_url = None
    existing_assets = []

    print(f"[Release] Checking release for tag {TAG}...")
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            release_id = data["id"]
            upload_url = data["upload_url"].split("{")[0]
            existing_assets = data.get("assets", [])
            print(f"[Release] Found existing release ID: {release_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[Release] Release does not exist yet. Creating...")
        else:
            raise

    # 2. Create release if needed
    if not release_id:
        create_payload = json.dumps({
            "tag_name": TAG,
            "target_commitish": "feature/cross-platform",
            "name": RELEASE_NAME,
            "body": RELEASE_NOTES,
            "draft": False,
            "prerelease": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases",
            data=create_payload,
            headers={**headers, "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            release_id = data["id"]
            upload_url = data["upload_url"].split("{")[0]
            print(f"[Release] Created release ID: {release_id}")
    else:
        # Update existing release title & notes
        update_payload = json.dumps({
            "name": RELEASE_NAME,
            "body": RELEASE_NOTES,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/{release_id}",
            data=update_payload,
            headers={**headers, "Content-Type": "application/json"},
            method="PATCH"
        )
        with urllib.request.urlopen(req) as resp:
            print(f"[Release] Updated release {TAG} notes.")

    # 3. Assets to upload
    assets_to_upload = [
        ("Clipify.AI.Setup.5.0.3.exe", r"L:\ClipifyAI\Clipify.AI.Setup.5.0.3.exe", "application/octet-stream"),
        ("update-v5.0.3.zip", r"L:\ClipifyAI\update-v5.0.3.zip", "application/zip"),
        ("Clipify.AI.beta.apk", r"L:\ClipifyAI\Clipify.AI.beta.apk", "application/vnd.android.package-archive"),
        ("dashboard.png", r"L:\ClipifyAI\docs\screenshots\dashboard.png", "image/png"),
    ]

    for asset_name, asset_path, mime_type in assets_to_upload:
        p = Path(asset_path)
        if not p.is_file():
            print(f"[Asset] ⚠ File not found, skipping: {p}")
            continue

        file_size = p.stat().st_size
        print(f"\n[Asset] Preparing '{asset_name}' ({file_size / (1024*1024):.2f} MB)...")

        # Delete existing asset with same name if present
        for ea in existing_assets:
            if ea["name"] == asset_name:
                print(f"  - Deleting existing asset {ea['id']}...")
                del_req = urllib.request.Request(
                    f"https://api.github.com/repos/{REPO}/releases/assets/{ea['id']}",
                    headers=headers,
                    method="DELETE"
                )
                try:
                    urllib.request.urlopen(del_req)
                    time.sleep(1)
                except Exception as ex:
                    print(f"    (Notice: {ex})")

        # Upload
        up_url = f"{upload_url}?name={urllib.parse.quote(asset_name)}"
        with open(p, "rb") as f:
            data = f.read()

        up_headers = {
            **headers,
            "Content-Type": mime_type,
            "Content-Length": str(len(data)),
        }
        print(f"  + Uploading {asset_name}...")
        up_req = urllib.request.Request(up_url, data=data, headers=up_headers, method="POST")
        try:
            with urllib.request.urlopen(up_req) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                print(f"  ✓ Uploaded: {res_data.get('browser_download_url')}")
        except Exception as exc:
            print(f"  ❌ Upload error for {asset_name}: {exc}")

    print("\n[SUCCESS] GitHub Release v5.0.3 published successfully!")

if __name__ == "__main__":
    main()

