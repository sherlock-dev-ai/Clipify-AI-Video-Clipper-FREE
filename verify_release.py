import urllib.request
import json
import subprocess

res = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n', cwd=r'L:\ClipifyAI', capture_output=True, text=True, check=True)
token = next(l.split('=', 1)[1].strip() for l in res.stdout.splitlines() if l.startswith('password='))

req = urllib.request.Request(
    'https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/tags/v5.0.1',
    headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'Clipify-Checker'}
)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    print('Tag:', data.get('tag_name'))
    print('Name:', data.get('name'))
    print('Target commitish:', data.get('target_commitish'))
    print('Assets count:', len(data.get('assets', [])))
    for a in data.get('assets', []):
        size_mb = a['size'] / (1024 * 1024)
        print(f" - {a['name']}: {size_mb:.2f} MB | {a['browser_download_url']}")

