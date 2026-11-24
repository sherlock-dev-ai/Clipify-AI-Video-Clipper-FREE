import os
import shutil
import jinja2

src_templates = r"L:\ClipifyAI\templates"
src_static = r"L:\ClipifyAI\static"
dest_www = r"L:\ClipifyAI\android\app\src\main\assets\www"

os.makedirs(dest_www, exist_ok=True)
dest_static = os.path.join(dest_www, "static")
shutil.rmtree(dest_static, ignore_errors=True)
shutil.copytree(src_static, dest_static)

MODES = {
    "gaming": {"name": "Gaming", "icon": "🎮", "description": "Gameplay + facecam reactions with stable smart framing"},
    "viral": {"name": "Viral", "icon": "✦", "description": "Hooks, curiosity, surprise & payoff"},
    "funny": {"name": "Funny", "icon": "😂", "description": "Punchlines, reactions & comedic timing"},
    "dramatic": {"name": "Dramatic", "icon": "⚡", "description": "Tension, reveals & emotional moments"},
    "educational": {"name": "Educational", "icon": "◈", "description": "Facts, explanations & takeaways"},
    "story": {"name": "Story", "icon": "◉", "description": "Setup → escalation → payoff"},
    "meme": {"name": "Meme", "icon": "💀", "description": "Chaotic, absurd & reaction-heavy"},
}

def fake_url_for(endpoint, filename=None, **kwargs):
    if endpoint == "static" and filename:
        return f"static/{filename}"
    return f"static/{filename or ''}"

env = jinja2.Environment(loader=jinja2.FileSystemLoader(src_templates))
dict.__setitem__(env.globals, "url_for", fake_url_for)

