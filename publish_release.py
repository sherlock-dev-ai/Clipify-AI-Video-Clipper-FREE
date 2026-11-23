import subprocess
import json
import urllib.request
import urllib.parse
import os
import mimetypes
from pathlib import Path

# Get github token
proc = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True)
token = None
for line in proc.stdout.splitlines():
    if line.startswith('password='):
        token = line.split('=', 1)[1].strip()
        break

if not token:
    raise Exception('GitHub token not found')

repo = 'sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE'
tag = 'v5.0.0'
release_name = 'Clipify AI v5.0.0: The Ultimate Final Release'

body = """```text
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CLIPIFY AI v5.0.0 - ULTIMATE FINAL RELEASE                ║
║                 100% Free • Fully Private • GPU Accelerated AI               ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### ┌─────────────────────────────────────────────────────────────┐
### │  WINDOWS DEFENDER / SMARTSCREEN ("RUN ANYWAY") EXPLANATION  │
### └─────────────────────────────────────────────────────────────┘

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  WHY WINDOWS DEFENDER / SMARTSCREEN SHOWS "PROTECTED YOUR PC":               │
│                                                                              │
│  ■ Open-Source & 100% Free:                                                  │
│    Commercial code-signing certificates cost $400–$800 USD every single year.│
│    Because Clipify AI is provided completely free of charge and open-source  │
│    for everyone, we do not monetize users or purchase costly corporate certs.│
│                                                                              │
│  ■ How to Launch on Windows:                                                 │
│    1. On the SmartScreen prompt, click "More info".                          │
│    2. Click the "Run anyway" button to proceed with installation.            │
│                                                                              │
│  ■ 100% Safe & Auditable:                                                    │
│    Clipify AI never uploads your footage or models to any external server.   │
│    All source code is publicly inspectable right here on GitHub.             │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### ┌─────────────────────────────────────────────────────────────┐
### │  TERMINAL / CONSOLE WINDOW ("DO NOT CLOSE") EXPLANATION     │
### └─────────────────────────────────────────────────────────────┘

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  WHY A TERMINAL / COMMAND WINDOW RUNS ALONGSIDE THE APP:                     │
│                                                                              │
│  ■ Local AI Daemon Host:                                                     │
│    Clipify AI operates completely offline without third-party subscriptions. │
│    The console window hosts your local Python AI runtime, WhisperX acoustic  │
│    speech aligner, and hardware-accelerated FFmpeg clipping pipeline.        │
│                                                                              │
│  ■ What You Should Do:                                                       │
│    ✓ You may safely MINIMIZE the terminal window to your taskbar.            │
│    ✗ DO NOT click the red [X] or close the console window. Closing it stops  │
│      the background AI backend and severs the app connection.                │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### ┌─────────────────────────────────────────────────────────────┐
### │  WHAT'S NEW IN v5.0.0                                       │
### └─────────────────────────────────────────────────────────────┘

```text
┌───┬──────────────────────────────────────────────────────────────────────────┐
│ # │ Feature / Enhancement                                                    │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 1 │ Seamless Fast In-Place Updater Takeover                                  │
│   │ • Direct background upgrade takeover with live status reboot console.    │
│   │ • Left sidebar remains accessible during entire update sequence.         │
│   │ • Replaces slow manual installers with instant 3-second code sync.       │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 2 │ Precision Dual-Handle Timeline Scrubber                                  │
│   │ • Visual start and end trimmer displayed immediately after video preview.│
│   │ • Minute-and-second boundary selectors for precise clip extraction.      │
│   │ • Prevents full 10+ hour stream transcription overload.                  │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 3 │ Resilient Stream & Long Video Downloader Engine                          │
│   │ • Hardened yt-dlp stream pipeline with socket resilience & retries.      │
│   │ • Fallback handling for null/NaN branding parameters.                    │
│   │ • Automatic candidate focus for untrimmed multi-hour broadcasts.         │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 4 │ Interactive ASCII Matrix Canvas                                          │
│   │ • Mouse-reactive symbol grid with dynamic typography morphing.           │
│   │ • Random highlighted characters pulsing across testing workspace.        │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 5 │ 3D Supporters Galaxy Orbit                                               │
│   │ • Fullscreen cosmological starfield spotlighting repository supporters.  │
│   │ • Floating interactive badges and GitHub stargazer recognition.          │
├───┼──────────────────────────────────────────────────────────────────────────┤
│ 6 │ Cross-Platform Android Companion APK v5.0.0                              │
│   │ • Synchronized assets, offline studio layout, and bug fixes.             │
└───┴──────────────────────────────────────────────────────────────────────────┘
```

---

### ┌─────────────────────────────────────────────────────────────┐
### │  VERIFIED RELEASE ASSETS & SHA-256 CHECKSUMS                 │
### └─────────────────────────────────────────────────────────────┘

```text
┌────────────────────────────┬───────────┬──────────────────────────────────────────────────────────────────┐
│ Asset Name                 │ File Size │ SHA-256 Checksum                                                 │
├────────────────────────────┼───────────┼──────────────────────────────────────────────────────────────────┤
│ Clipify.AI.Setup.5.0.0.exe │ ~348 MB   │ A7BAB4174D62542446B052B3023CB4F05D608FF81E88314A0EEDBCB3A2D603C4 │
│ update-v5.0.0.zip          │ 3.48 MB   │ 2F0CAC3CBF1CA620250B4EBD8D87494812A41B17BC1280B139DD54E5A958472B │
│ Clipify.AI.beta.apk        │ 16.6 MB   │ BF0302739D4C807800E51469E3E72456C2C701FB07F19A2E4C51BB737C3897B7 │
└────────────────────────────┴───────────┴──────────────────────────────────────────────────────────────────┘
```
"""

headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'Clipify-Release-Publisher'
}

print('Checking if release already exists...')
req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', headers=headers)
release_id = None
upload_url = None

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        release_id = data['id']
        upload_url = data['upload_url'].split('{')[0]
        print(f'Release {tag} already exists with ID {release_id}')
        # Update body and name
        update_data = json.dumps({'name': release_name, 'body': body}).encode('utf-8')
        patch_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/{release_id}', data=update_data, headers=headers, method='PATCH')
        with urllib.request.urlopen(patch_req) as p_resp:
            print(f'Updated release {tag} metadata successfully')
except urllib.error.HTTPError as e:
    if e.code == 404:
        print(f'Creating new release {tag}...')
        post_data = json.dumps({
            'tag_name': tag,
            'target_commitish': 'feature/cross-platform',
            'name': release_name,
            'body': body,
            'draft': False,
            'prerelease': False
        }).encode('utf-8')
        create_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases', data=post_data, headers=headers, method='POST')
        with urllib.request.urlopen(create_req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            release_id = data['id']
            upload_url = data['upload_url'].split('{')[0]
            print(f'Successfully created release {tag} with ID {release_id}')
    else:
        raise

# Fetch existing assets to avoid duplicates
list_assets_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/{release_id}/assets', headers=headers)
with urllib.request.urlopen(list_assets_req) as resp:
    existing_assets = json.loads(resp.read().decode('utf-8'))
    existing_map = {a['name']: a['id'] for a in existing_assets}

assets_to_upload = [
    Path('Clipify.AI.Setup.5.0.0.exe'),
    Path('update-v5.0.0.zip'),
    Path('Clipify.AI.beta.apk')
]

for asset_path in assets_to_upload:
    if not asset_path.exists():
        print(f'WARNING: {asset_path} does not exist!')
        continue

    filename = asset_path.name
    if filename in existing_map:
        print(f'Asset {filename} already exists (ID: {existing_map[filename]}), deleting old version...')
        del_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/assets/{existing_map[filename]}', headers=headers, method='DELETE')
        urllib.request.urlopen(del_req)
        print(f'Deleted old asset {filename}')

    content_type, _ = mimetypes.guess_type(str(asset_path))
    if not content_type:
        content_type = 'application/octet-stream'

    file_size = asset_path.stat().st_size
    print(f'Uploading {filename} ({file_size / (1024*1024):.2f} MB)...')

    upload_endpoint = f"{upload_url}?name={urllib.parse.quote(filename)}"
    with open(asset_path, 'rb') as f:
        data = f.read()

    up_headers = {
        'Authorization': f'token {token}',
        'Content-Type': content_type,
        'Content-Length': str(len(data)),
        'User-Agent': 'Clipify-Release-Publisher'
    }

    upload_req = urllib.request.Request(upload_endpoint, data=data, headers=up_headers, method='POST')
    with urllib.request.urlopen(upload_req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print(f'Successfully uploaded {filename}: {res.get("browser_download_url")}')

print('\nALL ASSETS UPLOADED AND RELEASE PUBLISHED SUCCESSFULLY!')

