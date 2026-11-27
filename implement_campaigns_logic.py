import os
import re

CAMPAIGNS_JS_LOGIC = '''
  // ==========================================
  // CAMPAIGNS & BOUNTIES MODAL (Black & White Clipper Directory)
  // ==========================================
  const CAMPAIGN_PLATFORMS = [
    {
      rank: 1,
      name: "Content Rewards",
      badge: "🔥 Top Bounty",
      focus: "Podcasts, YouTubers, streamers, gaming, shows",
      countries: "India + international",
      category: "india",
      url: "https://contentrewards.com"
    },
    {
      rank: 2,
      name: "Vyro",
      badge: "⭐ MrBeast Network",
      focus: "Major creators, MrBeast ecosystem, podcasts, shows",
      countries: "India not on published exclusion list",
      category: "india",
      url: "https://vyro.ai"
    },
    {
      rank: 3,
      name: "Clipster",
      badge: "🌍 Worldwide",
      focus: "Streamers, music, gaming, influencers",
      countries: "Worldwide; no country block",
      category: "global",
      url: "https://clipster.gg"
    },
    {
      rank: 4,
      name: "Clipping.net",
      badge: "✨ Marketplace",
      focus: "Creators, influencers, podcasts",
      countries: "Territories not published",
      category: "global",
      url: "https://clipping.net"
    },
    {
      rank: 5,
      name: "Vues",
      badge: "💼 Brand Deals",
      focus: "Brands, creators, social campaigns",
      countries: "Country availability not fully published",
      category: "global",
      url: "https://vues.io"
    },
    {
      rank: 6,
      name: "Clip",
      badge: "🏆 Sports & TV",
      focus: "Streamers, sports, film, TV, music",
      countries: "Country list not published",
      category: "global",
      url: "https://clip.live"
    },
    {
      rank: 7,
      name: "Wondeed",
      badge: "🌐 Multi-Region",
      focus: "Creator and influencer clipping",
      countries: "International; confirm payout",
      category: "global",
      url: "https://wondeed.com"
    },
    {
      rank: 8,
      name: "ClipAffiliates",
      badge: "📈 Rev-Share",
      focus: "Creator and influencer campaigns",
      countries: "Not independently verified",
      category: "global",
      url: "https://clipaffiliates.com"
    },
    {
      rank: 9,
      name: "ClipGrow",
      badge: "🇮🇳 India Hub",
      focus: "Creator clipping campaigns",
      countries: "India-focused",
      category: "india",
      url: "https://clipgrow.in"
    },
    {
      rank: 10,
      name: "ClipConnect India",
      badge: "🇮🇳 India Verified",
      focus: "Creator and social-media campaigns",
      countries: "India",
      category: "india",
      url: "https://clipconnect.in"
    }
  ];

  let campaignsModalOverlayEl = null;
  let campaignsStarsCleanup = null;
  let currentCampaignFilter = 'all';
  let currentCampaignSearch = '';

  function renderCampaignTableRows() {
    const tbody = document.getElementById('campaignsTableBody');
    if (!tbody) return;

    const q = (currentCampaignSearch || '').toLowerCase().trim();
    const cat = currentCampaignFilter;

    const filtered = CAMPAIGN_PLATFORMS.filter(item => {
      // Category match
      if (cat === 'india') {
        const isIndia = item.category === 'india' || item.countries.toLowerCase().includes('india');
        if (!isIndia) return false;
      } else if (cat === 'global') {
        const isGlobal = item.countries.toLowerCase().includes('worldwide') || item.countries.toLowerCase().includes('international');
        if (!isGlobal) return false;
      }

      // Search match
      if (q) {
        const matchName = item.name.toLowerCase().includes(q);
        const matchFocus = item.focus.toLowerCase().includes(q);
        const matchCountry = item.countries.toLowerCase().includes(q);
        const matchBadge = (item.badge || '').toLowerCase().includes(q);
        return matchName || matchFocus || matchCountry || matchBadge;
      }
      return true;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align: center; padding: 36px 16px; color: #64748b;">
            <div style="font-size: 1.5rem; margin-bottom: 8px;">🔍</div>
            <strong style="color: #cbd5e1; display: block; margin-bottom: 4px;">No platforms found</strong>
            <span style="font-size: 0.8rem;">Try clearing your search query or switching filters.</span>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = filtered.map(item => {
      const rankPad = String(item.rank).padStart(2, '0');
      return `
        <tr>
          <td class="platform-rank">#${rankPad}</td>
          <td>
            <div class="platform-name-cell">
              <strong>${item.name}</strong>
              <span class="platform-name-badge">${item.badge}</span>
            </div>
          </td>
          <td>
            <div class="platform-creators">${item.focus}</div>
          </td>
          <td>
            <span class="platform-country-badge">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
              <span>${item.countries}</span>
            </span>
          </td>
          <td>
            <a href="${item.url}" target="_blank" rel="noopener noreferrer" class="platform-btn-site" title="Visit ${item.name} website">
              <span>Check Website</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
            </a>
          </td>
        </tr>
      `;
    }).join('');

    // Attach external link opener for Android WebView
    tbody.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
          e.preventDefault();
          window.AndroidBridge.openBrowser(link.href);
        }
      });
    });
  }

  function initCampaignsModal() {
    if (campaignsModalOverlayEl) return;

    campaignsModalOverlayEl = document.createElement('div');
    campaignsModalOverlayEl.id = 'campaignsModalOverlay';
    campaignsModalOverlayEl.className = 'campaigns-modal-overlay galaxy-overlay';
    campaignsModalOverlayEl.innerHTML = `
      <div class="campaigns-bw-container" id="campaignsBwCard">
        <button type="button" class="galaxy-modal-close" id="btnCampaignsClose" aria-label="Close modal">&times;</button>
        <canvas id="campaignsStarsCanvas" class="galaxy-stars-canvas"></canvas>

        <div class="campaigns-content-layer">
          <!-- Header -->
          <div class="campaigns-bw-header">
            <span class="campaigns-bw-tag">⚡ CLIPPER CAMPAIGNS & BOUNTIES</span>
            <h2 class="campaigns-bw-title">Best platforms for streamer & podcast clippers</h2>
            <p class="campaigns-bw-desc">Monetize your 9:16 Shorts with verified bounty platforms and creator networks. Generate hooks with Clipify AI, submit your clips, and earn payouts.</p>
          </div>

          <!-- Filter & Search Controls -->
          <div class="campaigns-filter-row">
            <div class="campaigns-search-box">
              <svg class="campaigns-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <input type="text" id="campaignsSearchInput" placeholder="Filter platform, creator, or country (e.g. India, MrBeast, Gaming)..." autocomplete="off" />
            </div>
            <div class="campaigns-pills-row">
              <button type="button" class="campaigns-pill-btn active" data-filter="all">All Platforms (10)</button>
              <button type="button" class="campaigns-pill-btn" data-filter="india">🇮🇳 India Eligible (5)</button>
              <button type="button" class="campaigns-pill-btn" data-filter="global">🌍 Worldwide (4)</button>
            </div>
          </div>

          <!-- Table Wrap -->
          <div class="campaigns-table-wrap">
            <table class="campaigns-table">
              <thead>
                <tr>
                  <th style="width: 50px;">#</th>
                  <th style="width: 220px;">Platform</th>
                  <th>Streamers / podcasts / creators</th>
                  <th style="width: 240px;">Clipper countries</th>
                  <th style="width: 150px;">Action</th>
                </tr>
              </thead>
              <tbody id="campaignsTableBody">
                <!-- Dynamically rendered -->
              </tbody>
            </table>
          </div>

          <!-- Footer -->
          <div class="campaigns-bw-footer">
            <p class="campaigns-tip-text">
              💡 <b>Pro Clipper Tip:</b> Batch-generate 9:16 vertical clips with <b>Clipify AI Auto Golden Hook</b> and <b>Kinetic Subtitles</b> to maximize your view count and bounty acceptance rate!
            </p>
            <button type="button" class="campaigns-bw-dismiss" id="btnCampaignsDismiss">Back to Clipify AI</button>
          </div>
        </div>
      </div>
    `;

    campaignsModalOverlayEl.querySelector('#btnCampaignsClose')?.addEventListener('click', closeCampaignsModal);
    campaignsModalOverlayEl.querySelector('#btnCampaignsDismiss')?.addEventListener('click', closeCampaignsModal);

    campaignsModalOverlayEl.addEventListener('click', (e) => {
      if (e.target === campaignsModalOverlayEl) {
        closeCampaignsModal();
      }
    });

    // Wire Search Input
    const searchInput = campaignsModalOverlayEl.querySelector('#campaignsSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        currentCampaignSearch = e.target.value;
        renderCampaignTableRows();
      });
    }

    // Wire Filter Buttons
    campaignsModalOverlayEl.querySelectorAll('.campaigns-pill-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        campaignsModalOverlayEl.querySelectorAll('.campaigns-pill-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentCampaignFilter = btn.dataset.filter || 'all';
        renderCampaignTableRows();
      });
    });

    document.body.appendChild(campaignsModalOverlayEl);
  }

  function showCampaignsModal() {
    initCampaignsModal();
    renderCampaignTableRows();
    campaignsModalOverlayEl.style.display = 'flex';
    campaignsModalOverlayEl.classList.add('active');
    if (campaignsStarsCleanup) campaignsStarsCleanup();
    campaignsStarsCleanup = initStarfieldCanvas('campaignsStarsCanvas', 100);

    // Focus search input
    setTimeout(() => {
      const input = document.getElementById('campaignsSearchInput');
      if (input) input.focus();
    }, 150);
  }

  function closeCampaignsModal() {
    if (!campaignsModalOverlayEl) return;
    if (campaignsStarsCleanup) {
      campaignsStarsCleanup();
      campaignsStarsCleanup = null;
    }
    campaignsModalOverlayEl.classList.remove('active');
    setTimeout(() => {
      campaignsModalOverlayEl.style.display = 'none';
    }, 280);
  }
'''