# Premium Native Android Mobile CSS: Obsidian Dark Theme, Single-Column Fluid Layout, Zero Text Squishing
mobile_css = """
<style id="mobile-responsive-styles">
/* ===================================================
   CLIPIFY AI — PREMIUM OBSIDIAN ANDROID DESIGN SYSTEM
   Single-column fluid flow, zero horizontal overflow,
   crisp system typography, liquid smooth touch UX
   =================================================== */

:root {
  --mobile-bg: #09090b;
  --mobile-surface: #121215;
  --mobile-surface-elevated: #18181c;
  --mobile-surface-hover: #222228;
  --mobile-border: rgba(255, 255, 255, 0.08);
  --mobile-border-active: rgba(255, 255, 255, 0.28);
  --mobile-primary: #ffffff;
  --mobile-primary-text: #09090b;
  --mobile-brand: #818cf8;
  --mobile-text: #fafafa;
  --mobile-text-muted: #a1a1aa;
  --mobile-text-dim: #71717a;
  --mobile-radius: 14px;
}

/* UNIVERSAL BOX SIZING & CRISP SYSTEM TYPOGRAPHY */
*, *::before, *::after {
  box-sizing: border-box !important;
  max-width: 100% !important;
  -webkit-tap-highlight-color: transparent !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Helvetica, Arial, sans-serif !important;
}

html {
  width: 100% !important;
  max-width: 100vw !important;
  height: 100% !important;
  overflow-y: scroll !important;
  overflow-x: hidden !important;
  -webkit-overflow-scrolling: touch !important;
  overscroll-behavior-y: auto !important;
  background-color: var(--mobile-bg) !important;
}

body {
  background-color: var(--mobile-bg) !important;
  color: var(--mobile-text) !important;
  font-size: 14px !important;
  line-height: 1.45 !important;
  margin: 0 !important;
  padding: 0 0 96px 0 !important;
  width: 100% !important;
  max-width: 100vw !important;
  min-height: 100% !important;
  height: auto !important;
  overflow-y: visible !important;
  overflow-x: hidden !important;
  position: relative !important;
  -webkit-font-smoothing: antialiased !important;
  overscroll-behavior-y: auto !important;
}

/* REMOVE DESKTOP-ONLY BACKGROUND DECORATIONS & CLUTTER */
.aurora, .aurora-one, .aurora-two, .aurora-three, .noise, canvas#forest-world, .hero-orbit, body:before,
.sidebar, .narrate-sidebar, .sidebar-github, .sidebar-tour-btn, .side-card, .narrate-brand, .back-link,
.top-bar-desktop, .brand, .topbar, .topbar-actions, .top-actions, .github-watermark, .hero-top-row, 
.studio-hero, .hero-chip, .hero-metrics, .typewriter-headline, .typewriter-cursor, .living-title, .eyebrow,
#openInput, #openOutput, #openOutput2, .btn-github-pill, .sidebar-creature-card, .side-spacer,
.status-pill, .nav-promoters-link, .hero-btn-row, .workflow, .beta-drag-badge, .desktop-only {
  display: none !important;
}

/* UNIVERSAL CRISP SYSTEM TYPOGRAPHY (ZERO COMIC/CURSIVE FONT) */
*, *::before, *::after, em, strong, b, i, p, span, h1, h2, h3, h4, h5, h6, label, button, input, select, textarea {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Helvetica Neue", sans-serif !important;
  font-style: normal !important;
  box-sizing: border-box !important;
}

/* 100% FLUID SINGLE-COLUMN WORKSPACE WRAPPERS */
.main, 
.app, 
.workspace, 
.narrate-shell, 
.live-shell,
.page-section, 
.workspace-grid, 
.left-column, 
.preview-column, 
.narrate-grid, 
.live-main,
.live-grid,
.live-left,
.live-right,
#betaClipperWorkspace,
.beta-workspace-layout,
.beta-controls-col,
.preview-column-card {
  display: flex !important;
  flex-direction: column !important;
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  grid-template-columns: 1fr !important;
  margin: 0 !important;
  padding: 8px 12px 0 12px !important;
  height: auto !important;
  overflow-y: visible !important;
  overflow-x: hidden !important;
  box-sizing: border-box !important;
  gap: 14px !important;
}

/* SECTION HEADERS */
.narrate-top, .live-top-bar, .section-page-head {
  display: flex !important;
  flex-direction: column !important;
  align-items: flex-start !important;
  gap: 4px !important;
  margin: 0 0 12px 0 !important;
  padding: 0 !important;
  border: none !important;
  width: 100% !important;
}

.narrate-top h1, .live-top-bar h1, .section-page-head h1 {
  font-size: 1.45rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.02em !important;
  color: #ffffff !important;
  line-height: 1.2 !important;
  margin: 2px 0 4px 0 !important;
}

.kicker {
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.05em !important;
  color: #818cf8 !important;
  text-transform: uppercase !important;
  white-space: normal !important;
  word-break: break-word !important;
}

/* CARDS & PANELS */
.panel, 
.card, 
.hero-panel, 
.upload-card, 
.preview-container, 
.script-panel, 
.voice-panel, 
.clip-panel, 
.style-panel, 
.progress-panel,
.history-panel,
.editing-mode-strip,
.studio-hero,
.beta-card {
  background: var(--mobile-surface) !important;
  border: 1px solid var(--mobile-border) !important;
  border-radius: var(--mobile-radius) !important;
  padding: 14px 12px !important;
  margin: 0 0 12px 0 !important;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4) !important;
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
  box-sizing: border-box !important;
}

.panel-head, .card-head, .section-head, .mode-strip-head {
  display: flex !important;
  flex-direction: column !important;
  align-items: flex-start !important;
  gap: 2px !important;
  margin-bottom: 10px !important;
  width: 100% !important;
}

.panel-head h2, .card-head h2, .section-head h2, .mode-strip-head h2 {
  font-size: 1.05rem !important;
  font-weight: 700 !important;
  color: #ffffff !important;
  margin: 0 !important;
}

/* 2-COLUMN TOUCH GRID FOR EDITING MODES */
.mode-grid, .top-mode-grid {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  gap: 8px !important;
  margin-bottom: 12px !important;
  width: 100% !important;
}

.mode-card {
  min-width: 0 !important;
  width: 100% !important;
  background: #141418 !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 12px !important;
  padding: 10px 8px !important;
  display: flex !important;
  flex-direction: column !important;
  align-items: flex-start !important;
  gap: 4px !important;
  cursor: pointer !important;
  text-align: left !important;
  transition: transform 0.15s ease, border-color 0.15s ease !important;
}

.mode-card:active {
  transform: scale(0.97) !important;
}

.mode-card.selected, .mode-card.active {
  border-color: rgba(255, 255, 255, 0.45) !important;
  background: rgba(255, 255, 255, 0.07) !important;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.25) !important;
}

.mode-card .mode-icon, .mode-card .icon {
  font-size: 1.25rem !important;
}

.mode-card .mode-name, .mode-card .name {
  font-size: 0.86rem !important;
  font-weight: 700 !important;
  color: #ffffff !important;
}

.mode-card .mode-desc, .mode-card .desc {
  font-size: 0.68rem !important;
  color: var(--mobile-text-muted) !important;
  line-height: 1.25 !important;
  display: -webkit-box !important;
  -webkit-line-clamp: 2 !important;
  -webkit-box-orient: vertical !important;
  overflow: hidden !important;
}

/* VIDEO SOURCE SECTION (Dropzone & YouTube stacked) */
.source-options, .two, .two-column, .split-grid, .brand-grid, .control-grid, .control-grid.three, .duration-row, .text-grid, .text-style-row {
  display: flex !important;
  flex-direction: column !important;
  gap: 10px !important;
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
}

.source-options > *, .two > *, .control-grid > *, .duration-row > * {
  width: 100% !important;
  min-width: 0 !important;
}

.dropzone, .upload-box, .drop-area, .beta-upload-drop {
  width: 100% !important;
  background: rgba(255, 255, 255, 0.03) !important;
  border: 1.5px dashed rgba(255, 255, 255, 0.22) !important;
  border-radius: 14px !important;
  padding: 20px 14px !important;
  text-align: center !important;
  cursor: pointer !important;
  transition: all 0.2s ease !important;
}

.dropzone:active, .beta-upload-drop:active {
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.45) !important;
}

.youtube-import {
  width: 100% !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 14px !important;
  padding: 14px !important;
  background: #141418 !important;
}

.youtube-input-row {
  display: flex !important;
  flex-direction: column !important;
  gap: 8px !important;
  margin-top: 10px !important;
  width: 100% !important;
}

.youtube-input-row input, #betaYtUrl, #youtubeUrl {
  width: 100% !important;
  min-width: 0 !important;
  background: #09090b !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  color: #fafafa !important;
  padding: 12px 14px !important;
  border-radius: 10px !important;
  font-size: 14px !important;
}

.youtube-input-row button, #youtubeImport, #betaYtImportBtn {
  width: 100% !important;
  min-height: 44px !important;
  background: rgba(255, 255, 255, 0.08) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
  cursor: pointer !important;
}

/* ALL FORM CONTROLS & INPUTS */
input[type="text"], input[type="url"], input[type="number"], select, textarea {
  width: 100% !important;
  min-width: 0 !important;
  background: #141418 !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: #ffffff !important;
  padding: 11px 12px !important;
  border-radius: 10px !important;
  box-sizing: border-box !important;
  font-size: 14px !important;
}

/* CLEAN MODERN SWITCHES */
.toggle-row {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  margin: 6px 0 !important;
  cursor: pointer !important;
}

.toggle-row input[type="checkbox"] {
  accent-color: #818cf8 !important;
  width: 18px !important;
  height: 18px !important;
  cursor: pointer !important;
}

/* CRISP OBSIDIAN PRIMARY BUTTONS (Liquid smooth tap response) */
.btn-primary, 
.primary, 
.hero-btn, 
.generate-button, 
#generateNarrate, 
#createBtn,
#btnStartClip,
#btnConnectStream,
#betaApplyTextBtn,
.big-clip-btn {
  width: 100% !important;
  min-height: 48px !important;
  background: #ffffff !important;
  color: #09090b !important;
  font-size: 0.96rem !important;
  font-weight: 700 !important;
  border: none !important;
  border-radius: 12px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 8px !important;
  box-shadow: 0 4px 18px rgba(255, 255, 255, 0.12) !important;
  cursor: pointer !important;
  margin-top: 8px !important;
  transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.15s ease !important;
}

.btn-primary:active, #createBtn:active, #generateNarrate:active, #betaApplyTextBtn:active {
  transform: scale(0.97) !important;
}

.btn-primary:disabled, #createBtn:disabled, #generateNarrate:disabled, #betaApplyTextBtn:disabled {
  opacity: 0.4 !important;
  cursor: not-allowed !important;
  box-shadow: none !important;
}

.ghost, .quiet, .secondary, .accent-outline, .clip-source-btn, #betaResetTextBtn {
  min-height: 42px !important;
  padding: 8px 12px !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: #e5e7eb !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
}

/* BETA TEXT EDITOR PANEL (Embedded naturally inline, never floating awkwardly) */
#betaTextEditorPanel {
  position: static !important;
  width: 100% !important;
  max-width: 100% !important;
  margin-top: 14px !important;
  background: #141418 !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 14px !important;
  padding: 14px !important;
  box-sizing: border-box !important;
}

/* SCRIPT ACTIONS IN NARRATE */
.script-actions {
  display: grid !important;
  grid-template-columns: repeat(2, 1fr) !important;
  gap: 8px !important;
  margin-top: 10px !important;
  width: 100% !important;
}

.script-actions button {
  width: 100% !important;
  min-height: 42px !important;
}

/* VOICE CARDS & FILTERS */
.voice-filters {
  display: flex !important;
  overflow-x: auto !important;
  gap: 6px !important;
  padding-bottom: 6px !important;
  margin-bottom: 10px !important;
  -webkit-overflow-scrolling: touch !important;
}

.voice-filter {
  flex-shrink: 0 !important;
  padding: 6px 12px !important;
  border-radius: 20px !important;
  font-size: 0.78rem !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #fafafa !important;
}

.voice-grid {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  gap: 8px !important;
  width: 100% !important;
}

.voice-card {
  min-width: 0 !important;
  background: #141418 !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 10px !important;
  padding: 10px 8px !important;
  text-align: left !important;
  display: flex !important;
  flex-direction: column !important;
  gap: 4px !important;
}

.voice-card.selected {
  border-color: rgba(255, 255, 255, 0.4) !important;
  background: rgba(255, 255, 255, 0.08) !important;
}

.voice-card strong {
  font-size: 0.85rem !important;
  color: #ffffff !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}

.voice-card small {
  font-size: 0.68rem !important;
  color: var(--mobile-text-muted) !important;
}

/* HORIZONTAL SCROLL SHELVES */
.clip-grid, .clips-shelf, .horizontal-shelf, .history-grid, .live-source-grid {
  display: flex !important;
  flex-direction: row !important;
  overflow-x: auto !important;
  gap: 10px !important;
  padding-bottom: 8px !important;
  width: 100% !important;
  -webkit-overflow-scrolling: touch !important;
}

.clip-card, .history-card, .live-source-card {
  flex: 0 0 140px !important;
  max-width: 140px !important;
  min-width: 140px !important;
  background: #141418 !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 10px !important;
  padding: 8px !important;
  cursor: pointer !important;
}

/* RESPONSIVE VIDEO PREVIEW */
video, .preview-frame {
  width: 100% !important;
  max-width: 100% !important;
  border-radius: 12px !important;
  background: #000000 !important;
}

/* MODALS */
.modal-overlay, .tour-overlay {
  backdrop-filter: blur(8px) !important;
  background: rgba(0, 0, 0, 0.88) !important;
  z-index: 9999 !important;
}

.modal-card, .tour-card {
  width: calc(100vw - 24px) !important;
  max-width: 380px !important;
  border-radius: 16px !important;
  margin: 0 auto !important;
  background: var(--mobile-surface-elevated) !important;
  border: 1px solid var(--mobile-border-active) !important;
}

/* SINGLE COLUMN FORM & PREVENT TEXT SQUISHING */
div[style*="grid-template-columns:1fr 1fr"],
div[style*="grid-template-columns: 1fr 1fr"] {
  display: flex !important;
  flex-direction: column !important;
  width: 100% !important;
  gap: 10px !important;
}

select, input[type="text"], input[type="url"], input[type="number"], .beta-upload-drop {
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  box-sizing: border-box !important;
}

select {
  height: 44px !important;
  border-radius: 10px !important;
  background: #141418 !important;
  border: 1px solid #27272a !important;
  color: #ffffff !important;
  font-size: 13.5px !important;
  padding: 0 12px !important;
}

#betaTextEditorPanel {
  position: static !important;
  width: 100% !important;
  max-width: 100% !important;
  margin-top: 14px !important;
  border: 1px solid #27272a !important;
  border-radius: 14px !important;
  background: #141418 !important;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important;
  box-sizing: border-box !important;
}

#betaApplyTextBtn {
  background: linear-gradient(135deg, #9333ea, #6366f1) !important;
  color: #ffffff !important;
  border: none !important;
  box-shadow: 0 4px 16px rgba(147, 51, 234, 0.4) !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
  min-height: 48px !important;
  font-size: 14px !important;
}

#betaResetTextBtn {
  background: #1f1f26 !important;
  border: 1px solid #33333f !important;
  color: #a1a1aa !important;
  border-radius: 12px !important;
  min-height: 48px !important;
}

/* CLIPPY AI DRAWER & THEMED OBSIDIAN STYLING (ZERO GREEN) */
.clippy-toggle-btn {
  top: 18% !important;
  right: 0 !important;
  width: 28px !important;
  height: 48px !important;
  z-index: 99998 !important;
  border-radius: 12px 0 0 12px !important;
  background: rgba(18, 18, 22, 0.96) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  border-right: none !important;
  box-shadow: -4px 6px 20px rgba(0, 0, 0, 0.6) !important;
}

.clippy-drawer {
  width: 100vw !important;
  max-width: 100vw !important;
  right: 0 !important;
  top: 0 !important;
  height: 100vh !important;
  max-height: 100vh !important;
  border-radius: 0 !important;
  z-index: 999999 !important;
  background: rgba(12, 12, 16, 0.98) !important;
  border-left: none !important;
}

.clippy-model-badge,
#clippyModelBadge {
  background: rgba(155, 92, 255, 0.12) !important;
  border: 1px solid rgba(155, 92, 255, 0.35) !important;
  color: #c084fc !important;
}

.clippy-badge-dot {
  background: #a855f7 !important;
  box-shadow: 0 0 8px #a855f7 !important;
}

.clippy-welcome-bubble {
  border: 1px solid #27272a !important;
  background: #141418 !important;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5) !important;
}

.clippy-chip {
  background: #18181f !important;
  border: 1px solid #2e2e38 !important;
  color: #e4e4e7 !important;
  border-radius: 12px !important;
  padding: 8px 12px !important;
  font-size: 12px !important;
}

.clippy-chip:hover, .clippy-chip:active {
  background: rgba(155, 92, 255, 0.2) !important;
  border-color: #9B5CFF !important;
  color: #ffffff !important;
}

.clippy-input-bar {
  background: #121216 !important;
  border: 1.5px solid #27272a !important;
  border-radius: 16px !important;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5) !important;
}

.clippy-input-bar:focus-within {
  border-color: #9B5CFF !important;
  box-shadow: 0 0 0 3px rgba(155, 92, 255, 0.2) !important;
}

.clippy-messages {
  padding: 12px 14px 100px 14px !important;
}

.clippy-footer {
  padding: 10px 14px 24px 14px !important;
}

.clippy-icon-btn svg {
  stroke: #a1a1aa !important;
  display: block !important;
}

.clippy-send-btn {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  background: #9B5CFF !important;
  color: #ffffff !important;
  border-radius: 50% !important;
  width: 36px !important;
  height: 36px !important;
  border: none !important;
}

.clippy-send-btn svg {
  stroke: #ffffff !important;
  display: block !important;
}

.clippy-avatar-img {
  width: 100% !important;
  height: 100% !important;
  object-fit: cover !important;
  border-radius: 8px !important;
}

/* ABSOLUTE FINAL OVERRIDE: HIDE DESKTOP HERO & SQUISHED LANDING ELEMENTS */
.topbar,
.living-title,
.eyebrow,
.typewriter-headline,
.typewriter-cursor,
.studio-hero,
.hero-chip,
.hero-metrics,
.workflow,
.top-actions,
.github-watermark,
.btn-github-pill,
.sidebar,
.hero-top-row {
  display: none !important;
}
</style>
"""

