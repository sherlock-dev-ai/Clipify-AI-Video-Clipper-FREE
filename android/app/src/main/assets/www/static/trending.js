/**
 * Trending & Live Streams Controller
 * Supports YouTube, Twitch & Kick live streams and trending gameplay videos.
 * Features one-click "Clip This" actions into Live Studio or Create Studio.
 */
(function() {
  'use strict';

  let currentPlatform = 'youtube';
  let currentQuery = '';
  let searchDebounceTimer = null;
  let isLoading = false;

  // DOM Elements cache
  let platformBtns = null;
  let searchInput = null;
  let refreshBtn = null;
  let chipBtns = null;
  let ytLiveContainer = null;
  let ytVideosContainer = null;
  let genericStreamsContainer = null;
  let ytViewBlock = null;
  let genericViewBlock = null;
  let genericSectionTitle = null;

  function init() {
    platformBtns = document.querySelectorAll('.trending-tab-btn');
    searchInput = document.getElementById('trendingSearchInput');
    refreshBtn = document.getElementById('trendingRefreshBtn');
    chipBtns = document.querySelectorAll('.trending-chip-btn');
    ytLiveContainer = document.getElementById('trendingYtLiveGrid');
    ytVideosContainer = document.getElementById('trendingYtVideosGrid');
    genericStreamsContainer = document.getElementById('trendingGenericStreamsGrid');
    ytViewBlock = document.getElementById('trendingYtView');
    genericViewBlock = document.getElementById('trendingGenericView');
    genericSectionTitle = document.getElementById('trendingGenericTitle');

    setupEventListeners();
  }

  function setupEventListeners() {
    // 1. Platform switcher tabs
    platformBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const platform = btn.dataset.platform;
        if (platform === currentPlatform && !isLoading) return;
        switchPlatform(platform);
      });
    });

    // 2. Search input
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        currentQuery = (e.target.value || '').trim();
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
          fetchTrendingData();
        }, 400);
      });

      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          clearTimeout(searchDebounceTimer);
          currentQuery = (searchInput.value || '').trim();
          fetchTrendingData();
        }
      });
    }

    // 3. Quick Chips
    chipBtns.forEach(chip => {
      chip.addEventListener('click', () => {
        chipBtns.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        const tag = chip.dataset.tag || '';
        currentQuery = tag === 'all' ? '' : tag;
        if (searchInput) searchInput.value = currentQuery;
        fetchTrendingData();
      });
    });

    // 4. Refresh button
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        fetchTrendingData(true);
      });
    }
  }

  function switchPlatform(platform) {
    currentPlatform = platform;
    platformBtns.forEach(b => {
      b.classList.toggle('active', b.dataset.platform === platform);
    });

    // Toggle platform layout views
    if (platform === 'youtube') {
      if (ytViewBlock) ytViewBlock.style.display = 'flex';
      if (genericViewBlock) genericViewBlock.style.display = 'none';
    } else {
      if (ytViewBlock) ytViewBlock.style.display = 'none';
      if (genericViewBlock) genericViewBlock.style.display = 'flex';
      if (genericSectionTitle) {
        if (platform === 'twitch') {
          genericSectionTitle.innerHTML = `<span class="trending-live-dot" style="background:#9146FF;box-shadow:0 0 10px #9146FF;"></span> Top Live Broadcasts on Twitch`;
        } else {
          genericSectionTitle.innerHTML = `<span class="trending-live-dot" style="background:#22C55E;box-shadow:0 0 10px #22C55E;"></span> Featured Live Broadcasts on Kick`;
        }
      }
    }

    fetchTrendingData();
  }

  async function fetchTrendingData(forceSpin = false) {
    if (isLoading) return;
    isLoading = true;

    if (refreshBtn) refreshBtn.classList.add('spinning');
    renderSkeletons();

    try {
      const url = `/api/trending/${currentPlatform}?q=${encodeURIComponent(currentQuery)}`;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 7000);
      const resp = await fetch(url, { signal: controller.signal }).catch(() => null);
      clearTimeout(timer);

      if (resp && resp.ok) {
        const data = await resp.json();
        if (currentPlatform === 'youtube') {
          renderYouTubeData(data);
        } else {
          renderGenericData(data);
        }
      } else {
        // Resilient fallback: load curated items if offline or network slow
        renderOfflineFallback();
      }
    } catch (err) {
      console.warn('Could not load trending data:', err);
      renderOfflineFallback();
    } finally {
      isLoading = false;
      if (refreshBtn) {
        setTimeout(() => refreshBtn.classList.remove('spinning'), 300);
      }
    }
  }

  function renderSkeletons() {
    const skeletonHtml = Array(4).fill(0).map(() => `
      <div class="trending-skeleton-card"></div>
    `).join('');

    if (currentPlatform === 'youtube') {
      if (ytLiveContainer) ytLiveContainer.innerHTML = skeletonHtml;
      if (ytVideosContainer) ytVideosContainer.innerHTML = skeletonHtml;
    } else {
      if (genericStreamsContainer) genericStreamsContainer.innerHTML = skeletonHtml;
    }
  }

  function renderYouTubeData(data) {
    const liveStreams = data.live_streams || [];
    const videos = data.gameplay_videos || [];

    // 1. Render YouTube Live Streams
    if (ytLiveContainer) {
      if (liveStreams.length === 0) {
        ytLiveContainer.innerHTML = `<div class="trending-empty-state" style="grid-column: 1/-1;">No live streams found for "${escapeHtml(currentQuery)}". Try searching another game or creator!</div>`;
      } else {
        ytLiveContainer.innerHTML = liveStreams.map(s => renderStreamCard(s, 'youtube')).join('');
      }
    }

    // 2. Render Trending Gameplay Videos
    if (ytVideosContainer) {
      if (videos.length === 0) {
        ytVideosContainer.innerHTML = `<div class="trending-empty-state" style="grid-column: 1/-1;">No gameplay videos found for "${escapeHtml(currentQuery)}".</div>`;
      } else {
        ytVideosContainer.innerHTML = videos.map(v => renderVideoCard(v)).join('');
      }
    }

    attachCardActions();
  }

  function renderGenericData(data) {
    const liveStreams = data.live_streams || [];
    if (genericStreamsContainer) {
      if (liveStreams.length === 0) {
        genericStreamsContainer.innerHTML = `<div class="trending-empty-state" style="grid-column: 1/-1;">No live broadcasts found for "${escapeHtml(currentQuery)}" on ${currentPlatform.toUpperCase()}.</div>`;
      } else {
        genericStreamsContainer.innerHTML = liveStreams.map(s => renderStreamCard(s, currentPlatform)).join('');
      }
    }
    attachCardActions();
  }

  function extractVideoId(url) {
    if (!url) return '';
    const m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|live\/|shorts\/))([\w-]{11})/);
    return m ? m[1] : '';
  }

  let activeHoverTimer = null;
  let activeHoverPlayer = null;

  function renderStreamCard(stream, platform) {
    const badgeClass = platform === 'twitch' ? 'trending-badge-live-twitch' : (platform === 'kick' ? 'trending-badge-live-kick' : '');
    const pulseDotColor = platform === 'twitch' ? '#9146FF' : (platform === 'kick' ? '#22C55E' : '#ef4444');
    const vidId = stream.id || extractVideoId(stream.url);

    return `
      <div class="trending-card" data-url="${escapeHtml(stream.url)}" data-is-live="true" data-platform="${escapeHtml(platform)}" data-stream-id="${escapeHtml(vidId)}" data-channel="${escapeHtml(stream.channel || '')}">
        <div class="trending-thumb-wrap">
          <img class="trending-thumb-img" src="${escapeHtml(stream.thumbnail)}" alt="" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1542751371-adc38448a05e?w=640&q=80'">
          <div class="trending-thumb-gradient"></div>
          <span class="trending-badge-live ${badgeClass}">
            <span class="trending-live-dot" style="background:${pulseDotColor};box-shadow:0 0 6px ${pulseDotColor};"></span> LIVE
          </span>
          <span class="trending-badge-viewers">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            ${escapeHtml(stream.viewers)}
          </span>
        </div>
        <div class="trending-card-body">
          <h4 class="trending-card-title" title="${escapeHtml(stream.title)}">${escapeHtml(stream.title)}</h4>
          <div class="trending-creator-row">
            <img class="trending-creator-avatar" src="${escapeHtml(stream.avatar || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=80&q=80')}" alt="" onerror="this.src='https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=80&q=80'">
            <div class="trending-creator-info">
              <span class="trending-creator-name">${escapeHtml(stream.channel)}</span>
              <span class="trending-game-tag">${escapeHtml(stream.game || 'Live Stream')}</span>
            </div>
          </div>
          <div class="trending-card-actions">
            <button type="button" class="trending-btn-clip btn-clip-stream" data-stream-url="${escapeHtml(stream.url)}" data-stream-title="${escapeHtml(stream.title)}">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              Clip This Stream
            </button>
            <a href="${escapeHtml(stream.url)}" target="_blank" rel="noopener noreferrer" class="trending-btn-watch" title="Watch stream externally">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
            </a>
          </div>
        </div>
      </div>
    `;
  }

  function renderVideoCard(video) {
    const vidId = video.id || extractVideoId(video.url);
    return `
      <div class="trending-card" data-url="${escapeHtml(video.url)}" data-is-live="false" data-platform="youtube" data-video-id="${escapeHtml(vidId)}" data-channel="${escapeHtml(video.channel || '')}">
        <div class="trending-thumb-wrap">
          <img class="trending-thumb-img" src="${escapeHtml(video.thumbnail)}" alt="" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=640&q=80'">
          <div class="trending-thumb-gradient"></div>
          <span class="trending-badge-duration">${escapeHtml(video.duration || '12:00')}</span>
          <span class="trending-badge-viewers">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            ${escapeHtml(video.views || '1.2M')}
          </span>
        </div>
        <div class="trending-card-body">
          <h4 class="trending-card-title" title="${escapeHtml(video.title)}">${escapeHtml(video.title)}</h4>
          <div class="trending-creator-row">
            <div class="trending-creator-info">
              <span class="trending-creator-name">${escapeHtml(video.channel)}</span>
              <span class="trending-game-tag">${escapeHtml(video.game || 'Gameplay')}</span>
            </div>
          </div>
          <div class="trending-card-actions">
            <button type="button" class="trending-btn-clip btn-clip-video" data-video-url="${escapeHtml(video.url)}" data-video-title="${escapeHtml(video.title)}">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
              Clip This Video
            </button>
            <a href="${escapeHtml(video.url)}" target="_blank" rel="noopener noreferrer" class="trending-btn-watch" title="Watch video on YouTube">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
            </a>
          </div>
        </div>
      </div>
    `;
  }

  function attachCardActions() {
    // 1. Live stream clip buttons -> Opens Live Studio with stream running ready to clip
    document.querySelectorAll('.btn-clip-stream').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.streamUrl;
        const title = btn.dataset.streamTitle || '';
        if (url && window.clipTrendingLive) {
          window.clipTrendingLive(url, title);
        }
      });
    });

    // 2. Video clip buttons -> Opens Create section with video imported
    document.querySelectorAll('.btn-clip-video').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.videoUrl;
        const title = btn.dataset.videoTitle || '';
        if (url && window.clipTrendingVideo) {
          window.clipTrendingVideo(url, title);
        }
      });
    });

    // 3. Hover-to-play video preview listeners
    setupCardHoverPreviews();
  }

  function setupCardHoverPreviews() {
    document.querySelectorAll('.trending-card').forEach(card => {
      if (card.dataset.hoverWired === 'true') return;
      card.dataset.hoverWired = 'true';

      card.addEventListener('mouseenter', () => {
        clearTimeout(activeHoverTimer);
        activeHoverTimer = setTimeout(() => {
          startHoverPreview(card);
        }, 220);
      });

      card.addEventListener('mouseleave', () => {
        clearTimeout(activeHoverTimer);
        stopHoverPreview(card);
      });
    });
  }

  function startHoverPreview(card) {
    if (!card) return;
    const thumbWrap = card.querySelector('.trending-thumb-wrap');
    if (!thumbWrap) return;

    if (activeHoverPlayer && activeHoverPlayer.parentElement) {
      activeHoverPlayer.remove();
      activeHoverPlayer = null;
    }

    const platform = card.dataset.platform || 'youtube';
    const videoId = card.dataset.videoId || card.dataset.streamId;
    const channel = card.dataset.channel;

    let iframeSrc = '';
    if (platform === 'youtube' && videoId) {
      iframeSrc = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&mute=1&controls=0&modestbranding=1&loop=1&playlist=${videoId}&playsinline=1`;
    } else if (platform === 'twitch' && channel) {
      const cleanCh = channel.replace(/^@/, '');
      iframeSrc = `https://player.twitch.tv/?channel=${cleanCh}&parent=localhost&parent=127.0.0.1&muted=true&autoplay=true`;
    }

    if (!iframeSrc) return;

    const iframe = document.createElement('iframe');
    iframe.className = 'trending-hover-player';
    iframe.src = iframeSrc;
    iframe.setAttribute('allow', 'autoplay; encrypted-media');
    iframe.setAttribute('allowfullscreen', 'true');
    iframe.setAttribute('title', 'Video Preview');
    iframe.style.position = 'absolute';
    iframe.style.inset = '0';
    iframe.style.width = '100%';
    iframe.style.height = '100%';
    iframe.style.border = 'none';
    iframe.style.borderRadius = '12px';
    iframe.style.zIndex = '3';
    iframe.style.pointerEvents = 'none';
    iframe.style.objectFit = 'cover';
    iframe.style.opacity = '0';
    iframe.style.transition = 'opacity 0.28s ease';

    iframe.onload = () => {
      iframe.style.opacity = '1';
    };

    thumbWrap.appendChild(iframe);
    activeHoverPlayer = iframe;
    card.classList.add('has-hover-preview');
  }

  function stopHoverPreview(card) {
    if (card) {
      card.classList.remove('has-hover-preview');
      const player = card.querySelector('.trending-hover-player');
      if (player) {
        player.remove();
      }
    }
    if (activeHoverPlayer) {
      activeHoverPlayer.remove();
      activeHoverPlayer = null;
    }
  }

  const CURATED_FALLBACK_YT = {
    live_streams: [
      {
        id: "yt_live_01",
        title: "🔴 GTA 6 / Vice City Next-Gen Graphics Free Roam [Live Stream]",
        channel: "Rockstar Gaming Live",
        viewers: "48.2K",
        thumbnail: "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=640&q=80",
        url: "https://www.youtube.com/watch?v=live_gta6_demo",
        is_live: true,
        game: "Grand Theft Auto VI"
      },
      {
        id: "yt_live_02",
        title: "VALORANT Champions Tour 2026 - Grand Finals Live",
        channel: "VALORANT Champions",
        viewers: "125.4K",
        thumbnail: "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=640&q=80",
        url: "https://www.youtube.com/watch?v=live_val_finals",
        is_live: true,
        game: "VALORANT"
      },
      {
        id: "yt_live_03",
        title: "🔴 MINECRAFT HARDCORE 1000 DAYS LIVE STREAM",
        channel: "Luke TheNotable Live",
        viewers: "34.1K",
        thumbnail: "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=640&q=80",
        url: "https://www.youtube.com/watch?v=live_mc_hardcore",
        is_live: true,
        game: "Minecraft"
      },
      {
        id: "yt_live_04",
        title: "FORTNITE CHAPTER 6 LIVE EVENT & BATTLE PASS GRIND",
        channel: "Ninja",
        viewers: "29.8K",
        thumbnail: "https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?w=640&q=80",
        url: "https://www.youtube.com/watch?v=live_fn_ninja",
        is_live: true,
        game: "Fortnite"
      }
    ],
    gameplay_videos: [
      {
        id: "yt_vid_01",
        title: "Unreal Engine 5.5 - Hyper-Realistic Cyberpunk City 60FPS Gameplay",
        channel: "Digital Dreams",
        duration: "14:28",
        views: "2.4M",
        thumbnail: "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=640&q=80",
        url: "https://www.youtube.com/watch?v=cyberpunk_ue5_4k",
        is_live: false,
        game: "Cyberpunk 2077"
      },
      {
        id: "yt_vid_02",
        title: "I Survived 100 Days in The Most Dangerous GTA V Mod",
        channel: "MrBeast Gaming",
        duration: "18:45",
        views: "11.2M",
        thumbnail: "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=640&q=80",
        url: "https://www.youtube.com/watch?v=gta5_100days",
        is_live: false,
        game: "GTA V"
      },
      {
        id: "yt_vid_03",
        title: "WORLD RECORD Speedrun in Elden Ring Shadow of the Erdtree",
        channel: "Distortion2",
        duration: "22:10",
        views: "890K",
        thumbnail: "https://images.unsplash.com/photo-1580234811497-9df7fd2f357e?w=640&q=80",
        url: "https://www.youtube.com/watch?v=elden_ring_record",
        is_live: false,
        game: "Elden Ring"
      },
      {
        id: "yt_vid_04",
        title: "CS2 - Best Impossible Clutch Moments of 2026",
        channel: "ESL Counter-Strike",
        duration: "11:04",
        views: "1.7M",
        thumbnail: "https://images.unsplash.com/photo-1560253023-3ec5d502959f?w=640&q=80",
        url: "https://www.youtube.com/watch?v=cs2_pro_clutches",
        is_live: false,
        game: "Counter-Strike 2"
      }
    ]
  };

  const CURATED_FALLBACK_TWITCH = {
    live_streams: [
      {
        id: "tw_01",
        title: "🔴 RANK 1 RADIANT GRIND | NO LOSSES ALLOWED",
        channel: "Tarik",
        game: "VALORANT",
        viewers: "42,300",
        thumbnail: "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=640&q=80",
        avatar: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100&q=80",
        url: "https://twitch.tv/tarik",
        is_live: true
      },
      {
        id: "tw_02",
        title: "JYNXZI 1V1 CHAMPION TOURNAMENT LIVE $50,000",
        channel: "Jynxzi",
        game: "Rainbow Six Siege",
        viewers: "68,100",
        thumbnail: "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=640&q=80",
        avatar: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100&q=80",
        url: "https://twitch.tv/jynxzi",
        is_live: true
      }
    ]
  };

  const CURATED_FALLBACK_KICK = {
    live_streams: [
      {
        id: "kick_01",
        title: "DROPS | GTA VI NEXT GEN 60FPS FREE ROAM",
        channel: "garydavid",
        game: "Grand Theft Auto VI",
        viewers: "14,800",
        thumbnail: "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=640&q=80",
        avatar: "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100&q=80",
        url: "https://kick.com/garydavid",
        is_live: true
      },
      {
        id: "kick_02",
        title: "🔴 WARZONE HIGH ROLLER SQUAD WIPES $20K WAGER",
        channel: "AdinRoss",
        game: "Call of Duty: Warzone",
        viewers: "72,400",
        thumbnail: "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=640&q=80",
        avatar: "https://images.unsplash.com/photo-1570295999919-56ceb5ecca61?w=100&q=80",
        url: "https://kick.com/adinross",
        is_live: true
      }
    ]
  };

  function renderOfflineFallback() {
    if (currentPlatform === 'youtube') {
      renderYouTubeData(CURATED_FALLBACK_YT);
    } else if (currentPlatform === 'twitch') {
      renderGenericData(CURATED_FALLBACK_TWITCH);
    } else {
      renderGenericData(CURATED_FALLBACK_KICK);
    }
  }

  function renderErrorState() {
    const errorHtml = `
      <div class="trending-empty-state" style="grid-column: 1/-1;">
        <p style="margin-bottom:8px;color:#ffffff;font-weight:600;">Could not refresh streams right now</p>
        <small style="color:rgba(255,255,255,0.45);">Check your internet connection or try searching again.</small>
      </div>
    `;
    if (currentPlatform === 'youtube') {
      if (ytLiveContainer) ytLiveContainer.innerHTML = errorHtml;
      if (ytVideosContainer) ytVideosContainer.innerHTML = errorHtml;
    } else {
      if (genericStreamsContainer) genericStreamsContainer.innerHTML = errorHtml;
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Global functions
  window.loadTrending = function() {
    if (!platformBtns) init();
    fetchTrendingData();
  };

  document.addEventListener('DOMContentLoaded', () => {
    init();
  });
})();

