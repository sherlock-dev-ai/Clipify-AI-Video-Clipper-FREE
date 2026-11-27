import os
import sys
import subprocess
import json
import urllib.request
import urllib.parse
import shutil

apk_source = r"L:\ClipifyAI\android\app\build\outputs\apk\debug\app-debug.apk"
apk_target = r"L:\ClipifyAI\Clipify.AI.beta.apk"

if not os.path.exists(apk_source):
    print(f"Error: {apk_source} does not exist yet.")
    sys.exit(1)

shutil.copy2(apk_source, apk_target)
size_mb = os.path.getsize(apk_target) / (1024 * 1024)
print(f"Copied APK to {apk_target} ({size_mb:.2f} MB)")

# Retrieve token from git credential helper
res = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n", capture_output=True, text=True, check=True)
token = None
for line in res.stdout.splitlines():
    if line.startswith("password="):
        token = line.split("=", 1)[1].strip()

if not token:
    print("Error: Could not retrieve GitHub token.")
    sys.exit(1)

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Clipify-Updater"
}

# Fetch release v5.0.1
req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/tags/v5.0.1", headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        rel = json.loads(resp.read().decode("utf-8"))
        release_id = rel["id"]
        upload_url = rel["upload_url"].split("{")[0]
        assets = rel.get("assets", [])
        print(f"Found release {rel['tag_name']} (ID: {release_id})")
except Exception as e:
    print(f"Error getting release: {e}")
    sys.exit(1)

# Delete existing Clipify.AI.beta.apk asset if present
asset_name = "Clipify.AI.beta.apk"
for asset in assets:
    if asset["name"] == asset_name:
        del_req = urllib.request.Request(asset["url"], headers=headers, method="DELETE")
        urllib.request.urlopen(del_req)
        print(f"Deleted old asset {asset_name} (ID: {asset['id']})")

# Upload new APK
with open(apk_target, "rb") as f:
    apk_data = f.read()

up_url = f"{upload_url}?name={urllib.parse.quote(asset_name)}"
up_headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/vnd.android.package-archive",
    "User-Agent": "Clipify-Updater"
}

print(f"Uploading {asset_name} ({len(apk_data)} bytes)...")
up_req = urllib.request.Request(up_url, data=apk_data, headers=up_headers, method="POST")
with urllib.request.urlopen(up_req) as resp:
    res_data = json.loads(resp.read().decode("utf-8"))
    print(f"Uploaded successfully! Asset ID: {res_data['id']}, URL: {res_data['browser_download_url']}")