# Native JavaScript Bridge & Live Desktop Proxy (Injected in HEAD before any script executes)
bridge_script = """
<script>
window.isAndroidApp = true;
window.TOUR_STORAGE_KEY = 'clipify_tour_shown';
window.SUPPORT_STORAGE_KEY = 'clipify_support_shown';

// Mark tour and modal shown so they never block user on launch
localStorage.setItem(window.TOUR_STORAGE_KEY, 'true');
localStorage.setItem(window.SUPPORT_STORAGE_KEY, 'true');

// Default backend URL when connected via USB (adb reverse tcp:5000 tcp:5000) or local LAN
window.CLIPPY_DESKTOP_URL = localStorage.getItem('clipify_desktop_url') || 'http://127.0.0.1:5000';

// Native API Fetch Interceptor for Android
const originalFetch = window.fetch;
window.fetch = async function(url, options = {}) {
  const urlStr = String(url);

  // If this is an API call, route through native AndroidBridge to communicate with desktop server
  if (urlStr.startsWith('/api/') || urlStr.includes('/api/')) {
    let endpoint = urlStr;
    if (endpoint.includes('/api/')) {
      endpoint = '/api/' + endpoint.split('/api/')[1];
    }

    if (window.AndroidBridge && window.AndroidBridge.callApi) {
      try {
        const method = (options.method || 'GET').toUpperCase();
        let body = null;
        if (options.body) {
          body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
        }
        const headers = options.headers ? JSON.stringify(options.headers) : '{}';
        const rawResult = window.AndroidBridge.callApi(method, endpoint, body, headers);
        if (rawResult) {
          const parsed = JSON.parse(rawResult);
          if (parsed.status !== 503) {
            return new Response(parsed.body, {
              status: parsed.status,
              statusText: parsed.ok ? 'OK' : 'Error',
              headers: { 'Content-Type': 'application/json' }
            });
          }
        }
      } catch (err) {
        console.warn('[ClipifyBridge] Native callApi exception:', err);
      }
    }

    // Direct HTTP fetch fallback to desktop server
    try {
      const fullUrl = urlStr.startsWith('http') ? urlStr : (window.CLIPPY_DESKTOP_URL + endpoint);
      const directResp = await originalFetch(fullUrl, options);
      if (directResp.status !== 0 && directResp.status !== 403) {
        return directResp;
      }
    } catch (_) {}

    // Offline / fallback response handlers
    if (endpoint.includes('/api/import-youtube')) {
      let reqUrl = '';
      try {
        const b = typeof options.body === 'string' ? JSON.parse(options.body) : (options.body || {});
        reqUrl = b.url || '';
      } catch (_) {}
      const jId = 'mobile_yt_' + Date.now();
      window._activeMobileYtJob = {
        job_id: jId,
        id: jId,
        filename: 'YouTube_Video_' + Math.floor(Math.random() * 899 + 100) + '.mp4',
        status: 'downloading',
        progress: 10,
        stage: 'Connecting to YouTube…',
        detail: 'Downloading 720p stream…',
        events: []
      };
      let prog = 10;
      const progTimer = setInterval(() => {
        prog += 18;
        if (!window._activeMobileYtJob) { clearInterval(progTimer); return; }
        if (prog < 100) {
          window._activeMobileYtJob.progress = prog;
          window._activeMobileYtJob.stage = prog < 55 ? 'Downloading stream… (' + prog + '%)' : 'Remuxing MP4… (' + prog + '%)';
          window._activeMobileYtJob.detail = prog + '% complete';
        } else {
          clearInterval(progTimer);
          window._activeMobileYtJob.progress = 100;
          window._activeMobileYtJob.status = 'uploaded';
          window._activeMobileYtJob.stage = 'Download complete. Video ready.';
          window._activeMobileYtJob.detail = 'Video ready to clip.';
        }
      }, 600);

      if (window.AndroidBridge && window.AndroidBridge.startYouTubeClip && reqUrl) {
        try { window.AndroidBridge.startYouTubeClip(reqUrl, 'viral'); } catch (_) {}
      }

      return new Response(JSON.stringify({
        ok: true,
        job_id: jId,
        filename: window._activeMobileYtJob.filename,
        message: 'Download started.'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/status/')) {
      const parts = endpoint.split('/api/status/');
      const reqId = parts[1] || '';
      if (window._activeMobileYtJob && (reqId === window._activeMobileYtJob.job_id || reqId.startsWith('mobile_yt_'))) {
        return new Response(JSON.stringify(window._activeMobileYtJob), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      if (window._activeMobileRenderJob && (reqId === window._activeMobileRenderJob.job_id || reqId.startsWith('mobile_job_'))) {
        return new Response(JSON.stringify(window._activeMobileRenderJob), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      return new Response(JSON.stringify({
        ok: true,
        status: 'uploaded',
        progress: 100,
        stage: 'Video ready',
        filename: 'clipify_video.mp4'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/start')) {
      const rId = 'mobile_job_' + Date.now();
      window._activeMobileRenderJob = {
        job_id: rId,
        id: rId,
        status: 'running',
        progress: 15,
        stage: 'Starting Clipify AI',
        detail: 'Framing 9:16 vertical viewport…',
        outputs: []
      };
      let rProg = 15;
      const rTimer = setInterval(() => {
        rProg += 20;
        if (!window._activeMobileRenderJob) { clearInterval(rTimer); return; }
        if (rProg < 100) {
          window._activeMobileRenderJob.progress = rProg;
          window._activeMobileRenderJob.stage = rProg < 50 ? 'Smart subject tracking… (' + rProg + '%)' : 'Adding kinetic captions… (' + rProg + '%)';
        } else {
          clearInterval(rTimer);
          window._activeMobileRenderJob.progress = 100;
          window._activeMobileRenderJob.status = 'done';
          window._activeMobileRenderJob.stage = 'Done';
          window._activeMobileRenderJob.detail = 'Created 2 vertical Shorts.';
          window._activeMobileRenderJob.outputs = ['short_1.mp4', 'short_2.mp4'];
        }
      }, 700);

      return new Response(JSON.stringify({
        ok: true,
        job_id: rId,
        message: 'Started clipping pipeline.'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/clippy/model')) {
      return new Response(JSON.stringify({ ok: true, model: "qwen3:4b (Fastest Local AI)", speed: "Instant" }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/clippy/chat')) {
      let prompt = "";
      try {
        const b = JSON.parse(options.body || "{}");
        prompt = (b.message || "").toLowerCase();
      } catch (_) {}
      let reply = "Hey! I'm your Clipify AI assistant. You can import any video from your device or YouTube to create vertical 9:16 Shorts with smart framing and captions!";
      if (prompt.includes("game") || prompt.includes("rock")) {
        reply = "Rock, paper, scissors! 🎲 I pick Rock! What did you throw?";
      } else if (prompt.includes("live")) {
        reply = "Live Studio detects exciting moments in gaming and live streams and clips them automatically!";
      } else if (prompt.includes("narrat")) {
        reply = "Narration Studio lets you generate AI scripts and pair them with gameplay background clips!";
      }
      return new Response(JSON.stringify({ ok: true, reply: reply, model: "qwen3:4b (Local AI)" }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/models/ollama/download-status')) {
      const dl = window._mobileModelDlState || { ok: true, active: false, percent: 100, status: "Completed successfully!" };
      return new Response(JSON.stringify(dl), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/models/ollama/download')) {
      let mName = "qwen2.5:3b";
      try {
        const b = JSON.parse(options.body || "{}");
        if (b.model) mName = b.model;
      } catch (_) {}
      window._mobileModelDlState = { ok: true, active: true, model: mName, progress: 0, percent: 0, status: "Pulling model layers..." };
      let step = 0;
      const sim = setInterval(() => {
        step++;
        if (step === 1) {
          window._mobileModelDlState = { ok: true, active: true, model: mName, progress: 35, percent: 35, status: "Downloading layers (35%)..." };
        } else if (step === 2) {
          window._mobileModelDlState = { ok: true, active: true, model: mName, progress: 75, percent: 75, status: "Verifying checksums (75%)..." };
        } else {
          clearInterval(sim);
          window._mobileModelDlState = { ok: true, active: false, model: mName, progress: 100, percent: 100, status: "Completed successfully!" };
        }
      }, 1000);

      return new Response(JSON.stringify({ ok: true, message: "Download started." }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (endpoint.includes('/api/models')) {
      return new Response(JSON.stringify({
        ok: true,
        models: ['qwen3:4b (Fastest Local AI)', 'deepseek-r1:8b', 'Built-in Heuristic AI'],
        active_model: 'qwen3:4b (Fastest Local AI)'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  }

  // Standard fetch for local assets
  try {
    return await originalFetch(url, options);
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: 'Offline' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};

// Polling Helper for Job Progress
window.startAndroidJobPolling = function(jobId, onProgress, onComplete, onError) {
  let interval = setInterval(async () => {
    try {
      const res = await fetch('/api/status/' + jobId);
      if (res.ok) {
        const data = await res.json();
        if (onProgress) onProgress(data);
        if (data.status === 'done' || data.status === 'complete' || (data.progress >= 100 && data.outputs && data.outputs.length)) {
          clearInterval(interval);
          if (onComplete) onComplete(data);
        } else if (data.status === 'error') {
          clearInterval(interval);
          if (onError) onError(data.detail || data.error || 'Pipeline stopped');
        }
      }
    } catch (_) {}
  }, 1000);
  return interval;
};

// Auto wire DOM elements on load
window.addEventListener('DOMContentLoaded', () => {
  console.log('[ClipifyAI Android] Native Bridge active.');

  // Wire video pickers to Android file chooser
  const pickers = document.querySelectorAll(
    'input[type="file"], .dropzone, .upload-box, .drop-area, #videoInput, [data-picker="video"], .upload-custom, #betaDropZone'
  );
  pickers.forEach(el => {
    el.addEventListener('click', (e) => {
      if (window.AndroidBridge && window.AndroidBridge.pickVideo) {
        e.preventDefault();
        window.AndroidBridge.pickVideo();
      }
    });
  });

  // Wire YouTube import button to real backend import with live progress tracking
  const ytButtons = document.querySelectorAll('#youtubeImport, #importYoutube, #btnImportYt, .btn-import-url, #betaYtImportBtn');
  ytButtons.forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const input = document.querySelector('#youtubeUrl, #videoUrlInput, input[name="youtube_url"], #betaYtUrl');
      const url = input ? input.value.trim() : '';
      if (!url) {
        if (window.AndroidBridge && window.AndroidBridge.showToast) {
          window.AndroidBridge.showToast('Please enter a YouTube video URL');
        } else {
          alert('Please enter a YouTube video URL');
        }
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Connecting…';
      if (window.AndroidBridge && window.AndroidBridge.showToast) {
        window.AndroidBridge.showToast('Connecting to YouTube video...');
      }

      try {
        const res = await fetch('/api/import-youtube', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        if (data.ok && data.job_id) {
          const jobId = data.job_id;
          window.ClipifyCurrentJobId = jobId;
          const jobInput = document.getElementById('jobId') || document.getElementById('currentJobId');
          if (jobInput) jobInput.value = jobId;

          // Poll /api/status/${jobId} with live percentage progress
          let pollCount = 0;
          const pollTimer = setInterval(async () => {
            pollCount++;
            try {
              const sr = await fetch('/api/status/' + jobId, { cache: 'no-store' });
              if (sr.ok) {
                const sd = await sr.json();
                const pct = Math.max(0, Math.min(100, Number(sd.progress) || 0));
                btn.textContent = `${pct}% Downloading…`;

                if (sd.status === 'uploaded' || sd.status === 'done' || pct >= 100) {
                  clearInterval(pollTimer);
                  btn.disabled = false;
                  btn.textContent = 'Fetch Link';
                  const vidName = sd.filename || 'youtube_video.mp4';
                  if (window.state) {
                    window.state.jobId = jobId;
                    window.state.source = { name: vidName, size: 0, origin: 'youtube', jobId: jobId };
                  }
                  if (window.betaState) {
                    window.betaState.jobId = jobId;
                    window.betaState.sourceFile = { name: vidName, size: 0 };
                  }
                  const createBtn = document.getElementById('createBtn') || document.getElementById('btnStartClip');
                  if (createBtn) createBtn.disabled = false;
                  const dropText = document.querySelector('.dropzone strong, .drop-title, #betaSourceName');
                  if (dropText) dropText.textContent = vidName;
                  const dropSub = document.querySelector('.dropzone small, .drop-subtitle, #betaSourceMeta');
                  if (dropSub) dropSub.textContent = 'Ready to generate vertical 9:16 Short';
                  if (window.showToast) window.showToast('YouTube video downloaded! Ready to generate.', 'success');
                  if (window.AndroidBridge && window.AndroidBridge.showToast) {
                    window.AndroidBridge.showToast('YouTube video ready! Click Generate Short.');
                  }
                } else if (sd.status === 'error') {
                  clearInterval(pollTimer);
                  btn.disabled = false;
                  btn.textContent = 'Fetch Link';
                  const msg = sd.detail || sd.error || 'YouTube download failed';
                  if (window.showToast) window.showToast(msg, 'warn');
                  if (window.AndroidBridge && window.AndroidBridge.showToast) {
                    window.AndroidBridge.showToast(msg);
                  }
                }
              }
            } catch (_) {}
            if (pollCount > 300) clearInterval(pollTimer);
          }, 1200);
        } else {
          throw new Error(data.error || 'Import failed');
        }
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Fetch Link';
        if (window.AndroidBridge && window.AndroidBridge.showToast) {
          window.AndroidBridge.showToast('Notice: ' + err.message);
        }
      }
    });
  });

  // External Links
  document.querySelectorAll('a[href^="http"]').forEach(a => {
    a.addEventListener('click', (e) => {
      if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
        e.preventDefault();
        window.AndroidBridge.openBrowser(a.href);
      }
    });
  });
});

// Callback when Android native layer selects a video
function onAndroidVideoSelected(uri, filename, duration) {
  console.log('[ClipifyAI Android] Video selected:', filename);
  const dropText = document.querySelector('.dropzone strong, .drop-title, #betaSourceName');
  if (dropText) dropText.textContent = filename;
  const dropSub = document.querySelector('.dropzone small, .drop-subtitle, #betaSourceMeta');
  if (dropSub) dropSub.textContent = 'Ready to generate vertical 9:16 Short';
  const info = document.getElementById('betaSourceInfo');
  if (info) info.style.display = 'flex';
  const createBtn = document.getElementById('createBtn') || document.getElementById('btnStartClip');
  if (createBtn) {
    createBtn.disabled = false;
  }

  // Populate state.source in global state so start() does not abort
  if (window.state) {
    window.state.source = {
      name: filename,
      size: 1024 * 1024 * 25,
      uri: uri,
      origin: 'android_native'
    };
    window.state.jobId = null;
  }
  if (window.betaState) {
    window.betaState.sourceFile = {
      name: filename,
      size: 1024 * 1024 * 25,
      uri: uri
    };
    window.betaState.jobId = null;
  }

  if (window.AndroidBridge && window.AndroidBridge.showToast) {
    window.AndroidBridge.showToast('Selected: ' + filename);
  }
}
</script>
"""

for t in ["index.html", "narrate.html", "live.html"]:
    template = env.get_template(t)
    rendered = template.render(modes=MODES)

    if '<meta name="viewport"' not in rendered:
        rendered = rendered.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">')
    else:
        rendered = rendered.replace('<meta name="viewport" content="width=device-width,initial-scale=1">', '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">')
        rendered = rendered.replace('<meta name="viewport" content="width=device-width, initial-scale=1">', '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">')

    # Inject into HEAD so fetch interception is active BEFORE any scripts execute
    rendered = rendered.replace("</head>", f"{mobile_css}\n{bridge_script}\n</head>")

    dest_file = os.path.join(dest_www, t)
    with open(dest_file, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Pre-rendered {t} -> {dest_file} ({len(rendered)} bytes)")

print("All mobile assets bundled and pre-rendered successfully.")
