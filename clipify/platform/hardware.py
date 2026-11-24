"""
Clipify AI — Cross-Platform Hardware Acceleration Detector
Detects GPU encoders (NVENC, VideoToolbox, VAAPI, QSV) and configures optimal FFmpeg arguments.
"""

import subprocess
import sys
from typing import Dict, List, Optional
from .binary_locator import get_binary_locator

class HardwareAccelerator:
    def __init__(self):
        self.os_type = sys.platform
        self._detected_encoder: Optional[str] = None
        self._hwaccel_args: Optional[List[str]] = None

    def detect_best_encoder(self) -> Dict[str, any]:
        """Detects available hardware encoder and returns recommended flags."""
        if self._detected_encoder is not None:
            return {
                "encoder": self._detected_encoder,
                "args": self._hwaccel_args,
            }

        ffmpeg = get_binary_locator().find_ffmpeg()
        if not ffmpeg:
            return {"encoder": "libx264", "args": ["-preset", "veryfast"]}

        # Query available encoders from ffmpeg
        available_encoders = ""
        try:
            res = subprocess.run([ffmpeg, "-encoders"], capture_output=True, text=True, timeout=5)
            available_encoders = res.stdout
        except Exception:
            pass

        # Platform priority matrix
        if self.os_type == "darwin": # macOS (Apple Silicon & Intel)
            if "h264_videotoolbox" in available_encoders:
                self._detected_encoder = "h264_videotoolbox"
                self._hwaccel_args = ["-hwaccel", "videotoolbox", "-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}

        elif self.os_type.startswith("linux"): # Linux
            if "h264_nvenc" in available_encoders:
                self._detected_encoder = "h264_nvenc"
                self._hwaccel_args = ["-hwaccel", "cuda", "-preset", "p4", "-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}
            elif "h264_vaapi" in available_encoders:
                self._detected_encoder = "h264_vaapi"
                self._hwaccel_args = ["-vaapi_device", "/dev/dri/renderD128", "-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}
            elif "h264_qsv" in available_encoders:
                self._detected_encoder = "h264_qsv"
                self._hwaccel_args = ["-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}

        elif self.os_type == "win32": # Windows
            def _probe_encoder(enc, extra_args):
                try:
                    c = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.04", "-c:v", enc] + extra_args + ["-f", "null", "-"]
                    t = subprocess.run(c, capture_output=True, timeout=4)
                    return t.returncode == 0
                except Exception:
                    return False

            if "h264_nvenc" in available_encoders and _probe_encoder("h264_nvenc", ["-preset", "p4"]):
                self._detected_encoder = "h264_nvenc"
                self._hwaccel_args = ["-hwaccel", "cuda", "-preset", "p4", "-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}
            elif "h264_qsv" in available_encoders and _probe_encoder("h264_qsv", ["-b:v", "4000k"]):
                self._detected_encoder = "h264_qsv"
                self._hwaccel_args = ["-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}
            elif "h264_amf" in available_encoders and _probe_encoder("h264_amf", ["-b:v", "4000k"]):
                self._detected_encoder = "h264_amf"
                self._hwaccel_args = ["-b:v", "6500k"]
                return {"encoder": self._detected_encoder, "args": self._hwaccel_args}

        # Safe CPU fallback across all platforms
        self._detected_encoder = "libx264"
        self._hwaccel_args = ["-preset", "veryfast", "-crf", "22"]
        return {"encoder": self._detected_encoder, "args": self._hwaccel_args}

_accel_instance = None

def get_hardware_accelerator() -> HardwareAccelerator:
    global _accel_instance
    if _accel_instance is None:
        _accel_instance = HardwareAccelerator()
    return _accel_instance

