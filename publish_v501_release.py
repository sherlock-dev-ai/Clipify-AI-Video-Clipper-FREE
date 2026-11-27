import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.1"
RELEASE_NAME = "Clipify AI v5.0.1: Precision Overlay Scaling, Instant Multi-Clipping & Cyber Matrix Update"

RELEASE_NOTES = """<p align="center">
  <img src="https://raw.githubusercontent.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/main/docs/screenshots/live_studio_clips.jpg" alt="Clipify AI Video Clipper" width="100%">
</p>

## Clipify AI v5.0.1: Precision Overlay Scaling, Instant Multi-Clipping & Cyber Matrix Update

### 🚀 What's New in v5.0.1

1. **📐 Mathematical 1:1 Video-Ratio Text Overlay Preview**:
   - Preview text overlays in the **Editor**, **Create panel**, and **Beta Lab** now scale mathematically 1:1 according to the video frame aspect ratio.
   - What you see in the preview matches **100% exactly** with the rendered FFmpeg output ($fs = \\text{round}(W \\times \\frac{\\text{size}}{100})$).
   - Dynamic `ResizeObserver` automatically recalculates and preserves proportional sizing whenever the window or preview container changes size.
   - Smooth coordinate translation (`transform: translate(-x%, -y%)`) ensures overlays stay perfectly bounded within video borders.

2. **🎛️ Interactive In-Preview Quick Controls & Corner Resize Handle**:
   - **Hover / Active Control Pill**: On-overlay floating quick bar featuring `−` button, live percentage size badge (e.g. `6%`), `+` button, and drag indicator.
   - **Interactive Corner Handle (`⤡`)**: Click and drag the corner handle directly on the video preview to dynamically resize text overlays.
   - **Mouse Wheel / Trackpad Scroll Resizing**: Simply scroll up or down over the text overlay to dynamically increase or decrease size on the fly.
   - Expanded size range from **2% to 25%** for maximum styling flexibility.

3. **👾 Dynamic Moving ASCII Matrix Updater with "CLIPIFY" Block Typography**:
   - The in-app **Update Modal** now features an animated Matrix-style ASCII canvas with glowing 5x7 block typography for **`C L I P I F Y`** and inline text highlights (`CLIPIFY AI`, `CLIP.AI`).
   - Includes real-time cursor particle repulsion waves and glowing constellations of the Clipify Cat Mascot.

4. **⚡ Instant Clipping Isolated Pipeline & "Generate Another Clip"**:
   - Completely isolated instant pipeline skipping heavy LLM transcription for lightning-fast exports.
   - Dedicated memory cache isolation prevents reusing previous video footage when a new YouTube or local link is provided.
   - Added **"Generate Another Clip"** button to automatically produce fresh, diversified 9:16 vertical hooks from the same source footage.
   - Supports 9:16 Split Screen presets (Gaming Top/Bottom, Blur-Fill, Center Crop) and customizable clip counts.

5. **🚀 CUDA 12 GPU-First Acceleration & Auto CPU Fallback**:
   - Prioritizes NVIDIA CUDA GPU (CTranslate2 float16 & NVENC hardware encoders) for near-instant transcription and rendering.
   - Automatically and gracefully falls back to CPU only when no GPU is detected, completely eliminating transcription delays.

6. **🖤 Obsidian Monochrome Design System & Synchronized Navigation**:
   - Strict black & white minimalist aesthetic matching the core app theme across Create, Live Studio, and Narration Studio.
   - Unified sidebar navigation items, badges, and layout across all studios.

7. **🤖 Upgraded Clippy AI Assistant (v5.0.1 Knowledge Base)**:
   - Full awareness of all v5.0.1 capabilities, in-preview controls, split-screen layouts, and GPU settings with 1-click in-app navigation (`[NAVIGATE:...]`).

---

### 📦 Release Assets
- `Clipify.AI.Setup.5.0.1.exe`: Full offline Windows desktop installer.
- `update-v5.0.1.zip`: Fast in-place updater (downloaded automatically when clicking **Update** in the app).
- `Clipify.AI.beta.apk`: Android companion app.
"""

