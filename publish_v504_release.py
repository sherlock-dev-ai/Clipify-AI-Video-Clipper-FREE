import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.5"
RELEASE_NAME = "Clipify AI v5.0.5: Fast Startup Fix, Hinglish Captions, Live Studio & GPU Switcher"

RELEASE_NOTES = """<p align="center">
  <img src="https://raw.githubusercontent.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/main/docs/screenshots/dashboard.png" alt="Clipify AI Video Clipper" width="100%">
</p>

# Clipify AI v5.0.4: GPU Switching Cockpit, Max-Quality Live Facecam & Trending Hover Previews

### 🚀 What's New in v5.0.4

1. **⚡ Dynamic GPU Selector Cockpit (Top Header Bar)**:
   - Modern glassmorphism hardware switcher placed directly next to the GitHub button in both Main Studio and Live Studio headers.
   - **Multi-Device Dropdown**: Seamlessly detect, display, and toggle between all available GPUs (e.g. Discrete NVIDIA RTX A3000 / CUDA, Integrated Intel UHD / Iris Xe, and Multi-Core CPU Mode).
   - **Color-Coded Status Dot**: Glowing hardware indicator (Emerald Green for NVIDIA, Electric Cyan for Intel, Gold for CPU).
   - Instant hardware switching without needing to restart the application.

2. **🎥 Maximum Quality Live Stream Facecam Framing & Sharpness**:
   - Upgraded stream ingestion pipelines for **YouTube**, **Twitch**, and **Kick** to lock strictly onto highest available source stream resolution (4K / 1440p / 1080p60).
   - Enhanced facecam cropping with Lanczos multi-stage resampling and unsharp masking (`unsharp=5:5:0.8:3:3:0.4`) delivering crisp, high-definition facecam closeups in 9:16 vertical shorts.

3. **▶️ Hover-to-Play Video Previews in Trending (#trending)**:
   - Interactive hover cards across all live streams and trending gameplay videos.
   - Smooth 220ms debounce with muted, hardware-accelerated playback on mouse hover, giving an instant live peek into the action before clipping.

4. **📱 Mobile Companion & Cross-Platform Sync Refinements**:
   - Full 30-second Short rendering support verified across both live streams and viral gameplay videos.
   - Enhanced `DesktopSyncClient` network auto-discovery across Wi-Fi LAN and USB ADB reverse, seamlessly saving completed 1080x1920 9:16 Shorts to the mobile gallery (`Movies/ClipifyAI`).

5. **⚡ Resilient In-Place Updater (v5.0.4)**:
   - 1-click in-place updater package (`update-v5.0.4.zip`) instantly applies all features, theme aesthetics, and GPU control modules.

---

### 📦 Release Assets
- `Clipify.AI.Setup.5.0.4.exe`: Complete offline Windows desktop installer.
- `update-v5.0.4.zip`: Fast in-place updater package.
- `Clipify.AI.v5.0.4.apk`: Android mobile companion APK.
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

    print(f"[Release] Checking release for tag {TAG}...")
    release_id = None
    upload_url = None
    existing_assets = []

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
            print(f"[Release] Tag {TAG} not found. Creating fresh release...")
        else:
            raise

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

    # Assets to upload
    assets_to_upload = [
        ("Clipify.AI.Setup.5.0.5.exe", r"L:\ClipifyAI\Clipify.AI.Setup.5.0.5.exe", "application/octet-stream"),
        ("update-v5.0.5.zip", r"L:\ClipifyAI\update-v5.0.5.zip", "application/zip"),
        ("Clipify.AI.v5.0.5.apk", r"L:\ClipifyAI\android\app\build\outputs\apk\release\app-release.apk", "application/vnd.android.package-archive"),
        ("dashboard.png", r"L:\ClipifyAI\docs\screenshots\dashboard.png", "image/png"),
    ]

    for asset_name, asset_path, mime_type in assets_to_upload:
        p = Path(asset_path)
        if not p.is_file():
            print(f"[Asset] ⚠ File not found, skipping: {p}")
            continue

        file_size = p.stat().st_size
        print(f"\n[Asset] Preparing '{asset_name}' ({file_size / (1024*1024):.2f} MB)...")

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

        up_url = f"{upload_url}?name={urllib.parse.quote(asset_name)}"
        print(f"  + Uploading {asset_name} ({file_size / (1024*1024):.1f} MB)...")

        with open(p, "rb") as f:
            data = f.read()

        up_headers = {
            **headers,
            "Content-Type": mime_type,
            "Content-Length": str(len(data)),
        }
        up_req = urllib.request.Request(up_url, data=data, headers=up_headers, method="POST")
        try:
            with urllib.request.urlopen(up_req, timeout=3600) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                print(f"  ✓ Uploaded: {res_data.get('browser_download_url')}")
        except Exception as exc:
            print(f"  ❌ Upload error for {asset_name}: {exc}")

    print("\n[SUCCESS] GitHub Release v5.0.4 published successfully!")

if __name__ == "__main__":
    main()

