"""Isolated Narrate Studio workflow for Clipify AI."""

from .pipeline import NarratePipeline
from .tts import SapiTTS, available_voices

# Dynamically patch Flask routes when running in compiled Clipify AI.exe
try:
    import flask
    from flask import request, jsonify

    _orig_flask_init = flask.Flask.__init__

    def _hooked_flask_init(self, *args, **kwargs):
        _orig_flask_init(self, *args, **kwargs)

        @self.route("/api/publish/platforms", methods=["GET"])
        def _get_publish_platforms():
            try:
                from tools.mcp_publish import list_social_accounts
                return jsonify({"ok": True, "platforms": list_social_accounts()})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.route("/api/publish/credentials", methods=["POST"])
        def _save_publish_credentials():
            try:
                from tools.mcp_publish import load_credentials, save_credentials
                data = request.get_json(silent=True) or {}
                platform = str(data.get("platform", "")).lower()
                if platform not in {"youtube", "instagram", "tiktok"}:
                    return jsonify({"ok": False, "error": "Invalid platform specified."}), 400
                creds = load_credentials()
                if platform not in creds:
                    creds[platform] = {}
                for k, v in data.items():
                    if k != "platform" and v is not None:
                        creds[platform][k] = v
                save_credentials(creds)
                return jsonify({"ok": True, "message": f"{platform.capitalize()} credentials saved successfully."})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.route("/api/publish/upload", methods=["POST"])
        def _publish_short():
            try:
                from tools.mcp_publish import (
                    publish_youtube_short, publish_instagram_reel,
                    publish_tiktok_video, export_social_package
                )
                from pathlib import Path
                import os
                data = request.get_json(silent=True) or {}
                platform = str(data.get("platform", "youtube")).lower()
                job_id = str(data.get("job_id", "")).strip()
                filename = str(data.get("filename", "")).strip()
                title = str(data.get("title", "")).strip()
                description = str(data.get("description", "")).strip()
                privacy = str(data.get("privacy", "public")).strip()

                if not job_id or not filename:
                    return jsonify({"ok": False, "error": "Missing job_id or filename."}), 400

                # Locate video
                local_appdata = os.environ.get("LOCALAPPDATA", "")
                candidates = [
                    Path(local_appdata) / "ClippedAI" / "jobs" / job_id / "output" / filename,
                    Path("C:/Users/Dell/AppData/Local/Programs/ClipifyAI/jobs") / job_id / "output" / filename,
                    Path(r"L:\ClipifyAI\jobs") / job_id / "output" / filename,
                    Path(r"L:\ClipifyAI\output") / filename,
                ]
                video_path = None
                for c in candidates:
                    if c.is_file():
                        video_path = str(c)
                        break

                if not video_path:
                    return jsonify({"ok": False, "error": f"Video file not found: {filename}"}), 404

                if platform == "youtube":
                    res = publish_youtube_short(video_path, title=title, description=description, privacy=privacy)
                elif platform == "instagram":
                    caption = f"{title}\n\n{description}".strip()
                    res = publish_instagram_reel(video_path, caption=caption)
                elif platform == "tiktok":
                    title_text = f"{title} {description}".strip()
                    res = publish_tiktok_video(video_path, title=title_text, privacy=privacy)
                elif platform == "package":
                    out_dir = str(Path(video_path).parent / "social_exports")
                    res = export_social_package(video_path, title=title, description=description, output_dir=out_dir)
                else:
                    return jsonify({"ok": False, "error": f"Unsupported platform: {platform}"}), 400

                return jsonify(res)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

    flask.Flask.__init__ = _hooked_flask_init
except Exception as e:
    pass

__all__ = ["NarratePipeline", "SapiTTS", "available_voices"]
