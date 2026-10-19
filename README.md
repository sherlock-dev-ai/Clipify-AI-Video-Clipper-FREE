# Clipify AI 2.0.0 Preview

Clipify AI is a Windows desktop application for turning longer footage into vertical clips and creating script-led narration videos.

**Website:** [ai.projectclipzy.workers.dev](https://ai.projectclipzy.workers.dev/)<br>
**Download:** [Windows x64 preview installer](https://github.com/sherlock-dev-ai/Clipify-AI/releases/download/v2.0.0-preview.20261018/Clipify%20AI%20Setup-20261018-205733-726.exe)

## Screenshots

| Clipping dashboard | Narration studio |
|---|---|
| ![Clipify AI clipping dashboard](docs/screenshots/dashboard.png) | ![Clipify AI narration interface](docs/screenshots/narration.png) |

### Website

![Clipify AI project website](docs/screenshots/website.png)

The website hero image includes an illustrative motion-graphic concept; it is not an in-app screen.

## What it does

- Finds candidate moments in longer videos and renders vertical clips with timed captions.
- Offers clipping styles for Gaming, Viral, Funny, Dramatic, Educational, and Story content.
- Provides a separate narration workflow for script editing or generation, voice selection, background footage, and rendered narration videos.
- Can use Qwen through a configured local Ollama service for AI review of clip candidates.

See [AI selection policy](docs/AI_SELECTION_POLICY.md) for how valid approvals, rejections, and unavailable AI responses are handled.

## Setup notes

- The installer targets 64-bit Windows. A minimum Windows version and hardware profile have not been certified for general release.
- Runtime components and selected AI models may need to be downloaded during setup. Model downloads can be several gigabytes; the actual selection and estimate are shown by the installer.
- Qwen review requires a compatible local Ollama service and an available model. Model availability and hardware performance depend on the user's system.
- This is a preview build intended for evaluation. Review installer prompts and the website before installation.
- The installer is not digitally signed, so Windows may display an unknown-publisher prompt.

## Latest preview artifact

- **File:** `Clipify AI Setup-20261018-205733-726.exe`
- **Build:** 2.0.0, Windows x64
- **Size:** 425,423,921 bytes (405.7 MiB)
- **SHA-256:** `D5E340E8AA8E8342C984D4D41593EB28617BAC209B79A8D723F091C6C341DB96`

Verify the SHA-256 after downloading before running the installer.