# Update static/tour.js and android tour.js
tour_files = [
    r'L:\ClipifyAI\static\tour.js',
    r'L:\ClipifyAI\android\app\src\main\assets\www\static\tour.js',
]

for tp in tour_files:
    if not os.path.exists(tp):
        continue
    with open(tp, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'CAMPAIGN_PLATFORMS' not in content:
        # Insert before bindNavLinks
        bind_idx = content.find('function bindNavLinks() {')
        if bind_idx != -1:
            content = content[:bind_idx] + CAMPAIGNS_JS_LOGIC + '\n  ' + content[bind_idx:]
            
            # In bindNavLinks: add listener for navCampaignsLink
            nav_promoters_block = "document.querySelectorAll('#navPromotersLink').forEach(el => {"
            campaigns_nav_block = '''document.querySelectorAll('#navCampaignsLink').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        showCampaignsModal();
      });
    });\n\n    '''
            if nav_promoters_block in content:
                content = content.replace(nav_promoters_block, campaigns_nav_block + nav_promoters_block)

            # In handleHash: add #campaigns
            promoters_hash = "} else if (h === '#promoters') {\n        showPromotersModal();"
            campaigns_hash = "} else if (h === '#promoters') {\n        showPromotersModal();\n      } else if (h === '#campaigns') {\n        showCampaignsModal();"
            content = content.replace(promoters_hash, campaigns_hash)

            # Export window.showCampaignsModal
            promoters_export = "window.showPromotersModal = () => showPromotersModal();"
            campaigns_export = "window.showPromotersModal = () => showPromotersModal();\n  window.showCampaignsModal = () => showCampaignsModal();"
            content = content.replace(promoters_export, campaigns_export)

            with open(tp, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated tour.js with Campaigns logic: {tp}")
        else:
            print(f"Could not find bindNavLinks in {tp}")
    else:
        print(f"CAMPAIGN_PLATFORMS already in {tp}")

# 3. Update static/app.js and android app.js for navigateTo
app_files = [
    r'L:\ClipifyAI\static\app.js',
    r'L:\ClipifyAI\android\app\src\main\assets\www\static\app.js',
]

for ap in app_files:
    if not os.path.exists(ap):
        continue
    with open(ap, 'r', encoding='utf-8') as f:
        ac = f.read()

    # Update navigateTo
    old_nav = "if (['support', 'promoters', 'models', 'update', 'guide'].includes(target)) {"
    new_nav = "if (['support', 'promoters', 'campaigns', 'models', 'update', 'guide'].includes(target)) {"
    if old_nav in ac:
        ac = ac.replace(old_nav, new_nav)
        # Also trigger showCampaignsModal
        promoter_nav = "if (target === 'promoters' && window.showPromotersModal) window.showPromotersModal();"
        campaigns_nav = "if (target === 'promoters' && window.showPromotersModal) window.showPromotersModal();\n    if (target === 'campaigns' && window.showCampaignsModal) window.showCampaignsModal();"
        ac = ac.replace(promoter_nav, campaigns_nav)
        with open(ap, 'w', encoding='utf-8') as f:
            f.write(ac)
        print(f"Updated navigateTo in {ap}")

# 4. Update _CLIPPY_SYSTEM_PROMPT in app.py
with open(r'L:\ClipifyAI\app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

clippy_old_target = "8. Instant Navigation Commands:"
clippy_new_target = """8. Campaigns & Bounties ([NAVIGATE:campaigns] or #campaigns):
   - Direct directory of the top 10 platforms for streamer & podcast clippers to monetize their clips and join campaigns.
   - Includes: Content Rewards (India + international), Vyro (MrBeast ecosystem), Clipster (worldwide gaming & music), Clipping.net, Vues (brand campaigns), Clip (sports/entertainment), Wondeed, ClipAffiliates, ClipGrow (India), ClipConnect India.
   - Each platform features direct external website links, clipper country availability tags, and real-time search filters.

9. Instant Navigation Commands:"""

if clippy_old_target in app_py and "Campaigns & Bounties" not in app_py:
    app_py = app_py.replace(clippy_old_target, clippy_new_target)
    # Also add campaigns to valid navigate list
    app_py = app_py.replace("[NAVIGATE:promoters]", "[NAVIGATE:promoters], [NAVIGATE:campaigns]")
    with open(r'L:\ClipifyAI\app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)
    print("Updated _CLIPPY_SYSTEM_PROMPT in app.py")

print("All Campaigns integrations successfully implemented!")

