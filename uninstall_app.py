"""Standalone themed Black & White Uninstaller UI for Clipify AI (Windows)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DISCORD_URL = "https://discord.gg/5ZBsasgryX"


def _read_version() -> str:
    vf = ROOT / "version.json"
    if vf.is_file():
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
            return str(data.get("version", "6.0.13")).lstrip("v")
        except Exception:
            pass
    return "6.0.13"


def _find_app_browser() -> str | None:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _perform_uninstall(remove_outputs: bool, remove_ollama: bool, remove_cache: bool) -> str:
    notes: list[str] = []
    # 1. Stop running Clipify AI / Python servers inside ROOT
    if sys.platform == "win32":
        ps_kill = (
            f"$r='{str(ROOT).replace(chr(39), chr(39)*2)}';"
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.ProcessId -ne $PID -and ($_.ExecutablePath -like ($r + '*') -or $_.CommandLine -like ('*' + $r + '*')) "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_kill],
            capture_output=True, text=True, check=False,
        )

    # 2. Remove shortcuts
    appdata = os.environ.get("APPDATA", "")
    start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Clipify AI"
    if start_menu.exists():
        shutil.rmtree(start_menu, ignore_errors=True)
    desktop_lnk = Path.home() / "Desktop" / "Clipify AI.lnk"
    if desktop_lnk.is_file():
        try:
            desktop_lnk.unlink()
        except OSError:
            pass

    # 3. Optional removals
    user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "ClippedAI"
    if remove_outputs:
        for p in [ROOT / "output", ROOT / "jobs", user_data / "output", user_data / "jobs"]:
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
        notes.append("Removed generated Shorts & outputs.")

    if remove_cache:
        for p in [ROOT / "input", user_data / "input", user_data / "cache", user_data / "config.json"]:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        notes.append("Removed app settings & transcription cache.")

    if remove_ollama:
        ollama_dir = Path.home() / ".ollama"
        if ollama_dir.exists():
            shutil.rmtree(ollama_dir, ignore_errors=True)
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, check=False)
            subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"], capture_output=True, check=False)
            local_ollama = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "unins000.exe"
            if local_ollama.is_file():
                subprocess.Popen([str(local_ollama), "/VERYSILENT", "/NORESTART"])
        notes.append("Removed Ollama & downloaded AI models.")

    # 4. Remove Windows Uninstall registry entries
    if sys.platform == "win32":
        ps_reg = (
            "Remove-Item -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ClipifyAI' -Recurse -Force -ErrorAction SilentlyContinue;"
            "Remove-Item -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ClippedAI' -Recurse -Force -ErrorAction SilentlyContinue;"
            "Remove-Item -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Clipify AI' -Recurse -Force -ErrorAction SilentlyContinue;"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_reg],
            capture_output=True, text=True, check=False,
        )

    # 5. Remove application files (preserve non-empty user data unless all removed, and schedule self-delete)
    preserve_dirs = set()
    if not remove_outputs:
        preserve_dirs.update({"output", "jobs"})
    if not remove_cache:
        preserve_dirs.add("input")

    for item in list(ROOT.iterdir()):
        if item.name in preserve_dirs or item.name in {"runtime", "uninstall_app.py"}:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            pass

    # If user chose to remove everything (or runtime is inside ROOT), schedule delayed cleanup after server exits
    if sys.platform == "win32" and (ROOT / "runtime").exists():
        if remove_outputs and remove_cache:
            subprocess.Popen(
                ["cmd.exe", "/c", f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{ROOT}"'],
                creationflags=0x08000000,
            )
        else:
            subprocess.Popen(
                ["cmd.exe", "/c", f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{ROOT / "runtime"}" & del /f /q "{ROOT / "uninstall_app.py"}"'],
                creationflags=0x08000000,
            )

    notes.append("Removed Clipify AI application files and shortcuts.")
    return " ".join(notes)


def main() -> None:
    version = _read_version()
    html_template = (ROOT / "templates" / "uninstall.html").read_text(encoding="utf-8")
    rendered_html = (
        html_template.replace("{{VERSION}}", version)
        .replace("{{INSTALL_DIR}}", str(ROOT))
        .encode("utf-8")
    )

    server_ref: list[ThreadingHTTPServer] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

        def _send_json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/?"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(rendered_html)))
                self.end_headers()
                self.wfile.write(rendered_html)
            elif self.path == "/static/icon.png":
                icon_path = ROOT / "static" / "icon.png"
                if icon_path.is_file():
                    data = icon_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {}

            if self.path == "/api/open-discord":
                webbrowser.open(DISCORD_URL)
                self._send_json(200, {"ok": True})
            elif self.path == "/api/cancel":
                self._send_json(200, {"ok": True})
                threading.Timer(0.2, lambda: server_ref[0].shutdown()).start()
            elif self.path == "/api/uninstall":
                try:
                    summary = _perform_uninstall(
                        remove_outputs=bool(data.get("remove_outputs", False)),
                        remove_ollama=bool(data.get("remove_ollama", False)),
                        remove_cache=bool(data.get("remove_cache", False)),
                    )
                    self._send_json(200, {"ok": True, "summary": summary})
                    threading.Timer(4.0, lambda: server_ref[0].shutdown()).start()
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
            else:
                self.send_error(404)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_ref.append(httpd)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    browser = _find_app_browser()
    if browser:
        subprocess.Popen([browser, f"--app={url}", "--window-size=660,740"])
    else:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

