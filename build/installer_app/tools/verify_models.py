"""Verifies that every model the installer catalog offers really exists in the
Ollama registry and reports its real download size.

The catalog must not invent identifiers, so this queries the public registry's
manifest endpoint (the ``tags/list`` endpoint does not exist) and sums the
model layer sizes. Sizes come from the registry, never from hardcoded numbers.

Run this before trusting any change to the catalog.

Usage: python tools/verify_models.py [name[:tag] ...]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

MANIFEST = "https://registry.ollama.ai/v2/library/{name}/manifests/{tag}"
HEADERS = {
    "User-Agent": "ClipifyAI-Setup/2.0",
    "Accept": "application/vnd.docker.distribution.manifest.v2+json",
}

CANDIDATES = [
    "qwen3:4b", "qwen3:8b", "qwen3:14b", "qwen3:32b",
    "qwen2.5:14b", "llama3.2:3b", "llama3.1:8b", "gemma3:4b",
    "gemma3:12b", "mistral:7b", "mistral-small:24b", "phi4:14b",
    "deepseek-r1:8b", "deepseek-r1:14b", "command-r:35b",
    "granite3.3:8b", "llama3.3:70b", "gpt-oss:20b", "codellama:13b",
]


def manifest(name: str, tag: str) -> dict | None:
    url = MANIFEST.format(name=name, tag=tag)
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        print(f"  ! {name}:{tag} -> HTTP {error.code}")
    except Exception as error:  # noqa: BLE001 - diagnostic path
        print(f"  ! {name}:{tag} -> {error}")
    return None


def weight_bytes(document: dict) -> int:
    """Sum only real weight layers, skipping tiny template/tokenizer files."""
    total = 0
    for layer in document.get("layers") or []:
        media = layer.get("mediaType", "")
        if media.startswith("application/vnd.ollama.image.model"):
            total += int(layer.get("size") or 0)
    return total


def main(argv: list[str]) -> int:
    names = argv[1:] or CANDIDATES
    print(f"{'model':22} {'pullable':9} {'weights':>12}")
    print("-" * 46)
    good = []
    for full in names:
        base, _, tag = full.partition(":")
        tag = tag or "latest"
        document = manifest(base, tag)
        if not document:
            print(f"{full:22} {'NO':9} {'-':>12}")
            continue
        size = weight_bytes(document)
        print(f"{full:22} {'yes':9} {size / 1e9:>11.2f} GB")
        good.append((full, size))

    print()
    print(f"{len(good)}/{len(names)} pullable")
    for full, size in good:
        print(f"  {full:22} {size / 1e9:.2f} GB")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))