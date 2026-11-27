"""
Clipify AI — Unified GPU and Hardware Accelerator Manager
Detects all system GPUs (Discrete NVIDIA, Integrated Intel/AMD, and CPU mode).
Allows seamless switching of active GPU across PyTorch, CTranslate2, WhisperX, Ollama, and FFmpeg.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("clipify.gpu")

CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "ClipifyAI" / "gpu_config.json"


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def detect_all_gpus() -> List[Dict[str, Any]]:
    """Detect all physical GPU adapters and CPU fallback on the machine."""
    gpus: List[Dict[str, Any]] = []

    # 1. Query NVIDIA GPUs via nvidia-smi if available
    nvidia_gpus = []
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,gpu_name,memory.total,memory.free,memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_hidden_flags()
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    idx = int(parts[0])
                    name = parts[1]
                    tot_mb = float(parts[2])
                    free_mb = float(parts[3])
                    temp = parts[5]
                    vram_str = f"{tot_mb / 1024:.1f} GB"
                    nvidia_gpus.append({
                        "id": f"gpu{idx}",
                        "name": name,
                        "vendor": "nvidia",
                        "type": "discrete",
                        "vram": vram_str,
                        "free_vram": f"{free_mb / 1024:.1f} GB",
                        "temp": f"{temp}°C",
                        "index": idx,
                        "recommended": True,
                    })
    except Exception as e:
        logger.debug("nvidia-smi check skipped: %s", e)

    # 2. Query Windows CIM/WMI for all video controllers
    other_controllers = []
    if sys.platform == "win32":
        try:
            ps_cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name, AdapterRAM, DriverVersion | "
                "ConvertTo-Json"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_hidden_flags()
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = str(item.get("Name", "")).strip()
                    if not name:
                        continue
                    # Skip if already identified as NVIDIA GPU
                    if any(nv["name"].lower() in name.lower() or name.lower() in nv["name"].lower() for nv in nvidia_gpus):
                        continue
                    
                    adapter_ram = item.get("AdapterRAM", 0)
                    ram_mb = (adapter_ram or 0) / (1024 * 1024)
                    ram_str = f"{ram_mb / 1024:.1f} GB" if ram_mb > 0 else "Shared"
                    
                    is_intel = "intel" in name.lower()
                    is_amd = "amd" in name.lower() or "radeon" in name.lower()
                    vendor = "intel" if is_intel else ("amd" if is_amd else "generic")
                    
                    other_controllers.append({
                        "id": f"gpu_other_{len(other_controllers)}",
                        "name": name,
                        "vendor": vendor,
                        "type": "integrated" if is_intel else "discrete",
                        "vram": ram_str,
                        "index": -1,
                        "recommended": False,
                    })
        except Exception as e:
            logger.debug("Windows VideoController check skipped: %s", e)

    # Add NVIDIA GPUs first (highest performance priority)
    gpus.extend(nvidia_gpus)

    # Add other adapters (e.g. Intel UHD Graphics)
    for c in other_controllers:
        c["id"] = f"gpu{len(gpus)}"
        gpus.append(c)

    # Add CPU Compute Mode fallback
    gpus.append({
        "id": "cpu",
        "name": "CPU Compute Mode",
        "vendor": "cpu",
        "type": "cpu",
        "vram": "System RAM",
        "index": -1,
        "recommended": len(gpus) == 0,
    })

    return gpus


def get_active_gpu_id() -> str:
    """Retrieve the user-selected active GPU id, defaulting to discrete GPU."""
    try:
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            active = data.get("active_gpu")
            if active:
                return str(active)
    except Exception:
        pass

    # Default to first available GPU (prefer discrete NVIDIA)
    all_gpus = detect_all_gpus()
    for g in all_gpus:
        if g.get("vendor") == "nvidia":
            return g["id"]
    return all_gpus[0]["id"] if all_gpus else "cpu"


def apply_gpu_selection(gpu_id: str) -> Dict[str, Any]:
    """Apply the chosen GPU across system environment variables and libraries."""
    all_gpus = detect_all_gpus()
    chosen = next((g for g in all_gpus if g["id"] == gpu_id), None)
    if not chosen:
        chosen = all_gpus[0]
        gpu_id = chosen["id"]

    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"active_gpu": gpu_id}, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not persist gpu_config.json: %s", e)

    # Apply environment variables
    if chosen["vendor"] == "nvidia" and chosen["index"] >= 0:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(chosen["index"])
        os.environ["CLIPIFY_ACTIVE_GPU"] = gpu_id
        os.environ["CLIPIFY_GPU_VENDOR"] = "nvidia"
        os.environ["CLIPIFY_GPU_NAME"] = chosen["name"]
    elif chosen["vendor"] == "intel":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["CLIPIFY_ACTIVE_GPU"] = gpu_id
        os.environ["CLIPIFY_GPU_VENDOR"] = "intel"
        os.environ["CLIPIFY_GPU_NAME"] = chosen["name"]
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["CLIPIFY_ACTIVE_GPU"] = "cpu"
        os.environ["CLIPIFY_GPU_VENDOR"] = "cpu"
        os.environ["CLIPIFY_GPU_NAME"] = "CPU Compute Mode"

    # Configure PyTorch device if loaded
    try:
        import torch
        if chosen["vendor"] == "nvidia" and torch.cuda.is_available() and chosen["index"] >= 0:
            torch.cuda.set_device(chosen["index"])
    except Exception:
        pass

    logger.info("Active accelerator switched to: %s (%s)", chosen["name"], chosen["vram"])
    return chosen


def get_ffmpeg_video_encoder_flags(bitrate: str = "12M", preset: str = "fast", crf: int = 18) -> List[str]:
    """Return the optimal FFmpeg encoding flags according to user's selected GPU."""
    active_id = get_active_gpu_id()
    all_gpus = detect_all_gpus()
    active_gpu = next((g for g in all_gpus if g["id"] == active_id), None)
    vendor = active_gpu.get("vendor", "cpu") if active_gpu else "cpu"

    if vendor == "nvidia":
        # Hardware NVENC on discrete NVIDIA GPU
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-cq", str(max(14, crf)),
            "-b:v", bitrate,
            "-maxrate", "20M",
            "-bufsize", "30M",
            "-pix_fmt", "yuv420p"
        ]
    elif vendor == "intel":
        # Hardware Quick Sync Video on Intel Integrated GPU
        return [
            "-c:v", "h264_qsv",
            "-preset", "fast",
            "-global_quality", str(max(18, crf + 2)),
            "-b:v", bitrate,
            "-maxrate", "18M",
            "-bufsize", "24M",
            "-pix_fmt", "nv12"
        ]
    else:
        # Software encoding via libx264
        return [
            "-c:v", "libx264",
            "-preset", preset or "veryfast",
            "-crf", str(crf),
            "-b:v", bitrate,
            "-maxrate", "16M",
            "-bufsize", "20M",
            "-pix_fmt", "yuv420p"
        ]


def get_whisper_device_and_type() -> tuple[str, str]:
    """Return (device, compute_type) for Faster-Whisper / CTranslate2."""
    active_id = get_active_gpu_id()
    all_gpus = detect_all_gpus()
    active_gpu = next((g for g in all_gpus if g["id"] == active_id), None)
    vendor = active_gpu.get("vendor", "cpu") if active_gpu else "cpu"

    if vendor == "nvidia":
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return ("cuda", "float16")
        except Exception:
            pass
        try:
            import torch
            if torch.cuda.is_available():
                return ("cuda", "float16")
        except Exception:
            pass
    return ("cpu", "int8")


def get_gpu_status() -> Dict[str, Any]:
    """Return JSON status of all GPUs and current selection."""
    all_gpus = detect_all_gpus()
    active_id = get_active_gpu_id()
    for g in all_gpus:
        g["active"] = (g["id"] == active_id)
    active_obj = next((g for g in all_gpus if g["id"] == active_id), all_gpus[0] if all_gpus else None)
    return {
        "ok": True,
        "active_gpu": active_id,
        "active": active_obj,
        "gpus": all_gpus,
    }


