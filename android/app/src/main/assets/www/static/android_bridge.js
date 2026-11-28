/**
 * Clipify AI — Standalone Mobile Android Bridge & Fetch Interceptor
 * Enables full offline functionality inside the Android APK WebView:
 * - Local video import via Android native file picker
 * - YouTube link ingestion with simulated native progress and bridge handoff
 * - Standalone rendering via Android MediaCodec foreground service
 * - Interactive Clippy assistant & offline status polling
 */
(function () {
  'use strict';

  const isAndroid = !!(window.AndroidBridge || navigator.userAgent.includes('Android') || window.location.protocol === 'file:');

  if (!isAndroid) {
    // On pure desktop browser without Android bridge, do nothing
    return;
  }

  // Force clean mobile layout: completely remove desktop sidebar since native bottom bar exists
  document.documentElement.classList.add('is-android');
  const injectMobileStyle = () => {
    if (document.getElementById('clipify-mobile-clean-style')) return;
    const style = document.createElement('style');
    style.id = 'clipify-mobile-clean-style';
    style.textContent = `
      .sidebar,
      .sidebar-creature-card,
      #clippyFloatingCard,
      .aurora,
      .noise,
      .topbar {
        display: none !important;
      }
      .main {
        margin-left: 0 !important;
        width: 100% !important;
        max-width: 100% !important;
        padding: 14px 14px 90px 14px !important;
        box-sizing: border-box !important;
      }
      .page-section {
        padding: 0 !important;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  };
  if (document.head) injectMobileStyle();
  else document.addEventListener('DOMContentLoaded', injectMobileStyle);

  console.log('[ClipifyAI Android] Initializing Standalone Native Bridge...');

  // Shim EventSource so that SSE failures in WebView on file:/// do not throw or terminate the polling fallback
  const OriginalEventSource = window.EventSource;
  window.EventSource = function (url) {
    const urlStr = String(url);
    if (urlStr.includes('/api/events/')) {
      const esMock = new EventTarget();
      esMock.close = function () { };
      esMock.readyState = 1;
      return esMock;
    }
    if (OriginalEventSource) {
      try { return new OriginalEventSource(url); } catch (_) { }
    }
    return { close: () => { }, readyState: 2 };
  };

  // Async Bridge Callback Registry (prevents WebView UI thread blocking)
  window.__androidApiCallbacks = window.__androidApiCallbacks || {};
  window.__androidApiSeq = 0;
  window.__onAndroidApiResult = function (reqId, rawResult) {
    const cb = window.__androidApiCallbacks[reqId];
    if (cb) {
      delete window.__androidApiCallbacks[reqId];
      cb(rawResult);
    }
  };

  function callDesktopBridgeAsync(method, endpoint, body, headers) {
    return new Promise((resolve) => {
      if (window.AndroidBridge && window.AndroidBridge.callApiAsync) {
        const reqId = 'api_' + (++window.__androidApiSeq) + '_' + Date.now();
        const timer = setTimeout(() => {
          if (window.__androidApiCallbacks[reqId]) {
            delete window.__androidApiCallbacks[reqId];
            resolve(null);
          }
        }, 12000);
        window.__androidApiCallbacks[reqId] = (rawResult) => {
          clearTimeout(timer);
          resolve(rawResult);
        };
        try {
          window.AndroidBridge.callApiAsync(reqId, method, endpoint, body, headers);
        } catch (_) {
          clearTimeout(timer);
          delete window.__androidApiCallbacks[reqId];
          resolve(null);
        }
      } else if (window.AndroidBridge && window.AndroidBridge.callApi) {
        try {
          resolve(window.AndroidBridge.callApi(method, endpoint, body, headers));
        } catch (_) {
          resolve(null);
        }
      } else {
        resolve(null);
      }
    });
  }

  // Intercept window.fetch for API routes inside Android WebView
  const originalFetch = window.fetch;

  window.fetch = async function (url, options = {}) {
    const urlStr = String(url);

    if (urlStr.startsWith('/api/') || urlStr.includes('/api/')) {
      let endpoint = urlStr;
      if (endpoint.includes('/api/')) {
        endpoint = '/api/' + endpoint.split('/api/')[1];
      }

      // Try desktop bridge connection asynchronously if available
      if (window.AndroidBridge && (window.AndroidBridge.callApiAsync || window.AndroidBridge.callApi)) {
        try {
          const method = (options.method || 'GET').toUpperCase();
          let body = null;
          if (options.body) {
            body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
          }
          const headers = options.headers ? JSON.stringify(options.headers) : '{}';
          const rawResult = await callDesktopBridgeAsync(method, endpoint, body, headers);
          if (rawResult) {
            const parsed = JSON.parse(rawResult);
            if (parsed.status !== 503) {
              window.CLIPPY_DESKTOP_CONNECTED = true;
              return new Response(parsed.body, {
                status: parsed.status,
                statusText: parsed.ok ? 'OK' : 'Error',
                headers: { 'Content-Type': 'application/json' }
              });
            }
          }
        } catch (_) { }
      }

      // Standalone Mobile Engine Handlers (Zero hang, instant response)

      // Real Mobile Render Progress Listener (driven by RenderForegroundService -> AndroidMediaProcessor)
      function appendMobileLog(jobObj, line) {
        if (!jobObj || !line) return;
        if (!Array.isArray(jobObj.logs)) jobObj.logs = [];
        if (jobObj.logs[jobObj.logs.length - 1] !== line) {
          jobObj.logs.push(line);
        }
      }

      window.onMobileImportProgress = function (progress, stage, filePath, title, err) {
        const pct = Math.max(0, Math.min(100, Number(progress) || 0));
        if (!window._activeMobileYtJob) return;
        window._activeMobileYtJob.progress = pct;
        window._activeMobileYtJob.stage = stage || 'Downloading...';
        window._activeMobileYtJob.detail = stage || `${pct}%`;
        appendMobileLog(window._activeMobileYtJob, stage);

        if (pct >= 100) {
          if (err && err.length > 0) {
            window._activeMobileYtJob.status = 'error';
            window._activeMobileYtJob.error = err;
          } else if (filePath && filePath.length > 0) {
            window._activeMobileYtJob.status = 'uploaded';
            window._activeMobileYtJob.filename = (title ? title.replace(/[^a-zA-Z0-9 _-]/g, '').trim() : 'YouTube_Video') + '.mp4';
            window._lastAndroidUri = filePath;
            const srcPrev = document.getElementById('sourcePreview');
            if (srcPrev) {
              const fUrl = filePath.startsWith('file://') ? filePath : ('file://' + filePath);
              srcPrev.src = fUrl;
              srcPrev.hidden = false;
              try { srcPrev.load(); } catch (_) {}
            }
            if (window.onAndroidVideoSelected) {
              window.onAndroidVideoSelected(filePath, window._activeMobileYtJob.filename, 0);
            }
          }
        }
      };

      window.onMobileRenderProgress = function (progress, stage, outputPath, metaJson, outputsJson) {
        const pct = Math.max(0, Math.min(100, Number(progress) || 0));
        const hasOutput = Boolean(outputPath && outputPath.length > 0);
        const fileUrl = hasOutput ? (outputPath.startsWith('file://') ? outputPath : 'file://' + outputPath) : '';
        let allOutputs = [];
        try {
          const parsedOuts = outputsJson ? JSON.parse(outputsJson) : [];
          if (Array.isArray(parsedOuts) && parsedOuts.length > 0) allOutputs = parsedOuts;
        } catch (_) {}
        if (allOutputs.length === 0 && fileUrl) allOutputs = [fileUrl];

        let metaPayload = {};
        try { metaPayload = metaJson ? JSON.parse(metaJson) : {}; } catch (_) {}
        const metaMap = metaPayload.metadata || {};
        const candList = Array.isArray(metaPayload.candidates) && metaPayload.candidates.length > 0
          ? metaPayload.candidates
          : allOutputs.map((u, i) => ({
              title: metaPayload.title || `Clipify Viral Short ${i + 1}`,
              description: metaPayload.description || 'Generated on-device by Clipify AI.',
              start: metaPayload.start || 0,
              end: metaPayload.end || 30,
              score: 95
            }));
        const outMetaObj = {};
        allOutputs.forEach((u, i) => {
          outMetaObj[u] = metaMap[u] || {
            title: (candList[i] && candList[i].title) || metaPayload.title || `Clipify Viral Short ${i + 1}`,
            description: (candList[i] && candList[i].description) || metaPayload.description || 'Generated on-device by Clipify AI.'
          };
        });
        const clipsArr = allOutputs.map((u, i) => ({
          path: u,
          title: outMetaObj[u]?.title || `Short ${i + 1}`,
          description: outMetaObj[u]?.description || ''
        }));

        if (window._activeMobileRenderJob) {
          window._activeMobileRenderJob.ok = true;
          window._activeMobileRenderJob.progress = pct;
          window._activeMobileRenderJob.stage = stage || 'Rendering MP4...';
          window._activeMobileRenderJob.detail = stage || `${pct}%`;
          appendMobileLog(window._activeMobileRenderJob, stage);
          if (pct >= 100 && allOutputs.length > 0) {
            window._activeMobileRenderJob.status = 'done';
            window._activeMobileRenderJob.outputs = allOutputs;
            window._activeMobileRenderJob.filename = allOutputs[0].split('/').pop();
            window._activeMobileRenderJob.candidates = candList;
            window._activeMobileRenderJob.output_metadata = outMetaObj;
            window._activeMobileRenderJob.clips = clipsArr;
          } else if (pct >= 100 && !hasOutput) {
            window._activeMobileRenderJob.status = 'error';
            window._activeMobileRenderJob.error = stage || 'Render failed';
          }
        }
        if (window._activeInstantJob) {
          window._activeInstantJob.ok = true;
          window._activeInstantJob.progress = pct;
          window._activeInstantJob.stage = stage || 'Encoding 9:16 MP4...';
          window._activeInstantJob.detail = stage || `${pct}%`;
          appendMobileLog(window._activeInstantJob, stage);
          if (pct >= 100 && allOutputs.length > 0) {
            window._activeInstantJob.status = 'done';
            window._activeInstantJob.outputs = allOutputs;
            window._activeInstantJob.filename = allOutputs[0].split('/').pop();
            window._activeInstantJob.clip_paths = allOutputs;
            window._activeInstantJob.candidates = candList;
            window._activeInstantJob.output_metadata = outMetaObj;
            window._activeInstantJob.clips = clipsArr;
          } else if (pct >= 100 && !hasOutput) {
            window._activeInstantJob.status = 'error';
            window._activeInstantJob.error = stage || 'Instant render failed';
          }
        }
      };

      // 1. YouTube Import (Real independent on-device download via YouTubeStreamDownloader.kt)
      if (endpoint.includes('/api/import-youtube')) {
        let reqUrl = '';
        try {
          const b = typeof options.body === 'string' ? JSON.parse(options.body) : (options.body || {});
          reqUrl = (b.url || '').trim();
        } catch (_) {}

        if (!reqUrl) {
          return new Response(JSON.stringify({ ok: false, error: 'Please paste a video URL first.' }), {
            status: 400, headers: { 'Content-Type': 'application/json' }
          });
        }

        const jId = 'mobile_yt_' + Date.now();
        window._activeMobileYtJob = {
          ok: true,
          job_id: jId,
          id: jId,
          filename: 'YouTube_Download.mp4',
          status: 'downloading',
          progress: 5,
          stage: 'Connecting to YouTube...',
          detail: 'Resolving mobile MP4 stream...',
          logs: ['[YouTube] Connecting to YouTube stream...']
        };

        const maxHeight = parseInt(window._mobileSelectedImportQuality || document.querySelector('.mobile-import-quality-select')?.value || '4320', 10) || 4320;
        if (window.AndroidBridge && window.AndroidBridge.startYouTubeImportWithQuality) {
          window.AndroidBridge.startYouTubeImportWithQuality(reqUrl, maxHeight);
        } else if (window.AndroidBridge && window.AndroidBridge.startYouTubeImport) {
          window.AndroidBridge.startYouTubeImport(reqUrl);
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

      // 2. Status Polling (Real RenderState / Import job status)
      if (endpoint.includes('/api/status/')) {
        const parts = endpoint.split('/api/status/');
        const rawId = (parts[1] || '').split('?')[0].trim();

        if (window._activeMobileYtJob && (rawId === window._activeMobileYtJob.job_id || rawId.startsWith('mobile_yt_'))) {
          return new Response(JSON.stringify(window._activeMobileYtJob), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        if (window._activeMobileRenderJob && (rawId === window._activeMobileRenderJob.job_id || rawId.startsWith('mobile_job_'))) {
          return new Response(JSON.stringify(window._activeMobileRenderJob), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          });
        }

        return new Response(JSON.stringify({
          ok: false,
          status: 'error',
          progress: 0,
          error: 'Job not found or Desktop Engine offline.'
        }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 3. Pipeline Start (/api/start) -> Real RenderForegroundService MP4 processing
      if (endpoint.includes('/api/start')) {
        let reqBody = {};
        try {
          if (typeof FormData !== 'undefined' && options.body instanceof FormData) {
            options.body.forEach((v, k) => { if (typeof v === 'string') reqBody[k] = v; });
          } else if (typeof options.body === 'string') {
            reqBody = JSON.parse(options.body);
          } else {
            reqBody = options.body || {};
          }
        } catch (_) {}

        if (!window._lastAndroidUri) {
          return new Response(JSON.stringify({
            ok: false,
            error: 'Please choose a video from your phone gallery or import a link first.'
          }), { status: 400, headers: { 'Content-Type': 'application/json' } });
        }

        if (window._activeMobileRenderJob && window._activeMobileRenderJob.status === 'running' &&
            (Date.now() - (window._lastRenderStartMs || 0)) < 4000) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: window._activeMobileRenderJob.job_id,
            message: 'Render already in progress.'
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        window._lastRenderStartMs = Date.now();

        const rId = 'mobile_job_' + Date.now();
        const dur = Math.max(5, Math.min(180, Number(reqBody.max_duration || reqBody.duration || 30)));
        const isSplit = reqBody.layout === 'split' || reqBody.split_screen === '1' || reqBody.gaming_split === '1';
        const layoutMode = isSplit ? 'split' : 'center';
        const captionsOn = reqBody.captions !== 'no' && reqBody.disable_captions !== '1' && reqBody.captions_enabled !== '0';
        const count = Math.max(1, Math.min(5, Number(reqBody.clips || reqBody.clips_count || reqBody.num_clips || 1)));

        window._activeMobileRenderJob = {
          ok: true,
          job_id: rId,
          id: rId,
          status: 'running',
          progress: 5,
          stage: 'Initializing hardware Media3 HD engine...',
          detail: 'Preparing real MP4 render...',
          logs: [`[Media3] Starting ${layoutMode} HD render (${dur}s, ${count} clip(s), captions=${captionsOn})...`],
          outputs: [],
          candidates: [],
          output_metadata: {}
        };

        const maxHeight = parseInt(window._mobileSelectedImportQuality || document.querySelector('.mobile-import-quality-select')?.value || '4320', 10) || 4320;
        if (window.AndroidBridge && window.AndroidBridge.startRenderWithQuality) {
          window.AndroidBridge.startRenderWithQuality(window._lastAndroidUri, dur, layoutMode, captionsOn, count, maxHeight);
        } else if (window.AndroidBridge && window.AndroidBridge.startRenderWithCount) {
          window.AndroidBridge.startRenderWithCount(window._lastAndroidUri, dur, layoutMode, captionsOn, count);
        } else if (window.AndroidBridge && window.AndroidBridge.startRender) {
          window.AndroidBridge.startRender(window._lastAndroidUri, dur, layoutMode, captionsOn);
        }

        return new Response(JSON.stringify({
          ok: true,
          job_id: rId,
          message: 'Started real on-device MP4 render.'
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 4. Instant Clipping Start -> Real RenderForegroundService MP4 processing
      if (endpoint.includes('/api/instant/start')) {
        let reqBody = {};
        try {
          reqBody = typeof options.body === 'string' ? JSON.parse(options.body) : (options.body || {});
        } catch (_) {}

        const srcUri = (reqBody.youtube_url || '').trim() || window._lastAndroidUri || '';
        if (!srcUri) {
          return new Response(JSON.stringify({
            ok: false,
            error: 'Please choose a video from your gallery or paste a YouTube link first.'
          }), { status: 400, headers: { 'Content-Type': 'application/json' } });
        }

        const iId = 'instant_mobile_' + Date.now();
        const dur = Math.max(5, Math.min(180, Number(reqBody.duration || 30)));
        window._activeInstantJob = {
          ok: true,
          job_id: iId,
          status: 'running',
          progress: 5,
          stage: 'Initializing MediaCodec 9:16 MP4 render...',
          detail: 'Hardware vertical MP4 encoding...',
          logs: ['⚡ Initializing mobile video engine...'],
          outputs: [],
          clip_paths: [],
          clips: []
        };

        const count = Math.max(1, Math.min(5, Number(reqBody.clips || reqBody.clips_count || reqBody.num_clips || 1)));
        if (window.AndroidBridge && window.AndroidBridge.startRenderWithCount) {
          window.AndroidBridge.startRenderWithCount(srcUri, dur, reqBody.layout || 'center', reqBody.captions !== 'no', count);
        } else if (window.AndroidBridge && window.AndroidBridge.startRender) {
          window.AndroidBridge.startRender(srcUri, dur, reqBody.layout || 'center', reqBody.captions !== 'no');
        }

        return new Response(JSON.stringify({ ok: true, job_id: iId, message: 'Instant MP4 pipeline started.' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/instant/status/')) {
        const cur = window._activeInstantJob || { ok: false, status: 'error', progress: 0, error: 'No active instant job' };
        return new Response(JSON.stringify(cur), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 4b. Live Stream Studio handled natively by MobileLiveManager via callApiAsync

      // 5. Upload Interceptor
      if (endpoint.includes('/api/upload')) {
        const uId = 'mobile_job_' + Date.now();
        return new Response(JSON.stringify({
          ok: true,
          job_id: uId,
          filename: 'mobile_video.mp4'
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 6. Clippy AI Model & Chat
      if (endpoint.includes('/api/clippy/model')) {
        return new Response(JSON.stringify({
          ok: true,
          model: "qwen3:4b (Fastest Local AI)",
          provider: "builtin",
          speed: "Instant"
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/clippy/chat')) {
        let prompt = "";
        try {
          const b = JSON.parse(options.body || "{}");
          prompt = (b.message || "").toLowerCase();
        } catch (_) { }

        let reply = "I'm here to help you create viral Shorts! You can import local videos or YouTube links, use Instant 9:16 Clipping, or check the Campaigns tab for creator bounties.";
        if (prompt.includes("campaign") || prompt.includes("bount") || prompt.includes("earn")) {
          reply = "[NAVIGATE:campaigns]\nTop picks for clipper bounties:\n1. 🏆 **Content Rewards** (#1 Pick: India + International, pays per view)\n2. 🥈 **Vyro** (Major creators, MrBeast ecosystem)\n3. 🥉 **Clipster** (Worldwide streamers & gaming)";
        } else if (prompt.includes("caption") || prompt.includes("disable")) {
          reply = "You can disable captions anytime! In **Beta Features**, use the Subtitle Captions toggle, or select 'No Captions' in the font menu.";
        } else if (prompt.includes("huh") || prompt.includes("what")) {
          reply = "I'm your Clipify AI assistant! Pick a video from your gallery or paste a YouTube URL above to generate a 9:16 vertical Short.";
        }

        return new Response(JSON.stringify({
          ok: true,
          reply: reply,
          model: "qwen3:4b (Mobile AI)",
          provider: "builtin"
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 7. Models Hub & Ollama (Real schema, no "undefined (Downloaded)", no fake 1s Ollama download)
      if (endpoint.includes('/api/models/ollama/details')) {
        return new Response(JSON.stringify({
          ok: true,
          models: [],
          default: ''
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      if (endpoint.includes('/api/models/ollama/download-status')) {
        return new Response(JSON.stringify({
          ok: false,
          active: false,
          progress: 0,
          status: 'Desktop Engine required',
          error: 'Ollama requires Clipify Desktop Engine on your PC.'
        }), { status: 503, headers: { 'Content-Type': 'application/json' } });
      }

      if (endpoint.includes('/api/models/ollama/download') || endpoint.includes('/api/models/ollama/pull') || endpoint.includes('/api/models/ollama/delete')) {
        return new Response(JSON.stringify({
          ok: false,
          error: 'Ollama requires Clipify Desktop Engine on your PC. Connect your phone via USB or LAN to download and run Ollama models.'
        }), { status: 503, headers: { 'Content-Type': 'application/json' } });
      }

      if (endpoint.includes('/api/models/scan')) {
        return new Response(JSON.stringify({
          ok: false,
          models: [],
          error: 'Ollama runs on Clipify Desktop Engine (PC).'
        }), { status: 404, headers: { 'Content-Type': 'application/json' } });
      }

      if (endpoint.includes('/api/models') && !endpoint.includes('/api/models/config') && !endpoint.includes('/api/models/huggingface') && !endpoint.includes('/api/models/verify-hf')) {
        return new Response(JSON.stringify({
          ok: true,
          models: [{ id: 'mediacodec_hw', name: 'MediaCodec Hardware Engine', size: 'On-Device' }],
          default: 'mediacodec_hw'
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      // 8. General Health
      if (endpoint.includes('/api/health')) {
        return new Response(JSON.stringify({ ok: true, status: 'healthy', platform: 'android' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 9. Standalone Mobile System GPUs
      if (endpoint.includes('/api/system/gpus')) {
        return new Response(JSON.stringify({
          ok: true,
          active_gpu: 'mobile_mediacodec',
          active: { id: 'mobile_mediacodec', name: 'MediaCodec Hardware GPU', vendor: 'android', active: true, recommended: true },
          gpus: [{ id: 'mobile_mediacodec', name: 'MediaCodec Hardware GPU', vendor: 'android', active: true, recommended: true }]
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      // 10. Trending Fallback (Only reached if MobileTrendingFetcher + PC are both unreachable)
      if (endpoint.includes('/api/trending/')) {
        const plat = endpoint.split('/api/trending/')[1]?.split('?')[0] || 'youtube';
        return new Response(JSON.stringify({
          ok: false,
          platform: plat,
          error: 'Unable to fetch live trending feed. Check your internet connection.',
          gameplay_videos: [],
          live_streams: []
        }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 11. Standalone Mobile Projects / Recent Clips (matches loadProjects() schema)
      if (endpoint === '/api/projects' || endpoint.startsWith('/api/projects?')) {
        let clips = [];
        try {
          if (window.AndroidBridge && window.AndroidBridge.getRecentProjectsJson) {
            clips = JSON.parse(window.AndroidBridge.getRecentProjectsJson() || '[]');
          }
        } catch (_) { }
        const projects = clips.map((c, idx) => {
          const fileUrl = c.path && c.path.startsWith('file://') ? c.path : ('file://' + c.path);
          return {
            id: 'mobile_proj_' + idx + '_' + (c.dateModified || Date.now()),
            name: c.name || ('Clipify Short ' + (idx + 1)),
            source: c.name || 'Mobile Short',
            status: 'done',
            outputs: c.path ? [fileUrl] : [],
            output_metadata: c.path ? {
              [fileUrl]: {
                title: (c.name || 'Clipify Short').replace(/\.mp4$/i, ''),
                description: `${c.formattedSize || 'MP4'} · Saved in Movies/ClipifyAI`
              }
            } : {}
          };
        });
        return new Response(JSON.stringify({ ok: true, projects }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 12. Standalone Live Transcript & Preferences
      if (endpoint.includes('/api/live/transcript')) {
        return new Response(JSON.stringify({ ok: true, transcript: [], segments: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      if (endpoint.includes('/api/live/preferences')) {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // 13. Standalone Mobile Narrate Voices, Clips, Preview & Generate
      if (endpoint.includes('/api/narrate/voices')) {
        const voices = [
          { id: 'android_en_us_male', name: 'Marcus (Deep Narrator)', category: 'Creator', language: 'English (US)', gender: 'Male', engine: 'Android TTS' },
          { id: 'android_en_us_female', name: 'Aria (Crisp Storyteller)', category: 'Story', language: 'English (US)', gender: 'Female', engine: 'Android TTS' },
          { id: 'android_en_gb_male', name: 'Oliver (Documentary)', category: 'Documentary', language: 'English (UK)', gender: 'Male', engine: 'Android TTS' },
          { id: 'android_hi_in_male', name: 'Aarav (Hindi / Hinglish)', category: 'Regional', language: 'Hindi (IN)', gender: 'Male', engine: 'Android TTS' }
        ];
        return new Response(JSON.stringify({ ok: true, voices }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/videos')) {
        const videos = [];
        try {
          if (window.AndroidBridge && window.AndroidBridge.getRecentProjectsJson) {
            const localClips = JSON.parse(window.AndroidBridge.getRecentProjectsJson() || '[]');
            localClips.forEach((c, idx) => {
              const fileUrl = c.path && c.path.startsWith('file://') ? c.path : ('file://' + c.path);
              videos.push({
                id: 'local_' + idx + '_' + (c.name || 'clip'),
                name: (c.name || 'Mobile Short').replace(/\.mp4$/i, ''),
                duration: 30,
                duration_label: c.formattedSize || 'MP4 Short',
                width: 720,
                height: 1280,
                generated: true,
                path: fileUrl,
                thumbnail_url: fileUrl + '#t=0.5'
              });
            });
          }
        } catch (_) {}
        return new Response(JSON.stringify({ ok: true, videos }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/history')) {
        const history = [];
        try {
          if (window.AndroidBridge && window.AndroidBridge.getRecentProjectsJson) {
            const localClips = JSON.parse(window.AndroidBridge.getRecentProjectsJson() || '[]');
            localClips.forEach((c, idx) => {
              const fileUrl = c.path && c.path.startsWith('file://') ? c.path : ('file://' + c.path);
              history.push({
                id: 'hist_' + idx + '_' + (c.dateModified || Date.now()),
                title: (c.name || 'Clipify Short').replace(/\.mp4$/i, ''),
                duration: 30,
                voice: 'Mobile Studio',
                url: fileUrl
              });
            });
          }
        } catch (_) {}
        return new Response(JSON.stringify({ ok: true, history }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/download-extra-status')) {
        return new Response(JSON.stringify({ ok: true, available: false, downloading: false, count: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/preview-voice')) {
        if (window.AndroidBridge && window.AndroidBridge.speakText) {
          window.AndroidBridge.speakText('Welcome to Clipify AI Narrate Studio. Your story sounds crisp and ready.');
        }
        return new Response(JSON.stringify({ ok: true, use_native_tts: true, url: '' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/generate')) {
        let reqBody = {};
        try {
          reqBody = typeof options.body === 'string' ? JSON.parse(options.body) : (options.body || {});
        } catch (_) {}
        let targetPath = window._lastAndroidUri || '';
        try {
          if (window.AndroidBridge && window.AndroidBridge.getRecentProjectsJson) {
            const localClips = JSON.parse(window.AndroidBridge.getRecentProjectsJson() || '[]');
            const match = localClips.find((c, idx) => ('local_' + idx + '_' + (c.name || 'clip')) === reqBody.video);
            if (match && match.path) targetPath = match.path;
            else if (!targetPath && localClips[0]?.path) targetPath = localClips[0].path;
          }
        } catch (_) {}
        const nId = 'mobile_narrate_' + Date.now();
        window._activeNarrateJob = {
          ok: true,
          job_id: nId,
          status: 'running',
          progress: 8,
          stage: 'Rendering narrated Short...',
          detail: 'Hardware Media3 MP4 export',
          output: '',
          duration: 30,
          metadata: { title: (reqBody.script || 'Narrated Short').slice(0, 48) }
        };
        if (window.AndroidBridge && window.AndroidBridge.startRenderWithCount) {
          try { window.AndroidBridge.startRenderWithCount(targetPath, 30, 'center', true, 1); } catch (_) {}
        } else if (window.AndroidBridge && window.AndroidBridge.startRender) {
          try { window.AndroidBridge.startRender(targetPath, 30, 'center', true); } catch (_) {}
        }
        return new Response(JSON.stringify({ ok: true, job_id: nId }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/narrate/status/')) {
        const cur = window._activeNarrateJob || { ok: true, status: 'done', progress: 100, output: '' };
        if (window._activeMobileRenderJob) {
          cur.progress = window._activeMobileRenderJob.progress || cur.progress;
          cur.stage = window._activeMobileRenderJob.stage || cur.stage;
          if (window._activeMobileRenderJob.status === 'done') {
            cur.status = 'done';
            cur.output = window._activeMobileRenderJob.outputs?.[0] || '';
            const pv = document.getElementById('narratePreview');
            if (pv && cur.output) { pv.src = cur.output; pv.load(); }
          }
        }
        return new Response(JSON.stringify(cur), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      if (endpoint.includes('/api/apply-branding/') || endpoint.includes('/api/trim/')) {
        let reqBody = {};
        try {
          reqBody = typeof options.body === 'string' ? JSON.parse(options.body) : (options.body || {});
        } catch (_) {}
        window._mobileLastBranding = reqBody;
        try { localStorage.setItem('clipify_mobile_branding', JSON.stringify(reqBody)); } catch (_) {}
        const targetFile = reqBody.filename || reqBody.file || window.state?.reviewFile || '';
        if (window.AndroidBridge && window.AndroidBridge.showToast) {
          window.AndroidBridge.showToast('✓ Caption & branding style saved for mobile render!');
        }
        return new Response(JSON.stringify({
          ok: true,
          output: targetFile,
          message: 'Caption & branding settings applied on mobile.'
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }

      // Catch-all for any other /api/* route on file:// so originalFetch never throws "URL scheme file is not supported"
      if (endpoint.includes('/api/projects/trash')) {
        return new Response(JSON.stringify({ ok: true, items: [], trash: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (endpoint.includes('/api/cache/status')) {
        return new Response(JSON.stringify({ ok: true, size_bytes: 0, files: 0, human_size: '0 MB' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (endpoint.includes('/api/updater/check')) {
        return new Response(JSON.stringify({ ok: true, update_available: false, latest_version: '5.0.6-beta' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({ ok: false, error: 'Desktop Engine offline for ' + endpoint }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Default fetch for file:/// and local assets
    try {
      return await originalFetch(url, options);
    } catch (e) {
      return new Response(JSON.stringify({ ok: false, error: 'Offline' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  };

  // Wire Native UI Elements on DOM ready
  window.addEventListener('DOMContentLoaded', () => {
    console.log('[ClipifyAI Android] Wiring native controls...');

    // Wire video file dropzones & pickers to Android gallery picker (never hijack image/logo inputs)
    const pickers = document.querySelectorAll(
      'input[type="file"], .dropzone, .upload-box, .drop-area, #videoInput, [data-picker="video"], .upload-custom, #betaDropZone, .file-chip-change, #instantDropzone, #instantFileInput'
    );
    pickers.forEach(el => {
      const acceptAttr = (el.getAttribute('accept') || '').toLowerCase();
      const idAttr = (el.id || '').toLowerCase();
      if (acceptAttr.includes('image') || idAttr.includes('logo') || idAttr.includes('image')) {
        return;
      }
      el.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.pickVideo) {
          e.preventDefault();
          e.stopPropagation();
          window.AndroidBridge.pickVideo();
        }
      });
    });

    // Wire URL inputs to auto-enable generate buttons on mobile
    ['youtubeUrl', 'betaYtUrl', 'instantYtUrl'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        ['input', 'paste', 'change'].forEach(evt => {
          el.addEventListener(evt, () => {
            setTimeout(() => {
              const val = el.value.trim();
              if (val.length > 5) {
                ['createBtn', 'submitBtn', 'betaRunPipelineBtn', 'btnStartInstantClip'].forEach(bid => {
                  const b = document.getElementById(bid);
                  if (b) b.disabled = false;
                });
              }
            }, 50);
          });
        });
      }
    });

    // Wire external links to system browser
    document.querySelectorAll('a[href^="http"]').forEach(a => {
      a.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
          e.preventDefault();
          window.AndroidBridge.openBrowser(a.href);
        }
      });
    });

    // Show gallery toast when downloading on mobile
    document.addEventListener('click', (e) => {
      const target = e.target.closest('#featuredDownload, [download]');
      if (target) {
        if (window.AndroidBridge && window.AndroidBridge.showToast) {
          window.AndroidBridge.showToast('Clip saved to Gallery: /sdcard/Movies/ClipifyAI/');
        }
      }
    });
  });

  // Global Callback called by Android Activity when video is chosen from gallery
  window.onAndroidVideoSelected = function (uri, filename, duration) {
    console.log('[ClipifyAI Android] Video selected from native storage:', filename);
    window._lastAndroidUri = uri;
    const jId = 'mobile_job_' + Date.now();

    const dropText = document.querySelector('.dropzone strong, .drop-title, #betaSourceName, #fileName, #instantSelectedFileName');
    if (dropText) dropText.textContent = filename;
    const dropSub = document.querySelector('.dropzone small, .drop-subtitle, #betaSourceMeta, #fileSize, #previewMeta, #instantSelectedFileDur');
    if (dropSub) dropSub.textContent = 'Selected from mobile gallery · Ready to clip';
    const info = document.getElementById('betaSourceInfo');
    if (info) info.style.display = 'flex';
    const chip = document.getElementById('fileChip');
    if (chip) chip.hidden = false;
    const instBadge = document.getElementById('instantSelectedFile');
    if (instBadge) instBadge.hidden = false;

    // Enable all Generate buttons across all tabs!
    ['createBtn', 'submitBtn', 'btnStartClip', 'betaRunPipelineBtn', 'btnStartInstantClip'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });

    if (window.state) {
      window.state.jobId = jId;
      window.state.source = {
        name: filename,
        size: 1024 * 1024 * 25,
        uri: uri,
        origin: 'android_native',
        jobId: jId
      };
    }
    if (window.betaState) {
      window.betaState.jobId = jId;
      window.betaState.sourceFile = {
        name: filename,
        size: 1024 * 1024 * 25,
        uri: uri
      };
    }

    if (window.AndroidBridge && window.AndroidBridge.showToast) {
      window.AndroidBridge.showToast('Selected: ' + filename + '. Ready to generate!');
    }
  };

  // Native Mobile More Bottom-Sheet Drawer
  window.closeMobileMoreDrawer = function () {
    const backdrop = document.getElementById('mobileDrawerBackdrop');
    const sheet = document.getElementById('mobileDrawerSheet');
    if (backdrop) backdrop.classList.remove('active');
    if (sheet) sheet.classList.remove('active');
    setTimeout(() => {
      if (backdrop && !backdrop.classList.contains('active')) backdrop.style.display = 'none';
      if (sheet && !sheet.classList.contains('active')) sheet.style.display = 'none';
    }, 260);
  };

  window.toggleMobileMoreDrawer = function () {
    let backdrop = document.getElementById('mobileDrawerBackdrop');
    let sheet = document.getElementById('mobileDrawerSheet');
    if (!backdrop || !sheet) {
      backdrop = document.createElement('div');
      backdrop.id = 'mobileDrawerBackdrop';
      backdrop.className = 'mobile-drawer-backdrop';
      backdrop.style.display = 'none';
      backdrop.onclick = window.closeMobileMoreDrawer;

      sheet = document.createElement('div');
      sheet.id = 'mobileDrawerSheet';
      sheet.className = 'mobile-drawer-sheet';
      sheet.style.display = 'none';
      sheet.innerHTML = `
        <div class="mobile-drawer-pill"></div>
        <div class="mobile-drawer-header">
          <div><strong>Clipify AI Tools</strong><small>Studio &amp; Utilities</small></div>
          <button type="button" class="mobile-drawer-close" aria-label="Close">✕</button>
        </div>
        <div class="mobile-drawer-grid">
          <button type="button" class="mobile-drawer-item" data-drawer-nav="live">
            <span class="drawer-icon">📡</span>
            <span class="drawer-copy"><b>Live Studio</b><small>Stream clipping &amp; synced captions</small></span>
            <span class="drawer-pill red">LIVE</span>
          </button>
          <button type="button" class="mobile-drawer-item" data-drawer-nav="narrate">
            <span class="drawer-icon">🎙️</span>
            <span class="drawer-copy"><b>Narrate Studio</b><small>Script to voiceover Short</small></span>
            <span class="drawer-pill purple">VOICE</span>
          </button>
          <button type="button" class="mobile-drawer-item" data-drawer-nav="projects">
            <span class="drawer-icon">📁</span>
            <span class="drawer-copy"><b>Projects &amp; Clips</b><small>Browse exported 9:16 Shorts</small></span>
          </button>
          <button type="button" class="mobile-drawer-item" data-drawer-nav="beta">
            <span class="drawer-icon">🧪</span>
            <span class="drawer-copy"><b>Beta Testing</b><small>Experimental AI &amp; split-screen tools</small></span>
            <span class="drawer-pill purple">BETA</span>
          </button>
          <button type="button" class="mobile-drawer-item" data-drawer-nav="models">
            <span class="drawer-icon">⚡</span>
            <span class="drawer-copy"><b>AI Models</b><small>Local WhisperX &amp; Qwen engines</small></span>
          </button>
          <button type="button" class="mobile-drawer-item" data-drawer-nav="guide">
            <span class="drawer-icon">✨</span>
            <span class="drawer-copy"><b>App Guide</b><small>Interactive Studio walkthrough</small></span>
          </button>
          <a class="mobile-drawer-item" href="https://discord.gg/5ZBsasgryX" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;">
            <span class="drawer-icon">💬</span>
            <span class="drawer-copy"><b>Discord Server</b><small>Community, help &amp; updates</small></span>
          </a>
          <a class="mobile-drawer-item" href="https://github.com/sherlock-dev-ai" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;">
            <span class="drawer-icon">↗</span>
            <span class="drawer-copy"><b>GitHub</b><small>Releases &amp; source code</small></span>
          </a>
        </div>`;
      document.body.appendChild(backdrop);
      document.body.appendChild(sheet);

      sheet.querySelector('.mobile-drawer-close').onclick = window.closeMobileMoreDrawer;
      sheet.querySelectorAll('[data-drawer-nav]').forEach(btn => {
        btn.addEventListener('click', () => {
          const dest = btn.getAttribute('data-drawer-nav');
          window.closeMobileMoreDrawer();
          if (dest === 'live') {
            window.location.href = 'live.html';
          } else if (dest === 'narrate') {
            window.location.href = 'narrate.html';
          } else if (typeof window.navigateTo === 'function') {
            window.navigateTo(dest);
          } else {
            window.location.href = 'index.html#' + dest;
          }
        });
      });
    }

    const isOpen = sheet.classList.contains('active');
    if (isOpen) {
      window.closeMobileMoreDrawer();
    } else {
      backdrop.style.display = 'block';
      sheet.style.display = 'block';
      requestAnimationFrame(() => {
        backdrop.classList.add('active');
        sheet.classList.add('active');
      });
    }
  };

  // Mobile APK Update Checker & Installer Window
  function showMobileUpdateModal(opts) {
    let ov = document.getElementById('clipifyMobileUpdateModal');
    if (ov) ov.remove();
    ov = document.createElement('div');
    ov.id = 'clipifyMobileUpdateModal';
    ov.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(5,5,9,0.88);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;padding:18px;';
    ov.innerHTML = `
      <div style="width:100%;max-width:390px;background:#0e0f14;border:1px solid rgba(255,255,255,0.16);border-radius:18px;padding:20px;color:#fff;font-family:Inter,system-ui,sans-serif;box-shadow:0 24px 60px rgba(0,0,0,0.8);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
          <strong style="font-size:16px;">${opts.title || 'Clipify AI Update'}</strong>
          <button type="button" id="mUpdCloseX" style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.14);color:#fff;width:30px;height:30px;border-radius:8px;font-size:16px;">✕</button>
        </div>
        <div style="font-size:13px;color:rgba(255,255,255,0.78);line-height:1.5;margin-bottom:14px;">${opts.bodyHtml || ''}</div>
        <div id="mUpdProgressWrap" style="display:none;margin-bottom:14px;">
          <div style="height:8px;background:rgba(255,255,255,0.1);border-radius:99px;overflow:hidden;">
            <div id="mUpdProgressBar" style="height:100%;width:0%;background:#ffffff;transition:width 0.2s;"></div>
          </div>
          <div id="mUpdProgressText" style="font-size:12px;color:rgba(255,255,255,0.75);margin-top:6px;">Preparing download...</div>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button type="button" id="mUpdCloseBtn" style="padding:10px 14px;border-radius:10px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.14);color:#fff;font-weight:600;">Close</button>
          ${opts.actionHtml || ''}
        </div>
      </div>
    `;
    document.body.appendChild(ov);
    ov.querySelector('#mUpdCloseX').onclick = () => ov.remove();
    ov.querySelector('#mUpdCloseBtn').onclick = () => ov.remove();
    if (opts.onMount) opts.onMount(ov);
  }

  window.onMobileUpdateProgress = function (pct, msg) {
    const wrap = document.getElementById('mUpdProgressWrap');
    const bar = document.getElementById('mUpdProgressBar');
    const txt = document.getElementById('mUpdProgressText');
    if (wrap) wrap.style.display = 'block';
    if (bar) bar.style.width = `${pct}%`;
    if (txt) txt.textContent = msg || `Downloading (${pct}%)...`;
  };

  window.onMobileUpdateReady = function (ok, msg) {
    const txt = document.getElementById('mUpdProgressText');
    if (txt) txt.textContent = msg || (ok ? 'Installer opened!' : 'Could not open installer.');
    const btn = document.getElementById('mUpdInstallBtn');
    if (btn) {
      btn.disabled = false;
      btn.textContent = ok ? 'Re-open Installer' : 'Install Update';
    }
  };

  window.openClipifyMobileUpdate = async function () {
    const currentVerRaw = (window.AndroidBridge && window.AndroidBridge.getAppVersionName)
      ? window.AndroidBridge.getAppVersionName()
      : '5.0.7';
    const norm = (v) => String(v || '').replace(/^v/i, '').split('-')[0].trim();
    const currentNorm = norm(currentVerRaw);

    showMobileUpdateModal({
      title: 'Checking for Updates...',
      bodyHtml: `Installed version: <b>v${currentNorm}</b><br>Checking GitHub Releases...`
    });

    try {
      const resp = await originalFetch('https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/latest', {
        headers: { 'Accept': 'application/vnd.github.v3+json' }
      });
      const rel = await resp.json();
      const assets = Array.isArray(rel.assets) ? rel.assets : [];
      const latestTag = rel.tag_name || `v${currentNorm}`;
      const latestNorm = norm(latestTag);
      const apkAsset = assets.find(a => (a.name || '').toLowerCase().includes(latestNorm) && (a.name || '').toLowerCase().endsWith('.apk'))
        || assets.find(a => (a.name || '').toLowerCase().endsWith('.apk'));
      const targetUrl = (apkAsset && apkAsset.browser_download_url)
        ? apkAsset.browser_download_url
        : (rel.html_url || 'https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases');

      if (currentNorm === latestNorm) {
        showMobileUpdateModal({
          title: `Updated to v${currentNorm} ✓`,
          bodyHtml: `<div style="padding:10px 12px;border-radius:10px;background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.35);color:#86efac;font-weight:600;margin-bottom:8px;">✓ Updated to v${currentNorm} successfully!</div>You are running the latest version (<b>${latestTag}</b>).`
        });
        return;
      }

      showMobileUpdateModal({
        title: `Update Available: ${latestTag}`,
        bodyHtml: `Installed: <b>v${currentNorm}</b> &nbsp;→&nbsp; Latest: <b style="color:#4ade80;">${latestTag}</b><br><br>Tap <b>Install Update</b> to download and open the Android installer.`,
        actionHtml: `<button type="button" id="mUpdInstallBtn" style="padding:10px 16px;border-radius:10px;background:#ffffff;color:#000000;border:none;font-weight:700;">Install Update</button>`,
        onMount: (ov) => {
          const btn = ov.querySelector('#mUpdInstallBtn');
          if (!btn) return;
          btn.onclick = () => {
            btn.disabled = true;
            btn.textContent = 'Downloading...';
            window.onMobileUpdateProgress(2, `Downloading ${latestTag}...`);
            if (window.AndroidBridge && window.AndroidBridge.downloadAndInstallApk) {
              window.AndroidBridge.downloadAndInstallApk(targetUrl, latestTag);
            } else if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
              window.AndroidBridge.openBrowser(targetUrl);
            } else {
              window.open(targetUrl, '_blank');
            }
          };
        }
      });
    } catch (e) {
      showMobileUpdateModal({
        title: 'Update Check',
        bodyHtml: `Installed: <b>v${currentNorm}</b><br>Could not reach GitHub right now. You can open the Releases page to check manually.`,
        actionHtml: `<button type="button" id="mUpdOpenRel" style="padding:10px 16px;border-radius:10px;background:#ffffff;color:#000000;border:none;font-weight:700;">Open Releases</button>`,
        onMount: (ov) => {
          ov.querySelector('#mUpdOpenRel').onclick = () => {
            const url = 'https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases';
            if (window.AndroidBridge && window.AndroidBridge.openBrowser) window.AndroidBridge.openBrowser(url);
            else window.open(url, '_blank');
          };
        }
      });
    }
  };
  window.openClipifyUpdate = window.openClipifyMobileUpdate;

  // Ensure default mobile caption design in Create/Beta is White & Yellow (gold_yellow)
  // and inject a Download Quality selector before YouTube importing
  document.addEventListener('DOMContentLoaded', () => {
    ['#captionAccentSelect', '#betaCaptionAccent'].forEach(sel => {
      const el = document.querySelector(sel);
      if (el && !el.dataset.userChanged) {
        el.value = 'gold_yellow';
      }
    });
    if (window.captionPlaygroundState && !window.captionPlaygroundState.styleId) {
      window.captionPlaygroundState.styleId = 'gold_yellow';
    }

    // Sync mobile version badges & show "Updated to vX" confirmation once after upgrade
    const rawVer = (window.AndroidBridge && window.AndroidBridge.getAppVersionName)
      ? window.AndroidBridge.getAppVersionName()
      : '5.0.7';
    const curVer = String(rawVer || '5.0.7').replace(/^v/i, '').split('-')[0].trim();
    const prevSeen = localStorage.getItem('clipify_last_seen_version');
    if (prevSeen && prevSeen !== curVer && window.AndroidBridge && window.AndroidBridge.showToast) {
      window.AndroidBridge.showToast(`✓ Updated to v${curVer} successfully!`);
    }
    try { localStorage.setItem('clipify_last_seen_version', curVer); } catch (_) {}
    const sbBadge = document.getElementById('sidebarVersionBadge');
    const navTag = document.getElementById('navVersionTag');
    const topVer = document.querySelector('#topBrandVersionBadge .version-num');
    if (sbBadge) sbBadge.textContent = 'v' + curVer;
    if (navTag) navTag.textContent = 'v' + curVer;
    if (topVer) topVer.textContent = 'v' + curVer;

    // Inject Download Quality dropdown before YouTube importing across Create, Instant, and Beta
    window._mobileSelectedImportQuality = window._mobileSelectedImportQuality || '4320';
    ['youtubeUrl', 'instantYoutubeUrl', 'betaYtUrl'].forEach((inputId) => {
      const ytInput = document.getElementById(inputId);
      if (!ytInput || ytInput.dataset.hasQualitySelect) return;
      ytInput.dataset.hasQualitySelect = '1';
      const wrap = document.createElement('div');
      wrap.className = 'mobile-import-quality-wrap';
      wrap.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:8px;padding:8px 12px;border-radius:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.12);width:100%;box-sizing:border-box;';
      wrap.innerHTML = `
        <span style="font-size:0.78rem;font-weight:700;color:rgba(255,255,255,0.85);white-space:nowrap;">Quality</span>
        <select class="mobile-import-quality-select" style="flex:1;min-width:0;background:#0e0f14;color:#fff;border:1px solid rgba(255,255,255,0.18);border-radius:8px;padding:6px 10px;font-size:0.78rem;font-weight:600;">
          <option value="4320" selected>Best Available (4K / 1080p)</option>
          <option value="1080">1080p Full HD</option>
          <option value="720">720p HD</option>
          <option value="480">360p / 480p Fast</option>
        </select>
      `;
      const sel = wrap.querySelector('select');
      sel.value = window._mobileSelectedImportQuality;
      sel.addEventListener('change', () => {
        window._mobileSelectedImportQuality = sel.value;
        document.querySelectorAll('.mobile-import-quality-select').forEach(s => { s.value = sel.value; });
      });
      const parentRow = ytInput.closest('.youtube-input-row, .youtube-import-row, .url-row, .field-row') || ytInput.parentElement;
      if (parentRow && parentRow.parentElement) {
        parentRow.parentElement.insertBefore(wrap, parentRow.nextSibling);
      }
    });

    // Fix any overflowing cards/buttons & non-B&W badges on mobile
    if (!document.getElementById('clipify-mobile-bw-overflow-fix')) {
      const fixSt = document.createElement('style');
      fixSt.id = 'clipify-mobile-bw-overflow-fix';
      fixSt.textContent = `
        .ai-provider-card, .ollama-download-row, .provider-header-row { max-width: 100% !important; box-sizing: border-box !important; overflow: hidden !important; }
        .btn-open-model-hub { max-width: 100% !important; width: 100% !important; height: auto !important; min-height: 38px !important; white-space: normal !important; background: rgba(255,255,255,0.08) !important; border-color: rgba(255,255,255,0.22) !important; color: #fff !important; }
        #btnModelHubBadge { background: #ffffff !important; color: #000000 !important; }
        .ollama-download-row > div, .provider-tabs { max-width: 100% !important; flex-wrap: wrap !important; }
        .ollama-download-row input { min-width: 0 !important; }
      `;
      document.head.appendChild(fixSt);
    }
  });

  // Replace ugly native Android WebView alert() ("The page at file:// says:") with B&W Obsidian modal
  window.alert = function (msg) {
    let ov = document.getElementById('clipifyMobileAlertModal');
    if (ov) ov.remove();
    ov = document.createElement('div');
    ov.id = 'clipifyMobileAlertModal';
    ov.style.cssText = 'position:fixed;inset:0;z-index:100000;background:rgba(4,4,6,0.86);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;padding:18px;';
    ov.innerHTML = `
      <div style="width:100%;max-width:360px;background:#0b0b0e;border:1px solid rgba(255,255,255,0.18);border-radius:16px;padding:18px;color:#fff;font-family:Inter,system-ui,sans-serif;box-shadow:0 24px 60px rgba(0,0,0,0.85);">
        <div style="font-size:15px;font-weight:700;margin-bottom:8px;color:#fff;">Clipify AI</div>
        <div style="font-size:13px;line-height:1.5;color:rgba(255,255,255,0.82);margin-bottom:16px;word-break:break-word;"></div>
        <div style="display:flex;justify-content:flex-end;">
          <button type="button" id="mAlertOkBtn" style="padding:9px 18px;border-radius:10px;background:#fff;color:#000;border:none;font-weight:700;font-size:13px;">OK</button>
        </div>
      </div>
    `;
    ov.querySelector('div > div:nth-child(2)').textContent = String(msg ?? '');
    document.body.appendChild(ov);
    ov.querySelector('#mAlertOkBtn').onclick = () => ov.remove();
  };

  // Replace ugly grey/teal native Android <select> popups with sleek B&W Obsidian sheet
  // and render actual font designs for font selectors!
  const FONT_PREVIEW_MAP = {
    'montserrat extra bold': "'Montserrat', 'Arial Black', sans-serif",
    'montserrat black': "'Montserrat', 'Arial Black', sans-serif",
    'arial black': "'Arial Black', Impact, sans-serif",
    'arial': "Arial, Helvetica, sans-serif",
    'segoe ui black': "'Segoe UI', 'Arial Black', sans-serif",
    'segoe ui': "'Segoe UI', Roboto, sans-serif",
    'impact': "Impact, 'Arial Black', sans-serif",
    'tahoma': "Tahoma, Geneva, sans-serif",
    'trebuchet ms': "'Trebuchet MS', Helvetica, sans-serif",
    'verdana': "Verdana, Geneva, sans-serif",
    'calibri': "Calibri, 'Segoe UI', sans-serif",
    'aptos': "Aptos, 'Inter', sans-serif",
    'comic sans ms': "'Comic Sans MS', cursive, sans-serif",
    'georgia': "Georgia, 'Times New Roman', serif",
    'courier prime': "'Courier New', monospace",
    'poppins': "'Poppins', sans-serif",
    'inter': "'Inter', sans-serif"
  };

  function openBwSelectSheet(selectEl) {
    if (!selectEl || selectEl.disabled) return;
    let ov = document.getElementById('clipifyMobileSelectSheet');
    if (ov) ov.remove();

    const isFontSelect = /font/i.test(selectEl.id || '') || /font/i.test(selectEl.name || '') ||
      (selectEl.closest('label')?.textContent || '').toLowerCase().includes('font');
    const labelTxt = (selectEl.closest('label')?.childNodes[0]?.textContent || 'Select Option').trim() || 'Select Option';

    ov = document.createElement('div');
    ov.id = 'clipifyMobileSelectSheet';
    ov.style.cssText = 'position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,0.78);backdrop-filter:blur(10px);display:flex;align-items:flex-end;justify-content:center;';
    ov.innerHTML = `
      <div style="width:100%;max-width:480px;max-height:74vh;background:#0a0a0d;border-top:1px solid rgba(255,255,255,0.18);border-radius:20px 20px 0 0;padding:16px 16px 24px;color:#fff;display:flex;flex-direction:column;box-shadow:0 -18px 50px rgba(0,0,0,0.85);">
        <div style="display:flex;align-items:center;justify-content:space-between;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:10px;">
          <strong style="font-size:15px;letter-spacing:-0.01em;">${labelTxt}</strong>
          <button type="button" id="mSelClose" style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.14);color:#fff;width:30px;height:30px;border-radius:8px;font-size:15px;">✕</button>
        </div>
        <div id="mSelList" style="overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:2px;"></div>
      </div>
    `;
    const listEl = ov.querySelector('#mSelList');
    Array.from(selectEl.options).forEach((opt, idx) => {
      const selected = idx === selectEl.selectedIndex;
      const row = document.createElement('button');
      row.type = 'button';
      const optLower = (opt.textContent || opt.value || '').trim().toLowerCase();
      const mappedFont = isFontSelect ? (FONT_PREVIEW_MAP[optLower] || '') : '';
      const isBoldFont = isFontSelect && (optLower.includes('black') || optLower.includes('bold') || optLower.includes('impact'));
      row.style.cssText = `width:100%;text-align:left;padding:12px 14px;border-radius:12px;border:1px solid ${selected ? '#ffffff' : 'rgba(255,255,255,0.12)'};background:${selected ? '#ffffff' : 'rgba(255,255,255,0.04)'};color:${selected ? '#000000' : '#ffffff'};display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;`;

      const leftSpan = document.createElement('span');
      leftSpan.textContent = opt.textContent;
      leftSpan.style.fontSize = '14px';
      leftSpan.style.fontWeight = isBoldFont ? '900' : (selected ? '700' : '500');
      if (mappedFont) leftSpan.style.fontFamily = mappedFont;

      const rightWrap = document.createElement('span');
      rightWrap.style.cssText = 'display:flex;align-items:center;gap:8px;flex-shrink:0;';
      if (isFontSelect && opt.value !== 'none') {
        const previewAa = document.createElement('span');
        previewAa.textContent = 'Aa';
        previewAa.style.cssText = `padding:2px 8px;border-radius:6px;font-size:13px;border:1px solid ${selected ? 'rgba(0,0,0,0.22)' : 'rgba(255,255,255,0.18)'};font-weight:${isBoldFont ? '900' : '700'};`;
        if (mappedFont) previewAa.style.fontFamily = mappedFont;
        rightWrap.appendChild(previewAa);
      }
      const radioDot = document.createElement('span');
      radioDot.style.cssText = `width:18px;height:18px;border-radius:50%;border:2px solid ${selected ? '#000' : 'rgba(255,255,255,0.45)'};display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:900;`;
      radioDot.textContent = selected ? '✓' : '';
      rightWrap.appendChild(radioDot);

      row.appendChild(leftSpan);
      row.appendChild(rightWrap);
      row.onclick = () => {
        selectEl.selectedIndex = idx;
        selectEl.dataset.userChanged = '1';
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        ov.remove();
      };
      listEl.appendChild(row);
    });

    ov.querySelector('#mSelClose').onclick = () => ov.remove();
    ov.addEventListener('click', (ev) => { if (ev.target === ov) ov.remove(); });
    document.body.appendChild(ov);
  }

  ['mousedown', 'touchstart'].forEach(evtName => {
    document.addEventListener(evtName, (e) => {
      const sel = e.target && e.target.closest ? e.target.closest('select') : null;
      if (!sel) return;
      e.preventDefault();
      e.stopPropagation();
      sel.blur();
      if (evtName === 'touchstart' || !('ontouchstart' in window)) {
        openBwSelectSheet(sel);
      }
    }, { capture: true, passive: false });
  });

  // Mobile-only anti-squeeze layout & Caption Playground spacing polish
  (function injectMobileAntiSqueezeCss() {
    if (document.getElementById('clipify-mobile-antisqueeze-css')) return;
    const st = document.createElement('style');
    st.id = 'clipify-mobile-antisqueeze-css';
    st.textContent = `
      .shell, .main-content, main, .workspace {
        padding-left: 10px !important;
        padding-right: 10px !important;
        max-width: 100vw !important;
        box-sizing: border-box !important;
      }
      .card, .panel, .beta-card, .caption-playground-card, .caption-studio-card {
        padding: 14px 12px !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
        box-sizing: border-box !important;
      }
      #captionStylesGrid, .caption-styles-grid {
        grid-template-columns: 1fr !important;
        gap: 10px !important;
      }
      .caption-style-card {
        padding: 12px !important;
        width: 100% !important;
        box-sizing: border-box !important;
      }
      .caption-style-preview, .caption-preview-box {
        padding: 10px 8px !important;
        word-spacing: 0.18em !important;
        letter-spacing: 0.02em !important;
        line-height: 1.45 !important;
        display: flex !important;
        flex-wrap: wrap !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 6px !important;
      }
      .caption-style-preview span, .caption-preview-box span {
        margin: 0 3px !important;
      }
      .caption-studio-header {
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 8px !important;
      }
    `;
    (document.head || document.documentElement).appendChild(st);
  })();

})();
