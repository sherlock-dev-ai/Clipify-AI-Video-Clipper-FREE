import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.2"
RELEASE_NAME = "Clipify AI v5.0.2: Clipper Campaigns, Trending Streams, Caption Studio & Mobile Fixes"

RELEASE_NOTES = """<p align="center">
  <img src="https://raw.githubusercontent.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/main/docs/screenshots/dashboard.png" alt="Clipify AI Video Clipper" width="100%">
</p>

# Clipify AI v5.0.2: Clipper Campaigns, Trending Streams, Caption Studio & Mobile Fixes

### 🚀 What's New in v5.0.2

1. **💰 Clipper Campaigns & Bounties Directory (#campaigns)**:
   - Dedicated monetization directory listing the top 10 verified platforms for podcast and streamer clippers to earn per-view payouts.
   - **Content Rewards** (#1 Pick, India + Worldwide open), **Vyro** (#2 Pick, MrBeast network), **Clipster** (#3 Pick, global gaming & music), plus India-specific hubs (**ClipGrow**, **ClipConnect India**).
   - Real-time search by creator/platform, instant category filters (All / India Eligible / Worldwide), and direct external links.

2. **🔴 Trending Streams & Gameplay Cockpit (#trending)**:
   - Live stream and viral gameplay discovery engine across **YouTube**, **Twitch**, and **Kick**.
   - Side-to-side responsive card cockpit displaying live stream viewers, broadcaster handles, and categories.
   - **1-Click "Clip This"**: Regular videos are automatically ingested into **Create Studio** (`#create`); live streams automatically launch **Live Studio** (`/live`) with rolling buffer capture ready.

3. **🎨 Caption Designs & Interactive Mouse Playground (#beta)**:
   - **7 Animated Caption Presets**: Viral Yellow Punch (`#FFE500`), Cyber Lime Green (`#39FF14`), Hormozi Bold White (`#FFD700`), TikTok Cyan Pop (`#00F2FE`), Crimson Fire (`#FF3344`), Typewriter Retro, and Neon Lavender.
   - **Mouse Drag & Alignment Snapping**: Drag the subtitle bounding box across a 9:16 vertical phone mockup with instant snapping guides (Top Safe 25%, Center Seam 50%, Lower Safe 75%).
   - **Dynamic Mouse Resizing**: Corner drag handle (`⤡`), mouse wheel scroll-to-resize, and direct font size slider (`24px` to `76px`) synced 1:1 with FFmpeg export scripts.

4. **🔘 Disable Captions Toggle & 18 Language Select in Beta**:
   - Easily toggle subtitle captions completely **OFF** with the new Subtitle Captions switch (`#betaCaptionsToggle`) for clean, watermark-free vertical shorts.
   - Multi-language transcription dropdown supporting 18 languages: English, Hindi (हिन्दी), Spanish (Español), French, German, Portuguese, Japanese (日本語), Korean, Chinese, Arabic, Russian, and Auto-Detect.

5. **🤖 Intelligent Clippy AI Assistant (v5.0.2 Knowledge Base)**:
   - Cleaned reasoning and monologue filters for local Ollama models (`qwen3:4b`).
   - Dynamic, non-static knowledge engine that answers detailed questions about campaigns, payouts, trending streams, caption styles, GPU acceleration, and deep-links directly in-app (`[NAVIGATE:...]`).

6. **📱 Android Mobile Companion App Fixes**:
   - Fixed asset paths to ensure 100% offline local WebView rendering.
   - Restored mobile-optimized fluid responsive layouts without horizontal clipping.
   - Dynamic device detection reading actual hardware specs (`Build.MANUFACTURER`, `Build.MODEL`, RAM, MediaCodec).

---

### 📦 Release Assets
- `Clipify.AI.Setup.5.0.2.exe`: Full offline Windows desktop installer.
- `update-v5.0.2.zip`: Fast in-place updater (downloaded automatically when clicking **Update** in the app).
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
        ("Clipify.AI.Setup.5.0.2.exe", r"L:\ClipifyAI\Clipify.AI.Setup.5.0.2.exe", "application/octet-stream"),
        ("update-v5.0.2.zip", r"L:\ClipifyAI\update-v5.0.2.zip", "application/zip"),
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

    print("\n[SUCCESS] GitHub Release v5.0.2 published successfully!")

if __name__ == "__main__":
    main()

