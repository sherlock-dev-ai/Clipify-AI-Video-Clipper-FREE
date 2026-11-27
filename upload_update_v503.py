import urllib.request
import json
import subprocess
import os

proc = subprocess.run(
    ['git', 'credential', 'fill'],
    input='protocol=https\nhost=github.com\n\n',
    text=True,
    capture_output=True
)
token = ''
for line in proc.stdout.splitlines():
    if line.startswith('password='):
        token = line.split('=', 1)[1]

headers = {
    'Authorization': f'token {token}',
    'User-Agent': 'ClipifyAI-Uploader',
    'Accept': 'application/vnd.github.v3+json'
}

req = urllib.request.Request(
    'https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/tags/v5.0.3',
    headers=headers
)
with urllib.request.urlopen(req) as res:
    rel = json.loads(res.read().decode())

upload_url_template = rel['upload_url']
base_upload = upload_url_template.split('{')[0]

# Delete old update-v5.0.3.zip asset if exists
for a in rel.get('assets', []):
    if a.get('name') == 'update-v5.0.3.zip':
        asset_id = a.get('id')
        print(f"Deleting old asset {asset_id}...")
        d_req = urllib.request.Request(
            f'https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/assets/{asset_id}',
            headers=headers,
            method='DELETE'
        )
        with urllib.request.urlopen(d_req) as d_res:
            print("Deleted old zip.")

# Upload new update-v5.0.3.zip
zip_path = r'L:\ClipifyAI\update-v5.0.3.zip'
size = os.path.getsize(zip_path)
print(f"Uploading {zip_path} ({size} bytes)...")
with open(zip_path, 'rb') as f:
    up_data = f.read()

up_headers = {
    'Authorization': f'token {token}',
    'User-Agent': 'ClipifyAI-Uploader',
    'Content-Type': 'application/zip',
    'Content-Length': str(size)
}
up_req = urllib.request.Request(
    f"{base_upload}?name=update-v5.0.3.zip",
    data=up_data,
    headers=up_headers,
    method='POST'
)
with urllib.request.urlopen(up_req) as up_res:
    print("SUCCESS: update-v5.0.3.zip uploaded successfully!")

