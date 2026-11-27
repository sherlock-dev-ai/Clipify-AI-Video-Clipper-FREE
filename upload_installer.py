import subprocess
import json
import urllib.request
import urllib.parse
from pathlib import Path

proc = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True)
token = [l.split('=', 1)[1].strip() for l in proc.stdout.splitlines() if l.startswith('password=')][0]

repo = 'sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE'
tag = 'v5.0.0'
headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'Clipify-Release-Publisher'
}

print('Fetching release info...')
req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', headers=headers)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    release_id = data['id']
    upload_url = data['upload_url'].split('{')[0]

# Check existing
for a in data.get('assets', []):
    if a['name'] == 'Clipify.AI.Setup.5.0.0.exe':
        print(f"Deleting old Setup asset (ID: {a['id']})...")
        del_req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}", headers=headers, method='DELETE')
        urllib.request.urlopen(del_req)
        print('Deleted old Setup.')

asset_path = Path('Clipify.AI.Setup.5.0.0.exe')
file_size = asset_path.stat().st_size
print(f'Reading {asset_path} ({file_size / (1024*1024):.2f} MB)...')
with open(asset_path, 'rb') as f:
    data_bytes = f.read()

upload_endpoint = f'{upload_url}?name=Clipify.AI.Setup.5.0.0.exe'
up_headers = {
    'Authorization': f'token {token}',
    'Content-Type': 'application/octet-stream',
    'Content-Length': str(len(data_bytes)),
    'User-Agent': 'Clipify-Release-Publisher'
}

print('Uploading Clipify.AI.Setup.5.0.0.exe to GitHub release...')
upload_req = urllib.request.Request(upload_endpoint, data=data_bytes, headers=up_headers, method='POST')
with urllib.request.urlopen(upload_req) as resp:
    res = json.loads(resp.read().decode('utf-8'))
    print('SUCCESS! Uploaded to:', res.get('browser_download_url'))

# Print final asset summary
summary_req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', headers=headers)
with urllib.request.urlopen(summary_req) as resp:
    summary_data = json.loads(resp.read().decode('utf-8'))
    print('\nFinal Verified Assets in Release v5.0.0:')
    for a in summary_data.get('assets', []):
        print(f"  ✓ {a['name']} ({a['size']} bytes) - {a['browser_download_url']}")

