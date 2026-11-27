import os
import sys
import json
import subprocess
import urllib.request
import urllib.error

REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"
TAG = "v5.0.3"
ASSET_NAME = "Clipify.AI.Setup.5.0.3.exe"
FILE_PATH = r"L:\ClipifyAI\Clipify.AI.Setup.5.0.3.exe"

def get_token():
    proc = subprocess.run(
        ['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n',
        text=True,
        capture_output=True
    )
    for line in proc.stdout.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    return ''

def main():
    token = get_token()
    if not token:
        print("ERROR: No token found")
        sys.exit(1)

    headers = {
        'Authorization': f'token {token}',
        'User-Agent': 'ClipifyAI-Uploader',
        'Accept': 'application/vnd.github.v3+json'
    }

    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
        headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        release = json.loads(resp.read().decode())

    print(f"Release: {release['name']}")
    for a in release.get("assets", []):
        print(f"  Existing asset: {a['name']} ({a['size']} bytes, ID: {a['id']})")
        if a["name"] == ASSET_NAME:
            print(f"Deleting partial asset {a['id']}...")
            del_req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}",
                headers=headers,
                method="DELETE"
            )
            try:
                with urllib.request.urlopen(del_req):
                    print("Deleted.")
            except Exception as e:
                print(f"Delete note: {e}")

    upload_url_template = release["upload_url"]
    base_upload_url = upload_url_template.split("{")[0]
    upload_url = f"{base_upload_url}?name={ASSET_NAME}"

    file_size = os.path.getsize(FILE_PATH)
    print(f"\nUploading {FILE_PATH} ({file_size / (1024*1024):.1f} MB) via curl.exe...")

    cmd = [
        "curl.exe",
        "-X", "POST",
        "-H", f"Authorization: token {token}",
        "-H", "User-Agent: ClipifyAI-Uploader",
        "-H", "Content-Type: application/octet-stream",
        "--data-binary", f"@{FILE_PATH}",
        "--retry", "5",
        "--retry-delay", "5",
        "--retry-all-errors",
        "--progress-bar",
        upload_url
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode == 0:
        try:
            res = json.loads(p.stdout)
            print("SUCCESS! Asset ID:", res.get("id"))
            print("Download URL:", res.get("browser_download_url"))
        except Exception:
            print("Upload completed, output:", p.stdout[:200])
    else:
        print("curl failed with code:", p.returncode)
        print("STDERR:", p.stderr)
        print("STDOUT:", p.stdout)

if __name__ == '__main__':
    main()

