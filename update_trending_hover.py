import os
import re

p = r'L:\ClipifyAI\static\trending.js'
with open(p, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add extractVideoId and card attributes in renderStreamCard
old_stream = """  function renderStreamCard(stream, platform) {
    const badgeClass = platform === 'twitch' ? 'trending-badge-live-twitch' : (platform === 'kick' ? 'trending-badge-live-kick' : '');
    const pulseDotColor = platform === 'twitch' ? '#9146FF' : (platform === 'kick' ? '#22C55E' : '#ef4444');

    return `
      <div class="trending-card" data-url="${escapeHtml(stream.url)}" data-is-live="true">"""

new_stream = """  function extractVideoId(url) {
    if (!url) return '';
    const m = url.match(/(?:youtu\\.be\\/|youtube\\.com\\/(?:embed\\/|v\\/|watch\\?v=|live\\/|shorts\\/))([\\w-]{11})/);
    return m ? m[1] : '';
  }

  let activeHoverTimer = null;
  let activeHoverPlayer = null;

  function renderStreamCard(stream, platform) {
    const badgeClass = platform === 'twitch' ? 'trending-badge-live-twitch' : (platform === 'kick' ? 'trending-badge-live-kick' : '');
    const pulseDotColor = platform === 'twitch' ? '#9146FF' : (platform === 'kick' ? '#22C55E' : '#ef4444');
    const vidId = stream.id || extractVideoId(stream.url);

    return `
      <div class="trending-card" data-url="${escapeHtml(stream.url)}" data-is-live="true" data-platform="${escapeHtml(platform)}" data-stream-id="${escapeHtml(vidId)}" data-channel="${escapeHtml(stream.channel || '')}">"""

if old_stream in content:
    content = content.replace(old_stream, new_stream)
else:
    print("Warning: old_stream not matched directly")

# 2. Update renderVideoCard
old_video = """  function renderVideoCard(video) {
    return `
      <div class="trending-card" data-url="${escapeHtml(video.url)}" data-is-live="false">"""

new_video = """  function renderVideoCard(video) {
    const vidId = video.id || extractVideoId(video.url);
    return `
      <div class="trending-card" data-url="${escapeHtml(video.url)}" data-is-live="false" data-platform="youtube" data-video-id="${escapeHtml(vidId)}" data-channel="${escapeHtml(video.channel || '')}">"""

if old_video in content:
    content = content.replace(old_video, new_video)

# 3. Add titles to buttons
content = content.replace(
    'class="trending-btn-clip btn-clip-stream" data-stream-url="${escapeHtml(stream.url)}"',
    'class="trending-btn-clip btn-clip-stream" data-stream-url="${escapeHtml(stream.url)}" data-stream-title="${escapeHtml(stream.title)}"'
)
content = content.replace(
    'class="trending-btn-clip btn-clip-video" data-video-url="${escapeHtml(video.url)}"',
    'class="trending-btn-clip btn-clip-video" data-video-url="${escapeHtml(video.url)}" data-video-title="${escapeHtml(video.title)}"'
)

# 4. Update attachCardActions and add hover listeners
old_attach = """  function attachCardActions() {
    // 1. Live stream clip buttons -> Opens Live Studio with stream running ready to clip
    document.querySelectorAll('.btn-clip-stream').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.streamUrl;
        if (url && window.clipTrendingLive) {
          window.clipTrendingLive(url);
        }
      });
    });

    // 2. Video clip buttons -> Opens Create section with video imported
    document.querySelectorAll('.btn-clip-video').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.videoUrl;
        if (url && window.clipTrendingVideo) {
          window.clipTrendingVideo(url);
        }
      });
    });
  }"""

new_attach = """  function attachCardActions() {
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
  }"""

if old_attach in content:
    content = content.replace(old_attach, new_attach)
else:
    print("Warning: old_attach not matched directly")

with open(p, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated trending.js!")

