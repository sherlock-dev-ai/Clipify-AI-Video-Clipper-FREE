import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(r"L:\ClipifyAI")
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
ANDROID_WWW = ROOT / "android" / "app" / "src" / "main" / "assets" / "www"
ANDROID_STATIC = ANDROID_WWW / "static"

print("[Android Sync] Syncing static assets...")
ANDROID_STATIC.mkdir(parents=True, exist_ok=True)
for item in STATIC.iterdir():
    if item.is_file():
        shutil.copy2(item, ANDROID_STATIC / item.name)
print(f"[Android Sync] Copied {len(list(STATIC.iterdir()))} static files to Android assets.")

# Render Jinja2 templates cleanly via jinja2.Environment so no raw {{...}} or {%...%} tags remain
from jinja2 import Environment, FileSystemLoader

MODES = {
    "gaming": {"name": "Gaming", "icon": "🎮", "description": "Gameplay + facecam reactions with stable smart framing"},
    "viral": {"name": "Viral", "icon": "✦", "description": "Hooks, curiosity, surprise & payoff"},
    "funny": {"name": "Funny", "icon": "😂", "description": "Punchlines, reactions & comedic timing"},
    "dramatic": {"name": "Dramatic", "icon": "⚡", "description": "Tension, reveals & emotional moments"},
    "educational": {"name": "Educational", "icon": "◈", "description": "Facts, explanations & takeaways"},
    "story": {"name": "Story", "icon": "◉", "description": "Setup → escalation → payoff"},
    "meme": {"name": "Meme", "icon": "💀", "description": "Chaotic, absurd & reaction-heavy"},
}

def rewrite_static_urls(html_text: str) -> str:
    # Convert /static/foo.js?v=... or /static/foo.js to static/foo.js
    cleaned = re.sub(
        r"""(["'])/static/([^"'?#]+)(?:\?[^"']*)?(["'])""",
        r"\1static/\2\3",
        html_text,
    )
    # Rewrite root-relative page links so file:///android_asset/www/ navigation never goes blank
    cleaned = cleaned.replace('href="/"', 'href="index.html"')
    cleaned = cleaned.replace('href="/live"', 'href="live.html"')
    cleaned = cleaned.replace('href="/narrate"', 'href="narrate.html"')
    cleaned = re.sub(r'href="/#([^"]+)"', r'href="index.html#\1"', cleaned)
    return cleaned

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
jinja_env.globals["url_for"] = lambda endpoint, **kw: f"static/{kw['filename']}" if endpoint == "static" and "filename" in kw else f"/{endpoint}"

TEMPLATE_CTX = {
    "index.html": {"modes": MODES},
    "live.html": {},
    "narrate.html": {},
}

for tpl_name, ctx in TEMPLATE_CTX.items():
    content = jinja_env.get_template(tpl_name).render(**ctx)
    content = rewrite_static_urls(content)

    # Ensure viewport is mobile-optimized
    content = content.replace(
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">'
    )

    # Inject mobile.css for standalone mobile experience
    if "</head>" in content and "mobile.css" not in content:
        content = content.replace("</head>", '  <link rel="stylesheet" href="static/mobile.css">\n</head>')

    dest_path = ANDROID_WWW / tpl_name
    dest_path.write_text(content, encoding="utf-8")
    print(f"[Android Sync] Rendered and wrote {tpl_name} -> {dest_path}")

print("[Android Sync] Completed successfully!")

