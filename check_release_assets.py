import urllib.request
import json
import subprocess

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
    'User-Agent': 'ClipifyAI',
    'Accept': 'application/vnd.github.v3+json'
}
req = urllib.request.Request(
    'https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/tags/v5.0.3',
    headers=headers
)
with urllib.request.urlopen(req) as res:
    rel = json.loads(res.read().decode())
    print("Release assets:")
    for a in rel.get('assets', []):
        print(f"  - {a['name']}: {a['size']} bytes ({a.get('state')})")

