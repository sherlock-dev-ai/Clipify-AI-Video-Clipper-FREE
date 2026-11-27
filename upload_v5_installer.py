import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.0"
ASSET_NAME = "Clipify.AI.Setup.5.0.0.exe"
FILE_PATH = r"L:\ClipifyAI\Clipify.AI.Setup.5.0.0.exe"

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
            print(f"[Upload Progress] {self.uploaded / (1024*1024):.1f} / {self.total / (1024*1024):.1f} MB ({pct}%)", flush=True)
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
        "Accept": "application/vnd.github.v3+json"
    }

    print(f"Connecting to release {TAG}...")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
        headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        release = json.loads(resp.read().decode())

    upload_url_template = release["upload_url"]
    base_upload_url = upload_url_template.split("{")[0]

    file_size = os.path.getsize(FILE_PATH)
    print(f"Checking {FILE_PATH} ({file_size / (1024*1024):.2f} MB)...")

    # Remove partial or outdated Setup asset if present
    for a in release.get("assets", []):
        if a["name"] == ASSET_NAME:
            print(f"Removing existing asset {ASSET_NAME} (ID: {a['id']})...")
            del_req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}",
                headers=headers,
                method="DELETE"
            )
            try:
                with urllib.request.urlopen(del_req):
                    print("Deleted old asset.")
            except Exception as de:
                print(f"Delete note: {de}")

    upload_url = f"{base_upload_url}?name={ASSET_NAME}"
    upload_headers = {
        "Authorization": f"token {token}",
        "User-Agent": "ClipifyAI-Release-Script",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_size)
    }

    for attempt in range(1, 4):
        print(f"\nStarting upload attempt {attempt}/3...")
        start_time = time.time()
        pf = ProgressFile(FILE_PATH)
        try:
            up_req = urllib.request.Request(upload_url, data=pf, headers=upload_headers, method="POST")
            with urllib.request.urlopen(up_req, timeout=3600) as resp:
                result = json.loads(resp.read().decode())
                elapsed = time.time() - start_time
                print(f"\nSUCCESS: Upload complete in {elapsed:.1f}s ({file_size / (1024*1024):.1f} MB)!")
                print(f"Asset URL: {result.get('browser_download_url')}")
                break
        except Exception as exc:
            print(f"\nAttempt {attempt} failed ({type(exc).__name__}: {exc}). Retrying in 5s...", flush=True)
            time.sleep(5)
        finally:
            pf.close()

    # Final Verification
    print("\nVerifying all assets on GitHub Release v5.0.0...")
    final_req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
        headers=headers
    )
    with urllib.request.urlopen(final_req) as resp:
        final_rel = json.loads(resp.read().decode())
        print(f"Release: {final_rel.get('name')} ({final_rel.get('tag_name')})")
        for a in final_rel.get("assets", []):
            print(f"  ✓ {a['name']} ({a['size'] / (1024*1024):.2f} MB) - {a['browser_download_url']}")

if __name__ == "__main__":
    main()

