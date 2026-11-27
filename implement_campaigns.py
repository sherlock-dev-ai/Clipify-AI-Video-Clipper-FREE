import os
import re

CAMPAIGNS_NAV_HTML = '''      <a href="#campaigns" id="navCampaignsLink" class="nav-campaigns-link"
        title="Clipper Monetization & Bounties — Campaigns">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 11v3a1 1 0 0 0 1 1h2l4 4V5L6 9H4a1 1 0 0 0-1 1z"></path>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
        </svg>
        <span>Campaigns</span>
        <span class="nav-campaigns-pill">Bounties</span>
      </a>'''

# 1. Update HTML templates and android assets
html_files = [
    r'L:\ClipifyAI\templates\index.html',
    r'L:\ClipifyAI\templates\live.html',
    r'L:\ClipifyAI\templates\narrate.html',
    r'L:\ClipifyAI\android\app\src\main\assets\www\index.html',
    r'L:\ClipifyAI\android\app\src\main\assets\www\live.html',
    r'L:\ClipifyAI\android\app\src\main\assets\www\narrate.html',
]

for hp in html_files:
    if not os.path.exists(hp):
        continue
    with open(hp, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'id="navCampaignsLink"' not in content:
        # Find </nav> after navPromotersLink
        promoter_idx = content.find('id="navPromotersLink"')
        if promoter_idx != -1:
            end_a_idx = content.find('</a>', promoter_idx)
            if end_a_idx != -1:
                insert_pos = end_a_idx + 4
                content = content[:insert_pos] + '\n' + CAMPAIGNS_NAV_HTML + content[insert_pos:]
                with open(hp, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Added navCampaignsLink to {os.path.basename(hp)} ({hp})")
            else:
                print(f"Could not find </a> after navPromotersLink in {hp}")
        else:
            print(f"Could not find navPromotersLink in {hp}")
    else:
        print(f"navCampaignsLink already exists in {os.path.basename(hp)}")

# 2. Update tour.css and style.css
CAMPAIGNS_CSS = '''
/* ==========================================================================
   CAMPAIGNS & BOUNTIES FEATURE (Black & White Obsidian Aesthetic)
   ========================================================================== */
.nav-campaigns-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #a1a1aa;
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  padding: 8px 12px;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.nav-campaigns-link:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.nav-campaigns-pill {
  margin-left: auto;
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.22);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.08);
}

.campaigns-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 10065;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 20px;
  opacity: 0;
  transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.campaigns-modal-overlay.active {
  display: flex;
  opacity: 1;
}

.campaigns-bw-container {
  position: relative;
  width: min(96vw, 1080px);
  max-height: min(92vh, 820px);
  background: #090a0d;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 24px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.95), 0 0 40px rgba(255, 255, 255, 0.04);
  animation: modalScaleUp 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}

.campaigns-content-layer {
  position: relative;
  z-index: 10;
  display: flex;
  flex-direction: column;
  padding: 32px 36px;
  height: 100%;
  overflow-y: auto;
}

.campaigns-bw-header {
  margin-bottom: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding-bottom: 18px;
}

.campaigns-bw-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.72rem;
  font-weight: 800;
  color: #000000;
  background: #ffffff;
  padding: 3px 10px;
  border-radius: 6px;
  margin-bottom: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.campaigns-bw-title {
  color: #ffffff;
  font-size: 1.55rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin: 0 0 6px 0;
}

.campaigns-bw-desc {
  color: #94a3b8;
  font-size: 0.88rem;
  line-height: 1.5;
  margin: 0;
}

.campaigns-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.campaigns-search-box {
  position: relative;
  flex: 1;
  min-width: 240px;
}

.campaigns-search-box input {
  width: 100%;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  padding: 9px 14px 9px 34px;
  color: #ffffff;
  font-size: 0.84rem;
  outline: none;
  transition: all 0.2s ease;
  box-sizing: border-box;
}

.campaigns-search-box input:focus {
  border-color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 12px rgba(255, 255, 255, 0.12);
}

.campaigns-search-icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: #64748b;
  pointer-events: none;
}

.campaigns-pills-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.campaigns-pill-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #94a3b8;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.campaigns-pill-btn:hover, .campaigns-pill-btn.active {
  background: #ffffff;
  color: #000000;
  border-color: #ffffff;
}

.campaigns-table-wrap {
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.02);
  margin-bottom: 20px;
}

.campaigns-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.86rem;
}

.campaigns-table th {
  padding: 12px 16px;
  color: #94a3b8;
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.03);
}

.campaigns-table td {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  vertical-align: middle;
}

.campaigns-table tr:last-child td {
  border-bottom: none;
}

.campaigns-table tr:hover td {
  background: rgba(255, 255, 255, 0.035);
}

.platform-rank {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.82rem;
  font-weight: 700;
  color: #64748b;
}

.platform-name-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.platform-name-cell strong {
  color: #ffffff;
  font-size: 0.95rem;
  font-weight: 700;
}

.platform-name-badge {
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 600;
  color: #cbd5e1;
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  width: fit-content;
}

.platform-creators {
  color: #cbd5e1;
  font-size: 0.84rem;
  line-height: 1.4;
}

.platform-country-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: #f8fafc;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}

.platform-btn-site {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #ffffff;
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  white-space: nowrap;
}

.platform-btn-site:hover {
  background: #ffffff;
  color: #000000;
  border-color: #ffffff;
  box-shadow: 0 0 14px rgba(255, 255, 255, 0.35);
  transform: translateY(-1px);
}

.campaigns-bw-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 16px;
  flex-wrap: wrap;
}

.campaigns-tip-text {
  color: #94a3b8;
  font-size: 0.8rem;
  flex: 1;
  min-width: 250px;
  margin: 0;
}

.campaigns-tip-text b {
  color: #ffffff;
}

.campaigns-bw-dismiss {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: #ffffff;
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.campaigns-bw-dismiss:hover {
  background: rgba(255, 255, 255, 0.16);
  border-color: #ffffff;
}

/* Mobile responsive adjustments */
@media (max-width: 768px) {
  .campaigns-content-layer {
    padding: 24px 18px;
  }
  .campaigns-bw-title {
    font-size: 1.25rem;
  }
  .campaigns-table th, .campaigns-table td {
    padding: 10px 12px;
  }
}
'''

css_files = [
    r'L:\ClipifyAI\static\tour.css',
    r'L:\ClipifyAI\android\app\src\main\assets\www\static\tour.css',
]

for cp in css_files:
    if not os.path.exists(cp):
        continue
    with open(cp, 'r', encoding='utf-8') as f:
        c = f.read()
    if '.nav-campaigns-link' not in c:
        c += '\n' + CAMPAIGNS_CSS
        with open(cp, 'w', encoding='utf-8') as f:
            f.write(c)
        print(f"Added CAMPAIGNS_CSS to {os.path.basename(cp)}")
    else:
        print(f"CAMPAIGNS_CSS already in {os.path.basename(cp)}")

print("Step 1 and 2 complete.")