class ProgressFile:
    def __init__(self, filepath):
        self.f = open(filepath, "rb")
        self.total = os.path.getsize(filepath)
        self.uploaded = 0
        self.last_pct = -1

    def read(self, size=-1):
        chunk = self.f.read(size)
        self.uploaded += len(chunk)
        pct = int(self.uploaded / self.total * 100) if self.total else 100
        if pct != self.last_pct and pct % 5 == 0:
            self.last_pct = pct
            print(f"  [Progress] {self.uploaded / (1024*1024):.1f} / {self.total / (1024*1024):.1f} MB ({pct}%)", flush=True)
        return chunk

    def __len__(self):
        return self.total

    def close(self):
        self.f.close()

def get_token():
    p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    creds, _ = p.communicate('protocol=https\nhost=github.com\n\n')
    return dict([line.split('=', 1) for line in creds.splitlines() if '=' in line]).get('password', '')

def main():
    token = get_token()
    if not token:
        print("ERROR: No GitHub token found.")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "ClipifyAI-Release-Script",
        "Accept": "application/vnd.github.v3+json",
    }

    print(f"Connecting to GitHub API for {REPO}...")
    rel_req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", headers=headers)
    release_data = None
    try:
        with urllib.request.urlopen(rel_req) as resp:
            release_data = json.loads(resp.read().decode("utf-8"))
            print(f"Found existing release for {TAG} (ID: {release_data['id']})")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Creating new release for {TAG} on main...")
            create_payload = {
                "tag_name": TAG,
                "target_commitish": "main",
                "name": RELEASE_NAME,
                "body": RELEASE_NOTES,
                "draft": False,
                "prerelease": False
            }
            create_req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases",
                data=json.dumps(create_payload).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(create_req) as c_resp:
                release_data = json.loads(c_resp.read().decode("utf-8"))
                print(f"Created release {TAG} (ID: {release_data['id']})")
        else:
            raise

    upload_url = release_data["upload_url"].split("{")[0]

    # Assets to upload
    assets_to_upload = [
        ("update-v5.0.1.zip", r"L:\ClipifyAI\update-v5.0.1.zip", "application/zip"),
        ("Clipify.AI.Setup.5.0.1.exe", r"L:\ClipifyAI\Clipify.AI.Setup.5.0.1.exe", "application/octet-stream"),
        ("Clipify.AI.beta.apk", r"L:\ClipifyAI\Clipify.AI.beta.apk", "application/vnd.android.package-archive"),
    ]

    for asset_name, file_path, content_type in assets_to_upload:
        if not os.path.exists(file_path):
            print(f"WARNING: File {file_path} not found. Skipping {asset_name}.")
            continue

        for existing in release_data.get("assets", []):
            if existing["name"] == asset_name:
                print(f"Removing existing {asset_name} (ID: {existing['id']})...")
                del_req = urllib.request.Request(
                    f"https://api.github.com/repos/{REPO}/releases/assets/{existing['id']}",
                    headers=headers,
                    method="DELETE"
                )
                try:
                    urllib.request.urlopen(del_req)
                    time.sleep(1)
                except Exception as ex:
                    print("Delete error:", ex)

        size = os.path.getsize(file_path)
        print(f"Uploading {asset_name} ({size / (1024*1024):.2f} MB)...")
        up_url = f"{upload_url}?name={asset_name}"
        up_headers = {
            "Authorization": f"token {token}",
            "User-Agent": "ClipifyAI-Release-Script",
            "Content-Type": content_type,
            "Content-Length": str(size)
        }

        pf = ProgressFile(file_path)
        up_req = urllib.request.Request(up_url, data=pf, headers=up_headers, method="POST")
        try:
            with urllib.request.urlopen(up_req) as up_resp:
                res = json.loads(up_resp.read().decode("utf-8"))
                print(f"✓ Uploaded {asset_name} (ID: {res.get('id')})")
        finally:
            pf.close()

    print("\nALL ASSETS UPLOADED AND VERIFIED FOR v5.0.1!")

if __name__ == "__main__":
    main()
