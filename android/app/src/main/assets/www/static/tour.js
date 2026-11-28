/**
 * Clipify AI - Interactive Guided Workspace Tour & Support System
 * Automatically recognizes the active workspace:
 * - Create a Short (/ or #create)
 * - Projects Workspace (#projects)
 * - Post-Processing Editor (#editor)
 * - Beta Testing Lab (#beta)
 * - Live Stream Studio (/live)
 * - AI Narration Studio (/narrate)
 */
(function () {
  const TOUR_STORAGE_KEY = 'clipify_tour_completed';

  // ==========================================
  // 1. CREATE A SHORT STEPS (index.html #create)
  // ==========================================
  const CREATE_STEPS = [
    {
      target: '#openInput, #openOutput',
      title: '1. Quick Workspace Folder Access',
      desc: 'Instant 1-click access to your files: <b>[ Open input ]</b> opens your raw footage folder, and <b>[ Open output ]</b> opens your rendered 9:16 vertical shorts in Windows File Explorer.',
      pos: 'bottom'
    },
    {
      target: '#dropzone, #videoInput',
      title: '2. Video Import & Drag-and-Drop Zone',
      desc: 'Drag and drop any long-form video file (MP4, MKV, MOV, WEBM) directly into this dropzone, or browse local drives with instant codec validation.',
      pos: 'right'
    },
    {
      target: '#youtubeUrl, #fetchUrl',
      title: '3. YouTube Link Ingestion',
      desc: 'Paste any public YouTube URL and click <b>Import</b> to download and process long videos automatically at full resolution.',
      pos: 'bottom'
    },
    {
      target: '#navClearCacheLink, #create .btn-clear-cache-link, .btn-clear-cache-link',
      title: '4. Clear Cache & Temporary Footage',
      desc: 'Reclaim gigabytes of disk storage in 1 click! Safely purges cached Whisper transcriptions and downloaded YouTube video files without touching your finished shorts in <code>output/</code>.',
      pos: 'bottom'
    },
    {
      target: '#modelSelect, #btnOpenModelHub',
      title: '5. AI Intelligence Engine & Model Hub',
      desc: 'Choose your local Ollama LLM (Qwen 2.5 7B, Llama 3.2, DeepSeek) or connect Hugging Face Serverless Cloud for instant highlight extraction.',
      pos: 'top'
    },
    {
      target: '#provTabOllama, #provTabHuggingFace',
      title: '6. Local vs Cloud AI Provider Switcher',
      desc: 'Switch between <b>Local Ollama</b> (100% private, offline, zero API fees) and <b>Hugging Face Cloud</b> (instant cloud processing requiring 0 GB of local RAM).',
      pos: 'top'
    },
    {
      target: '#fontSelect',
      title: '7. Subtitle Typography & Fonts',
      desc: 'Select high-legibility subtitle fonts: <b>Montserrat Extra Bold</b>, <b>Impact</b>, <b>Segoe UI Black</b>, or <b>Arial Black</b> with high-contrast outlines.',
      pos: 'top'
    },
    {
      target: '#clips',
      title: '8. Target Number of Shorts',
      desc: 'Configure how many distinct viral clips (1 to 4) the AI should discover, rank, frame, and export from your source video.',
      pos: 'top'
    },
    {
      target: '#minDuration, #maxDuration',
      title: '9. Short Duration Range (Seconds)',
      desc: 'Define minimum and maximum clip duration (25s–60s). The AI refines speech boundaries to prevent awkward sentence cutoffs.',
      pos: 'top'
    },
    {
      target: '#splitScreenToggle',
      title: '10. Split-Screen Podcasting Layout',
      desc: 'Transform horizontal interviews and video podcasts into stacked 9:16 vertical shorts. Automatically frames conversation partners on top and bottom.',
      pos: 'bottom'
    },
    {
      target: '#gamingSplitToggle, #gamingSplitRow',
      title: '11. 🎮 Gaming Split-Screen Architecture',
      desc: '<b>ENABLED:</b> Full gameplay stream on top + Streamer webcam on bottom.<br><b>DISABLED:</b> 2-person conversation split with face-tracking.',
      pos: 'bottom'
    },
    {
      target: '#fastWhisperToggle',
      title: '12. Turbo WhisperX Acceleration',
      desc: 'Toggle Turbo WhisperX for up to 5x faster offline speech-to-text transcription with GPU CUDA acceleration and word-level timestamp alignment.',
      pos: 'top'
    },
    {
      target: '#logoEnabled, #watermarkPanel',
      title: '13. Watermark & Logo Overlay',
      desc: 'Brand your clips automatically with custom channel logos, selectable anchor positions (top-right, bottom-center), and optional chroma-key background removal.',
      pos: 'top'
    },
    {
      target: '#createBtn',
      title: '14. 1-Click Generate Shorts',
      desc: 'Click Generate to execute the complete local pipeline: Audio extraction → WhisperX transcription → Ollama viral scoring → 9:16 smart framing → Caption burn-in.',
      pos: 'top'
    },
    {
      target: '#progressPanel',
      title: '15. Real-Time Pipeline Tracker',
      desc: 'Follow live progress updates across every phase: Transcribe, AI Analyze, Smart Edit, Captions, and Final Render with detailed event logs.',
      pos: 'top'
    }
  ];

  // ==========================================
  // 2. PROJECTS WORKSPACE STEPS (#projects)
  // ==========================================
  const PROJECTS_STEPS = [
    {
      target: '#refreshProjects',
      title: '1. Refresh Project Library',
      desc: 'Scan local workspace and jobs folders to sync newly rendered clips or updates across sessions.',
      pos: 'bottom'
    },
    {
      target: '#projectList',
      title: '2. Rendered Shorts Library & Clip Grid',
      desc: 'Replay finished 9:16 vertical cuts, copy AI-generated titles & hashtags in one click, download MP4s, or launch the post-processing editor.',
      pos: 'top'
    },
    {
      target: '#refreshTrash, #trashList',
      title: '3. Built-In Recycle Bin & Recovery Shelf',
      desc: 'Never lose accidental deletions! Deleted projects are safely staged here where they can be restored back to your active library or permanently erased.',
      pos: 'top'
    }
  ];

  // ==========================================
  // 3. POST-PROCESSING EDITOR STEPS (#editor)
  // ==========================================
  const EDITOR_STEPS = [
    {
      target: '#editorPreviewFrame, #reviewVideo',
      title: '1. Interactive 9:16 Preview Frame',
      desc: 'Review your vertical cut in full resolution with interactive playback, pause, seeking, and real-time canvas overlays.',
      pos: 'right'
    },
    {
      target: '#editorLogo, #editorDragHint',
      title: '2. Draggable Watermark & Logo Overlay',
      desc: 'Brand a finished Short without rerunning AI pipelines! Drag overlays directly on the video player with live visual coordinates.',
      pos: 'left'
    },
    {
      target: '#editorClipSwitcher',
      title: '3. Multi-Cut Switcher',
      desc: 'Easily cycle between all candidate shorts generated for this job to review and export individual variations.',
      pos: 'left'
    },
    {
      target: '#reviewTitle, #reviewMeta',
      title: '4. Project Metadata & Render Specs',
      desc: 'Displays resolution (1080 × 1920), duration, source parent job ID, and AI viral hook rating.',
      pos: 'left'
    }
  ];

  // ==========================================
  // 4. BETA TESTING LAB STEPS (#beta)
  // ==========================================
  const BETA_STEPS = [
    {
      target: '#betaDropZone, #betaFileInput',
      title: '1. Beta Source Footage Dropzone',
      desc: 'Drag & drop raw horizontal clips here or browse files to test the next-generation AI video processing engine.',
      pos: 'bottom'
    },
    {
      target: '#betaYtUrl, #betaYtImportBtn',
      title: '2. Experimental YouTube Link Ingestion',
      desc: 'Paste any video URL and click <b>Import</b> to download and test experimental stream segmenting at full 1080p resolution.',
      pos: 'bottom'
    },
    {
      target: '#beta .btn-clear-cache-link, .btn-clear-cache-link',
      title: '3. Clear Beta Cache & Storage',
      desc: 'Clean downloaded YouTube test videos and Whisper caches with 1 click to keep your drives clean without touching rendered shorts.',
      pos: 'bottom'
    },
    {
      target: '#betaSplitRatioRow, #betaSplitRatio, #betaLayout',
      title: '4. Two-Panel Split-Ratio Framing',
      desc: 'Fine-tune exact split ratio percentages (e.g. 50/50, 60/40) for stacked horizontal-to-vertical compositions with live drag handle.',
      pos: 'left'
    },
    {
      target: '#betaPremiumCaptions, #betaCaptionPreset',
      title: '5. Premium Motion Subtitles',
      desc: 'Test kinetic typography styles with high-energy scale-pop bouncy words, glowing strokes, and animated text transitions.',
      pos: 'left'
    },
    {
      target: '#betaSituationalCues',
      title: '6. Situational Action Cues',
      desc: 'Enable AI context cues that highlight dramatic gasps, screaming reactions, laughter, and gameplay climax moments.',
      pos: 'left'
    },
    {
      target: '#betaWatermarkEnabled, #betaWatermarkText',
      title: '7. Custom Watermark Branding',
      desc: 'Overlay channel handles or custom text stamps with adjustable opacity, angle tilt, and anchor positions.',
      pos: 'left'
    },
    {
      target: '#betaRunPipelineBtn',
      title: '8. Run Experimental AI Pipeline',
      desc: 'Execute experimental segmentation and framing models with real-time profiling and live GPU acceleration metrics.',
      pos: 'top'
    },
    {
      target: '#betaPreviewFrame, #betaResultVideo',
      title: '9. Real-Time Result Monitor & Split Resizer',
      desc: 'Watch the newly processed beta vertical Short inside the 9:16 interactive player frame with live draggable split resizer handle.',
      pos: 'left'
    },
    {
      target: '#betaTextEditorPanel, #betaTextInput, #betaApplyTextBtn',
      title: '10. Draggable Text & Timeline Overlay',
      desc: 'Brand or annotate your Short directly! Drag text overlay anywhere on the video preview, set start/end timestamps on the timeline, and adjust font, color, and background box.',
      pos: 'left'
    },
    {
      target: '#betaDownloadBtn, #betaOpenInEditor',
      title: '11. Direct Download & Edit Actions',
      desc: 'Download the rendered MP4 immediately or jump directly to the full Post-Processing Editor.',
      pos: 'left'
    }
  ];

  // ==========================================
  // 4b. INSTANT CLIPPING STEPS (/instant)
  // ==========================================
  const INSTANT_STEPS = [
    {
      target: '#instantSourceCard, #instantDropzone',
      title: '1. Source Media Input',
      desc: 'Drop local video files here or paste any YouTube URL to instantly import footage without touching other workspaces.',
      pos: 'right'
    },
    {
      target: '#instantPresetCard, #instantDurationGroup',
      title: '2. Lightning Fast Presets & Multi-Clip Count',
      desc: 'Choose target duration (15s, 30s, or 60s) and batch generate 1, 2, 3, or 5 vertical clips at once. Completely skips heavy LLM candidate ranking to finish in seconds!',
      pos: 'right'
    },
    {
      target: '#instantLayoutGroup, #instantCaptionsGroup',
      title: '3. Framing Layout & Kinetic Captions',
      desc: 'Choose from 9:16 Center Crop, Blur-Fill, or Split Screen layouts (Top/Bottom 50/50 & Gaming/Facecam), and toggle dynamic Kinetic Captions.',
      pos: 'right'
    },
    {
      target: '#btnStartInstantClip',
      title: '4. Isolated Instant Generation',
      desc: 'Click <b>⚡ Make Instant Short</b> to immediately kick off accelerated hardware-direct 9:16 rendering. Completely isolated so your other jobs stay safe.',
      pos: 'top'
    },
    {
      target: '#instantConsoleCard, #instantConsoleLog',
      title: '5. Live Dark Terminal Log',
      desc: 'Watch real-time frame-by-frame encoding and stream analysis in the themed dark console with zero delay or freeze.',
      pos: 'left'
    },
    {
      target: '#instantReviewCard, #instantVideoPlayer',
      title: '6. Multi-Clip Review, Download & Editor',
      desc: 'Switch between generated clips, preview high-bitrate vertical video, download MP4s individually or all at once, or send to Editor.',
      pos: 'left',
      isFinal: true
    }
  ];

  // ==========================================
  // 5. LIVE STUDIO STEPS (/live)
  // ==========================================
  const LIVE_STEPS = [
    {
      target: '.source-tabs',
      title: '1. Multi-Platform Stream Ingestion',
      desc: 'Select your live stream source: <b>YouTube Live</b>, <b>Twitch Live</b>, <b>Kick Live</b>, or local <b>OBS Studio</b> RTMP ingestion.',
      pos: 'bottom'
    },
    {
      target: '#liveSourceUrl, #btnConnectStream',
      title: '2. Stream Connection & Status Bar',
      desc: 'Paste any public live stream or channel URL and click <b>Connect & Start Clipping</b> to attach the real-time buffer.',
      pos: 'bottom'
    },
    {
      target: '#btnObsGuide, #obsConfigBox',
      title: '3. OBS Studio Local RTMP Stream Ingestion',
      desc: 'Stream directly from OBS on the same PC! Click <b>OBS Setup</b> for your local RTMP Server URL and Stream Key to capture private streams latency-free.',
      pos: 'bottom'
    },
    {
      target: '#monitorScreen, #waveform',
      title: '4. 16:9 Broadcast Centerpiece Preview Monitor',
      desc: 'Live broadcast preview with stream title, active duration, buffer health, and real-time audio waveform visualizer.',
      pos: 'right'
    },
    {
      target: '#btnInstantClip, #btnLiveClipNow',
      title: '5. ⚡ Instant Clip Quick Capture',
      desc: 'Hit the instant clip button to immediately capture the last 15s, 30s, or 60s of broadcast into a framed 9:16 vertical Short.',
      pos: 'bottom'
    },
    {
      target: '#toggleAutoClip',
      title: '6. Hands-Free Automated Clipping Engine',
      desc: 'Enable Auto-Clipping to let AI continuously monitor the live stream, detect climax moments and chat spikes, and auto-render vertical Shorts while you stream.',
      pos: 'left'
    },
    {
      target: '#autoClipIntervalSelect, #autoClipTargetInput',
      title: '7. Auto-Clip Frequency & Target Limits',
      desc: 'Configure how often the AI evaluates stream buffers (e.g. every 5 mins) and set maximum clip targets (1 - 100 clips) before pausing.',
      pos: 'left'
    },
    {
      target: '#sensitivitySlider',
      title: '8. Highlight Detection Sensitivity Slider',
      desc: 'Adjust sensitivity from 1 (only the highest viral peaks) to 10 (frequent energetic clips) to match your broadcast style.',
      pos: 'left'
    },
    {
      target: '#toggleAutoEdit, #toggleFaceTrack',
      title: '9. AI Smart Editing & Speaker Face Tracking',
      desc: 'Automatically tracks streamer and guest face centroids, applying smooth deadzone framing and energy zooms on excited reactions.',
      pos: 'left'
    },
    {
      target: '#toggleGamingLayout',
      title: '10. Gaming Split-Screen Architecture',
      desc: 'When enabled: Full gameplay on top + Streamer webcam on bottom. When disabled: 2-person conversation split (host on top + guest below).',
      pos: 'left'
    },
    {
      target: '#toggleAutoCaptions',
      title: '11. Animated Live Auto-Captions',
      desc: 'Automatically transcribes spoken dialogue and burns dynamic word-by-word karaoke subtitles in your chosen typography.',
      pos: 'left'
    },
    {
      target: '#toggleCustomText, #customTextInput',
      title: '12. Custom Branding Watermark & Channel Handle',
      desc: 'Add custom broadcast watermarks (e.g., LIVE · @MYCHANNEL) with selectable positioning and brand colors.',
      pos: 'left'
    },
    {
      target: '#transcriptFeed',
      title: '13. Real-Time Whisper Speech-to-Text Feed',
      desc: 'Live continuous speech-to-text transcription as the streamer talks, timestamping every sentence and calculating engagement velocity.',
      pos: 'left'
    },
    {
      target: '#studioConsolePanel',
      title: '14. Studio Activity & Event Console',
      desc: 'Monitors real-time live events, stream resolution, buffer ingestion metrics, and highlight detection triggers.',
      pos: 'top'
    },
    {
      target: '#btnRankClipsAi',
      title: '15. AI Viral Hook Clip Ranker Terminal',
      desc: 'Click <b>RANK CLIPS AI</b> to run local LLM evaluations on all captured clips, scoring hook power and ordering top viral candidates.',
      pos: 'top'
    },
    {
      target: '#liveClipsGrid',
      title: '16. Live Shorts Gallery & Batch Controls',
      desc: 'Horizontal shelf displaying all rendered live clips. Preview videos, copy AI titles, download MP4s, or batch select and delete unwanted clips.',
      pos: 'top'
    }
  ];

  // ==========================================
  // 6. NARRATION STUDIO STEPS (/narrate)
  // ==========================================
  const NARRATE_STEPS = [
    {
      target: '#targetDuration',
      title: '1. Target Video Length Slider',
      desc: 'Set the target duration for your Short from 30 to 60 seconds. The AI automatically calibrates spoken word count and pacing to match.',
      pos: 'bottom'
    },
    {
      target: '#scriptInput, #wordCount',
      title: '2. Narration Dialogue & Script Input',
      desc: 'Write or paste spoken narration dialogue, story hooks, or facts. The live word counter and estimated duration update in real time.',
      pos: 'right'
    },
    {
      target: '#scriptPrompt, #generateScript, #improveScript',
      title: '3. AI Script Writing & 1-Click Polish',
      desc: 'Describe an idea in the AI prompt box and click <b>Generate with AI</b>, or click <b>Improve with AI</b> to rewrite your draft for higher retention with strong hooks.',
      pos: 'right'
    },
    {
      target: '#voiceGrid, #voiceSearch',
      title: '4. Neural Kokoro Voice Actors',
      desc: 'Browse and audition high-fidelity offline neural voice actors. Filter by tone, accent, and style with zero cloud API latency.',
      pos: 'right'
    },
    {
      target: '#voiceSpeed',
      title: '5. Voice Pacing & Speed Adjustment',
      desc: 'Fine-tune spoken speech delivery from Slower (-2), Natural (0), to Faster (+2) for high-energy Shorts.',
      pos: 'top'
    },
    {
      target: '#clipFolder, #chooseClipFolder',
      title: '6. Atmosphere & Background Footage',
      desc: 'Select licensed vertical 9:16 background gameplay (GTA 5 Stunts, Subway Surfers, Minecraft Parkour) or change to your custom folders.',
      pos: 'right'
    },
    {
      target: '#btnDownloadExtra',
      title: '7. Additional Background Gameplay (62 Videos)',
      desc: 'Click to automatically download 62 additional licensed vertical gameplay backgrounds in high quality directly to your library.',
      pos: 'right'
    },
    {
      target: '#customVideo',
      title: '8. Custom Gameplay Video Upload',
      desc: 'Want your own gameplay behind the story? Click here to upload any local video clip directly into the Narration Studio.',
      pos: 'right'
    },
    {
      target: '#presetGrid',
      title: '9. Word-Sync Subtitle Presets',
      desc: 'Choose your caption aesthetic: <b>Sync yellow</b> (active word follows audio), <b>White + yellow</b>, or <b>Color words</b>.',
      pos: 'right'
    },
    {
      target: '#captionSize',
      title: '10. Caption Typography Size Slider',
      desc: 'Scale your vertical caption typography up to 120px for maximum readability on mobile feeds.',
      pos: 'top'
    },
    {
      target: '#generateNarrate',
      title: '11. Generate Narrated Short',
      desc: 'Click Generate to synthesize offline Kokoro neural audio, align speech timestamps, composite background gameplay, and burn dynamic subtitles.',
      pos: 'top'
    },
    {
      target: '#narratePreview',
      title: '12. 9:16 Live Preview & Video Player',
      desc: 'Review the completed vertical Short in the responsive 9:16 video player with full playback controls.',
      pos: 'left'
    },
    {
      target: '.timeline',
      title: '13. Multi-Track Timeline Sync',
      desc: 'Visual timeline showing multi-track synchronization across voice audio, video clip, and subtitles.',
      pos: 'left'
    },
    {
      target: '#narrateDownload',
      title: '14. Instant Download & Social Export',
      desc: 'Download ready-to-post MP4 videos with 1 click, or click <b>Share / Publish</b> to prepare metadata for YouTube Shorts, TikTok, and Instagram Reels.',
      pos: 'left'
    },
    {
      target: '#narrateHistory',
      title: '15. Narration Archive & History Shelf',
      desc: 'Browse, replay, and manage previously generated narrated shorts stored locally on your PC.',
      pos: 'top'
    }
  ];

  const TRENDING_STEPS = [
    {
      title: 'Trending & Live Radar',
      badge: 'LIVE DISCOVERY',
      description: 'Discover trending streams and gameplay broadcasts across YouTube, Twitch, and Kick in real time.',
      target: '#trending .trending-header, #trending',
      position: 'bottom'
    },
    {
      title: 'Search & Filter Streams',
      badge: 'FILTERING',
      description: 'Search by creator, game, or topic, or switch platforms and refresh the live feed instantly.',
      target: '#trendingSearchInput',
      position: 'bottom'
    },
    {
      title: 'One-Click Import',
      badge: 'SEND TO STUDIO',
      description: 'Click any trending stream or video card to send it straight into Clipify AI for instant clipping.',
      target: '#trendingYtLiveGrid, #trendingGenericStreamsGrid, #trending',
      position: 'top'
    }
  ];

  const MODELS_STEPS = [
    {
      title: 'AI Models & Engine Hub',
      badge: 'LOCAL & CLOUD',
      description: 'Manage local Ollama models, Hugging Face Cloud inference, and WhisperX transcription weights in one place.',
      target: '#models .mh-header, #models',
      position: 'bottom'
    },
    {
      title: 'Search & Install Models',
      badge: 'ONE-CLICK PULL',
      description: 'Filter or search recommended models by speed, RAM, or vision capability and pull them directly into Clipify AI.',
      target: '#mhGrid, #models',
      position: 'top'
    }
  ];

  const STORAGE_STEPS = [
    {
      title: 'Storage & Disk Manager',
      badge: 'WORKSPACE PATH',
      description: 'Inspect disk usage across generated shorts, cached transcripts, and imported source videos, or move your storage folder.',
      target: '#storageCardsGrid, #storage',
      position: 'bottom'
    }
  ];

  const SUPPORT_STEPS = [
    {
      title: 'Support Clipify AI',
      badge: '100% FREE & LOCAL',
      description: 'Support development via Ko-fi, GitHub Sponsors, or community sharing so Clipify AI stays free and open.',
      target: '#support',
      position: 'bottom'
    }
  ];

  const PROMOTERS_STEPS = [
    {
      title: 'Promote Us & Earn',
      badge: 'CREATOR PROGRAM',
      description: 'Share Clipify AI tutorials, shorts, or showcases and join the Discord creator community.',
      target: '#promoters',
      position: 'bottom'
    }
  ];

  const CAMPAIGNS_STEPS = [
    {
      title: 'Clipping Campaigns',
      badge: 'BOUNTIES',
      description: 'Browse active creator campaigns, clipping bounties, and featured rewards.',
      target: '#campaigns',
      position: 'bottom'
    }
  ];

  // Distinct section theming colors (designed for aesthetic, non-AI craft look)
  const CONTEXT_THEMES = {
    instant: {
      name: 'Instant Clipping Lab',
      label: '⚡ Instant Clipping',
      steps: INSTANT_STEPS,
      accent: '#ffffff',
      accentLight: '#e4e4e7',
      accentGlow: 'rgba(255, 255, 255, 0.45)',
      badgeBg: 'rgba(255, 255, 255, 0.12)',
      badgeBorder: 'rgba(255, 255, 255, 0.35)',
    },
    beta: {
      name: 'Beta Testing Lab',
      label: '🧪 Beta Lab',
      steps: BETA_STEPS,
      accent: '#22c55e',
      accentLight: '#4ade80',
      accentGlow: 'rgba(34, 197, 94, 0.45)',
      badgeBg: 'rgba(34, 197, 94, 0.12)',
      badgeBorder: 'rgba(34, 197, 94, 0.35)',
    },
    trending: {
      name: 'Trending Radar',
      label: '🔥 Trending',
      steps: TRENDING_STEPS,
      accent: '#ef4444',
      accentLight: '#f87171',
      accentGlow: 'rgba(239, 68, 68, 0.45)',
      badgeBg: 'rgba(239, 68, 68, 0.12)',
      badgeBorder: 'rgba(239, 68, 68, 0.35)',
    },
    models: {
      name: 'AI Models Hub',
      label: '🧠 Models',
      steps: MODELS_STEPS,
      accent: '#ffffff',
      accentLight: '#e4e4e7',
      accentGlow: 'rgba(255, 255, 255, 0.4)',
      badgeBg: 'rgba(255, 255, 255, 0.12)',
      badgeBorder: 'rgba(255, 255, 255, 0.35)',
    },
    storage: {
      name: 'Storage Manager',
      label: '💾 Storage',
      steps: STORAGE_STEPS,
      accent: '#38bdf8',
      accentLight: '#7dd3fc',
      accentGlow: 'rgba(56, 189, 248, 0.45)',
      badgeBg: 'rgba(56, 189, 248, 0.12)',
      badgeBorder: 'rgba(56, 189, 248, 0.35)',
    },
    support: {
      name: 'Support Us',
      label: '🤍 Support Us',
      steps: SUPPORT_STEPS,
      accent: '#ffffff',
      accentLight: '#e4e4e7',
      accentGlow: 'rgba(255, 255, 255, 0.4)',
      badgeBg: 'rgba(255, 255, 255, 0.12)',
      badgeBorder: 'rgba(255, 255, 255, 0.35)',
    },
    promoters: {
      name: 'Promote Us',
      label: '📣 Promote Us',
      steps: PROMOTERS_STEPS,
      accent: '#ffffff',
      accentLight: '#e4e4e7',
      accentGlow: 'rgba(255, 255, 255, 0.4)',
      badgeBg: 'rgba(255, 255, 255, 0.12)',
      badgeBorder: 'rgba(255, 255, 255, 0.35)',
    },
    campaigns: {
      name: 'Campaigns',
      label: '🎯 Campaigns',
      steps: CAMPAIGNS_STEPS,
      accent: '#ffffff',
      accentLight: '#e4e4e7',
      accentGlow: 'rgba(255, 255, 255, 0.4)',
      badgeBg: 'rgba(255, 255, 255, 0.12)',
      badgeBorder: 'rgba(255, 255, 255, 0.35)',
    },
    create: {
      name: 'Create a Short',
      label: '🎬 Create',
      steps: CREATE_STEPS,
      accent: '#f59e0b',
      accentLight: '#fbbf24',
      accentGlow: 'rgba(245, 158, 11, 0.45)',
      badgeBg: 'rgba(245, 158, 11, 0.12)',
      badgeBorder: 'rgba(245, 158, 11, 0.35)',
    },
    projects: {
      name: 'Projects Workspace',
      label: '📁 Projects',
      steps: PROJECTS_STEPS,
      accent: '#06b6d4',
      accentLight: '#22d3ee',
      accentGlow: 'rgba(6, 182, 212, 0.45)',
      badgeBg: 'rgba(6, 182, 212, 0.12)',
      badgeBorder: 'rgba(6, 182, 212, 0.35)',
    },
    editor: {
      name: 'Post-Processing Editor',
      label: '✂️ Editor',
      steps: EDITOR_STEPS,
      accent: '#a855f7',
      accentLight: '#c084fc',
      accentGlow: 'rgba(168, 85, 247, 0.45)',
      badgeBg: 'rgba(168, 85, 247, 0.12)',
      badgeBorder: 'rgba(168, 85, 247, 0.35)',
    },
    live: {
      name: 'Live Studio',
      label: '🔴 Live Studio',
      steps: LIVE_STEPS,
      accent: '#ef4444',
      accentLight: '#f87171',
      accentGlow: 'rgba(239, 68, 68, 0.45)',
      badgeBg: 'rgba(239, 68, 68, 0.12)',
      badgeBorder: 'rgba(239, 68, 68, 0.35)',
    },
    narrate: {
      name: 'Narration Studio',
      label: '🎙️ Narration Studio',
      steps: NARRATE_STEPS,
      accent: '#0284c7',
      accentLight: '#38bdf8',
      accentGlow: 'rgba(56, 189, 248, 0.45)',
      badgeBg: 'rgba(56, 189, 248, 0.12)',
      badgeBorder: 'rgba(56, 189, 248, 0.35)',
    }
  };

  // Helper to accurately determine active workspace context
  function getCurrentPageContext() {
    const p = window.location.pathname.toLowerCase();
    if (p.includes('/live')) return 'live';
    if (p.includes('/narrate')) return 'narrate';

    const sections = ['instant', 'beta', 'trending', 'models', 'storage', 'support', 'promoters', 'campaigns', 'projects', 'editor', 'create'];

    // 1. Check hash first
    const h = (window.location.hash || '').replace('#', '').split('?')[0].toLowerCase();
    if (sections.includes(h)) return h;

    // 2. Check active navigation link in sidebar
    const activeNav = document.querySelector('[data-nav].active');
    if (activeNav && activeNav.dataset.nav && sections.includes(activeNav.dataset.nav)) {
      return activeNav.dataset.nav;
    }

    // 3. Check which DOM section is currently visible
    for (const s of sections) {
      const el = document.getElementById(s);
      if (el) {
        const style = window.getComputedStyle(el);
        if (style.display !== 'none' && style.visibility !== 'hidden' && (el.classList.contains('visible') || el.offsetParent !== null)) {
          return s;
        }
      }
    }

    return 'create';
  }

  // Scoped, resilient target element locator
  function findVisibleTarget(selectorString, currentContext) {
    if (!selectorString) return null;
    const parts = selectorString.split(',');

    let sectionContainer = null;
    if (currentContext === 'instant') {
      sectionContainer = document.querySelector('#instant');
    } else if (currentContext === 'beta') {
      sectionContainer = document.querySelector('#beta');
    } else if (currentContext === 'projects') {
      sectionContainer = document.querySelector('#projects');
    } else if (currentContext === 'editor') {
      sectionContainer = document.querySelector('#editor');
    } else if (currentContext === 'create') {
      sectionContainer = document.querySelector('#create') || document.querySelector('main');
    }

    // 1. Prioritize elements inside the current workspace section container
    if (sectionContainer) {
      for (const p of parts) {
        const sel = p.trim();
        try {
          const els = sectionContainer.querySelectorAll(sel);
          for (let el of els) {
            const resolved = resolveVisibleElement(el);
            if (resolved) return resolved;
          }
        } catch (_) {}
      }
    }

    // 2. Fall back to search globally in document
    for (const p of parts) {
      const sel = p.trim();
      try {
        const els = document.querySelectorAll(sel);
        for (let el of els) {
          const resolved = resolveVisibleElement(el);
          if (resolved) return resolved;
        }
      } catch (_) {}
    }

    return null;
  }

  function resolveVisibleElement(el) {
    if (!el) return null;

    // Checkbox, radio, or file inputs: automatically target the enclosing visible label/toggle-row
    if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio' || el.type === 'file' || el.type === 'hidden')) {
      const parentLabel = el.closest('label') || el.closest('.toggle-row') || el.parentElement;
      if (parentLabel) el = parentLabel;
    }

    // Must be in DOM and visible
    if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') {
      return null;
    }

    const rect = el.getBoundingClientRect();
    if (rect.width > 4 && rect.height > 4) {
      return el;
    }
    return null;
  }

  // Position card comfortably with center-alignment on the orthogonal axis
  function positionCard(rect, preferredPos, cardWidth, cardHeight) {
    const margin = 20;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let left, top;

    if (preferredPos === 'bottom') {
      top = rect.bottom + margin;
      left = rect.left + (rect.width - cardWidth) / 2;
      if (top + cardHeight > vh - margin) {
        top = rect.top - cardHeight - margin;
      }
    } else if (preferredPos === 'top') {
      top = rect.top - cardHeight - margin;
      left = rect.left + (rect.width - cardWidth) / 2;
      if (top < margin) {
        top = rect.bottom + margin;
      }
    } else if (preferredPos === 'right') {
      left = rect.right + margin;
      top = rect.top + (rect.height - cardHeight) / 2;
      if (left + cardWidth > vw - margin) {
        left = rect.left - cardWidth - margin;
      }
    } else { // left
      left = rect.left - cardWidth - margin;
      top = rect.top + (rect.height - cardHeight) / 2;
      if (left < margin) {
        left = rect.right + margin;
      }
    }

    left = Math.max(margin, Math.min(left, vw - cardWidth - margin));
    top = Math.max(margin, Math.min(top, vh - cardHeight - margin));

    return { left, top };
  }

  // Compute smooth, aesthetically curved cubic Bezier curve connecting card and spotlight anchor
  function computeCurvedDottedConnector(cardRect, spotRect) {
    const cMidX = cardRect.left + cardRect.width / 2;
    const cMidY = cardRect.top + cardRect.height / 2;
    const sMidX = spotRect.left + spotRect.width / 2;
    const sMidY = spotRect.top + spotRect.height / 2;

    let x1, y1, x2, y2, cx1, cy1, cx2, cy2;

    const dx = sMidX - cMidX;
    const dy = sMidY - cMidY;

    if (Math.abs(dx) >= Math.abs(dy)) {
      if (dx > 0) {
        // Target is to the RIGHT of card
        x1 = cardRect.right;
        y1 = Math.max(cardRect.top + 20, Math.min(cardRect.bottom - 20, cardRect.top + cardRect.height * 0.4));
        x2 = spotRect.left;
        y2 = Math.max(spotRect.top + 8, Math.min(spotRect.bottom - 8, sMidY));
        const spanX = Math.max(60, (x2 - x1) * 0.55);
        const verticalBow = (y2 >= y1) ? -25 : 25;
        cx1 = x1 + spanX;
        cy1 = y1 + verticalBow;
        cx2 = x2 - spanX;
        cy2 = y2 - verticalBow * 0.5;
      } else {
        // Target is to the LEFT of card
        x1 = cardRect.left;
        y1 = Math.max(cardRect.top + 20, Math.min(cardRect.bottom - 20, cardRect.top + cardRect.height * 0.4));
        x2 = spotRect.right;
        y2 = Math.max(spotRect.top + 8, Math.min(spotRect.bottom - 8, sMidY));
        const spanX = Math.max(60, (x1 - x2) * 0.55);
        const verticalBow = (y2 >= y1) ? -25 : 25;
        cx1 = x1 - spanX;
        cy1 = y1 + verticalBow;
        cx2 = x2 + spanX;
        cy2 = y2 - verticalBow * 0.5;
      }
    } else {
      if (dy > 0) {
        // Target is BELOW card
        x1 = Math.max(cardRect.left + 24, Math.min(cardRect.right - 24, cMidX));
        y1 = cardRect.bottom;
        x2 = Math.max(spotRect.left + 8, Math.min(spotRect.right - 8, sMidX));
        y2 = spotRect.top;
        const spanY = Math.max(50, (y2 - y1) * 0.55);
        const horizontalBow = (x2 >= x1) ? 30 : -30;
        cx1 = x1 + horizontalBow;
        cy1 = y1 + spanY;
        cx2 = x2 - horizontalBow * 0.5;
        cy2 = y2 - spanY;
      } else {
        // Target is ABOVE card
        x1 = Math.max(cardRect.left + 24, Math.min(cardRect.right - 24, cMidX));
        y1 = cardRect.top;
        x2 = Math.max(spotRect.left + 8, Math.min(spotRect.right - 8, sMidX));
        y2 = spotRect.bottom;
        const spanY = Math.max(50, (y1 - y2) * 0.55);
        const horizontalBow = (x2 >= x1) ? 30 : -30;
        cx1 = x1 + horizontalBow;
        cy1 = y1 - spanY;
        cx2 = x2 - horizontalBow * 0.5;
        cy2 = y2 + spanY;
      }
    }

    const pathStr = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${cx1.toFixed(1)} ${cy1.toFixed(1)}, ${cx2.toFixed(1)} ${cy2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
    return { pathStr, x1, y1, x2, y2 };
  }

  let currentContext = 'create';
  let tourSteps = CREATE_STEPS;
  let currentStepIndex = 0;
  let overlayEl = null;
  let spotlightEl = null;
  let cardEl = null;
  let svgEl = null;
  let pathEl = null;
  let anchorDotEl = null;
  let cardDotEl = null;
  let supportModalOverlayEl = null;

  function initTourElements() {
    if (overlayEl) return;

    overlayEl = document.createElement('div');
    overlayEl.id = 'tourOverlay';

    spotlightEl = document.createElement('div');
    spotlightEl.id = 'tourSpotlight';
    spotlightEl.style.display = 'none';
    overlayEl.appendChild(spotlightEl);

    // SVG container for animated curved dotted line
    svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgEl.id = 'tourConnectorSvg';
    svgEl.setAttribute('class', 'tour-connector-svg');
    svgEl.style.display = 'none';

    pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    pathEl.id = 'tourConnectorPath';
    pathEl.setAttribute('class', 'tour-connector-path');
    svgEl.appendChild(pathEl);

    anchorDotEl = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    anchorDotEl.id = 'tourAnchorDot';
    anchorDotEl.setAttribute('class', 'tour-anchor-dot');
    svgEl.appendChild(anchorDotEl);

    cardDotEl = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    cardDotEl.id = 'tourCardDot';
    cardDotEl.setAttribute('class', 'tour-card-dot');
    svgEl.appendChild(cardDotEl);

    overlayEl.appendChild(svgEl);

    cardEl = document.createElement('div');
    cardEl.id = 'tourCard';
    overlayEl.appendChild(cardEl);

    overlayEl.addEventListener('click', (e) => {
      if (e.target === overlayEl || e.target === spotlightEl) {
        endTour();
      }
    });

    window.addEventListener('keydown', (e) => {
      if (!overlayEl || !overlayEl.classList.contains('active')) return;
      if (e.key === 'Escape') endTour();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') nextStep();
      else if (e.key === 'ArrowLeft') prevStep();
    });

    window.addEventListener('resize', updateSpotlightAndConnector);
    window.addEventListener('scroll', updateSpotlightAndConnector, { passive: true });

    document.body.appendChild(overlayEl);
  }

  function startTour(force = false, contextOverride = null) {
    if (window.isAndroidApp && !force) {
      return;
    }
    if (!force && localStorage.getItem(TOUR_STORAGE_KEY)) {
      return;
    }

    currentContext = contextOverride || getCurrentPageContext();
    const info = CONTEXT_THEMES[currentContext] || CONTEXT_THEMES['create'];
    tourSteps = info.steps;

    initTourElements();
    currentStepIndex = 0;
    overlayEl.style.display = 'block';
    overlayEl.classList.add('active');
    renderCurrentStep();
  }

  function endTour() {
    if (!overlayEl) return;
    overlayEl.classList.remove('active');
    overlayEl.style.display = 'none';
    if (svgEl) {
      svgEl.classList.remove('visible');
      svgEl.style.display = 'none';
    }
    localStorage.setItem(TOUR_STORAGE_KEY, 'true');
  }

  function nextStep() {
    if (currentStepIndex < tourSteps.length - 1) {
      currentStepIndex++;
      renderCurrentStep();
    } else {
      endTour();
      showSupportModal();
    }
  }

  function prevStep() {
    if (currentStepIndex > 0) {
      currentStepIndex--;
      renderCurrentStep();
    }
  }

  function updateConnectorCurve(theme) {
    if (!svgEl || !pathEl || !cardEl || !spotlightEl) return;
    const cardRect = cardEl.getBoundingClientRect();
    const spotRect = spotlightEl.getBoundingClientRect();

    if (spotRect.width <= 4 || spotRect.height <= 4 || cardRect.width === 0) {
      svgEl.classList.remove('visible');
      svgEl.style.display = 'none';
      return;
    }

    const conn = computeCurvedDottedConnector(cardRect, spotRect);
    if (!conn || !conn.pathStr || !conn.x1 || !conn.y1 || !conn.x2 || !conn.y2 ||
        conn.x1 < 10 || conn.y1 < 10 || conn.x2 < 10 || conn.y2 < 10) {
      svgEl.classList.remove('visible');
      svgEl.style.display = 'none';
      return;
    }

    pathEl.setAttribute('stroke', theme.accentLight);
    pathEl.style.filter = `drop-shadow(0 0 7px ${theme.accentGlow})`;
    anchorDotEl.setAttribute('fill', theme.accentLight);
    cardDotEl.setAttribute('fill', theme.accentLight);

    pathEl.setAttribute('d', conn.pathStr);
    anchorDotEl.setAttribute('cx', conn.x2);
    anchorDotEl.setAttribute('cy', conn.y2);
    cardDotEl.setAttribute('cx', conn.x1);
    cardDotEl.setAttribute('cy', conn.y1);

    svgEl.style.display = 'block';
    svgEl.classList.add('visible');
  }

  function updateSpotlightAndConnector() {
    if (!overlayEl || !overlayEl.classList.contains('active')) return;
    const theme = CONTEXT_THEMES[currentContext] || CONTEXT_THEMES['create'];
    tourSteps = theme.steps;
    const step = tourSteps[currentStepIndex];
    if (!step) return;

    const targetEl = findVisibleTarget(step.target, currentContext);
    if (!targetEl) return;

    const rect = targetEl.getBoundingClientRect();
    const pad = 8;
    spotlightEl.style.top = Math.max(0, rect.top - pad) + 'px';
    spotlightEl.style.left = Math.max(0, rect.left - pad) + 'px';
    spotlightEl.style.width = (rect.width + pad * 2) + 'px';
    spotlightEl.style.height = (rect.height + pad * 2) + 'px';

    const cardWidth = 360;
    const cardHeight = cardEl.offsetHeight || 220;
    const pos = positionCard(rect, step.pos, cardWidth, cardHeight);
    cardEl.style.top = pos.top + 'px';
    cardEl.style.left = pos.left + 'px';

    updateConnectorCurve(theme);
  }

  function renderCurrentStep() {
    if (svgEl) {
      svgEl.classList.remove('visible');
      svgEl.style.display = 'none';
    }
    if (spotlightEl) {
      spotlightEl.style.display = 'none';
    }
    const theme = CONTEXT_THEMES[currentContext] || CONTEXT_THEMES['create'];
    tourSteps = theme.steps;
    const step = tourSteps[currentStepIndex];
    if (!step) return;

    if (step.isFinal) {
      endTour();
      showSupportModal();
      return;
    }

    // Apply section color themes to overlay CSS custom properties
    overlayEl.style.setProperty('--tour-accent', theme.accent);
    overlayEl.style.setProperty('--tour-accent-light', theme.accentLight);
    overlayEl.style.setProperty('--tour-accent-glow', theme.accentGlow);
    overlayEl.style.setProperty('--tour-badge-bg', theme.badgeBg);
    overlayEl.style.setProperty('--tour-badge-border', theme.badgeBorder);

    // Locate visible target
    let targetEl = findVisibleTarget(step.target, currentContext);

    if (!targetEl) {
      if (currentStepIndex < tourSteps.length - 1) {
        currentStepIndex++;
        renderCurrentStep();
      } else {
        endTour();
        showSupportModal();
      }
      return;
    }

    try {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
    } catch (_) {
      targetEl.scrollIntoView();
    }

    setTimeout(() => {
      const rect = targetEl.getBoundingClientRect();
      const pad = 8;

      spotlightEl.style.display = 'block';
      spotlightEl.style.top = Math.max(0, rect.top - pad) + 'px';
      spotlightEl.style.left = Math.max(0, rect.left - pad) + 'px';
      spotlightEl.style.width = (rect.width + pad * 2) + 'px';
      spotlightEl.style.height = (rect.height + pad * 2) + 'px';
      spotlightEl.style.borderRadius = '16px';

      // Clean card without cross-page switcher bar
      cardEl.innerHTML = `
        <div class="tour-card-header">
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="tour-context-badge">${theme.label}</span>
            <span class="tour-step-badge">COMPONENT ${currentStepIndex + 1} OF ${tourSteps.length}</span>
          </div>
          <button type="button" class="tour-skip-btn" id="tourSkipBtn">Skip</button>
        </div>
        <h3 class="tour-card-title">${step.title}</h3>
        <p class="tour-card-desc">${step.desc}</p>
        <div class="tour-card-footer">
          <div class="tour-nav-btns">
            ${currentStepIndex > 0 ? `<button type="button" class="tour-btn tour-btn-prev" id="tourPrevBtn">← Previous</button>` : ''}
            <button type="button" class="tour-btn tour-btn-next" id="tourNextBtn">
              ${currentStepIndex === tourSteps.length - 1 ? 'Finish Tour ★' : 'Next →'}
            </button>
          </div>
        </div>
      `;

      cardEl.querySelector('#tourSkipBtn')?.addEventListener('click', endTour);
      cardEl.querySelector('#tourPrevBtn')?.addEventListener('click', prevStep);
      cardEl.querySelector('#tourNextBtn')?.addEventListener('click', nextStep);

      const cardWidth = 360;
      const cardHeight = cardEl.offsetHeight || 220;
      const pos = positionCard(rect, step.pos, cardWidth, cardHeight);

      cardEl.style.top = pos.top + 'px';
      cardEl.style.left = pos.left + 'px';
      cardEl.style.display = 'block';

      // Update animated curved dotted SVG line
      requestAnimationFrame(() => {
        updateConnectorCurve(theme);
      });
    }, 110);
  }

  // ==========================================
  // ==========================================
  // SUPPORT MODAL & FLOATING STARGAZERS GALAXY
  // ==========================================
  let supportersPhysicsActive = false;
  let supportersAnimId = null;
  let supportersList = [];
  let galaxyStarsCleanup = null;
  let promotersStarsCleanup = null;

  // 34 Verified Real GitHub Accounts (Sherlock Dev community / supporters)
  let REAL_STARGAZERS = [
    { login: 'Lerreu', avatar_url: 'https://avatars.githubusercontent.com/u/75152710?v=4' },
    { login: 'maxwellhammer', avatar_url: 'https://avatars.githubusercontent.com/u/82539786?v=4' },
    { login: 'Aaryan-0s', avatar_url: 'https://avatars.githubusercontent.com/u/84567585?v=4' },
    { login: 'Unsatisfied123', avatar_url: 'https://avatars.githubusercontent.com/u/91078073?v=4' },
    { login: 'TejoSaiSwaroop', avatar_url: 'https://avatars.githubusercontent.com/u/104894666?v=4' },
    { login: 'kudakkwashe', avatar_url: 'https://avatars.githubusercontent.com/u/118259334?v=4' },
    { login: 'Anonymonkz', avatar_url: 'https://avatars.githubusercontent.com/u/134843461?v=4' },
    { login: 'SAMUELPAUL2007', avatar_url: 'https://avatars.githubusercontent.com/u/188880985?v=4' },
    { login: 'divyam314', avatar_url: 'https://avatars.githubusercontent.com/u/208231694?v=4' },
    { login: 'NandakishorEnAi', avatar_url: 'https://avatars.githubusercontent.com/u/210684940?v=4' },
    { login: 'Aditya-07-dev', avatar_url: 'https://avatars.githubusercontent.com/u/253079667?v=4' },
    { login: 'kenzfx8-gif', avatar_url: 'https://avatars.githubusercontent.com/u/258203318?v=4' },
    { login: 'naumanalighazali-a11y', avatar_url: 'https://avatars.githubusercontent.com/u/265206388?v=4' },
    { login: 'webovka1', avatar_url: 'https://avatars.githubusercontent.com/u/288022013?v=4' },
    { login: 'adithks627-cpu', avatar_url: 'https://avatars.githubusercontent.com/u/288409665?v=4' },
    { login: 'vivienneee123-lgtm', avatar_url: 'https://avatars.githubusercontent.com/u/313046937?v=4' },
    { login: 'rishabbhardwaj38-eng', avatar_url: 'https://avatars.githubusercontent.com/u/324034825?v=4' },
    { login: 'personallity5656', avatar_url: 'https://avatars.githubusercontent.com/u/328689405?v=4' },
    { login: 'CHEWBACCA05', avatar_url: 'https://avatars.githubusercontent.com/u/331156104?v=4' },
    { login: 'rihanrajputyubi-cmd', avatar_url: 'https://avatars.githubusercontent.com/u/347490849?v=4' },
    { login: 'mitchelpatrick001-dot', avatar_url: 'https://avatars.githubusercontent.com/u/354305907?v=4' },
    { login: 'mohammedfarajallah367-arch', avatar_url: 'https://avatars.githubusercontent.com/u/354670647?v=4' },
    { login: 'fitnesssiddhant-design', avatar_url: 'https://avatars.githubusercontent.com/u/355329702?v=4' },
    { login: 'laliteshsaikrish2011-png', avatar_url: 'https://avatars.githubusercontent.com/u/356862194?v=4' },
    { login: 'nagareadvaytechy', avatar_url: 'https://avatars.githubusercontent.com/u/356872496?v=4' },
    { login: 'hrb250144', avatar_url: 'https://avatars.githubusercontent.com/u/357685482?v=4' },
    { login: 'vishal210208-dev', avatar_url: 'https://avatars.githubusercontent.com/u/358105183?v=4' },
    { login: 'gtaviralclips52-lab', avatar_url: 'https://avatars.githubusercontent.com/u/358249790?v=4' },
    { login: 'masonswastaken', avatar_url: 'https://avatars.githubusercontent.com/u/359323372?v=4' },
    { login: 'g8z45py5zg-gif', avatar_url: 'https://avatars.githubusercontent.com/u/359429509?v=4' },
    { login: 'arfins218-beep', avatar_url: 'https://avatars.githubusercontent.com/u/359631906?v=4' },
    { login: 'tilakmaya033-ai', avatar_url: 'https://avatars.githubusercontent.com/u/359946384?v=4' },
    { login: 'akshaytechuniverse-coder', avatar_url: 'https://avatars.githubusercontent.com/u/359972180?v=4' },
    { login: 'lucifer987621-collab', avatar_url: 'https://avatars.githubusercontent.com/u/360014568?v=4' }
  ];

  function initStarfieldCanvas(canvasId, starCount = 140) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    let animId = null;
    let running = true;
    let width = 0;
    let height = 0;

    function resize() {
      const parent = canvas.parentElement;
      width = parent ? parent.clientWidth : window.innerWidth;
      height = parent ? parent.clientHeight : window.innerHeight;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    const stars = [];
    for (let i = 0; i < starCount; i++) {
      stars.push({
        x: Math.random() * (width || 800),
        y: Math.random() * (height || 600),
        r: Math.random() * 1.5 + 0.5,
        alpha: Math.random() * 0.7 + 0.2,
        twinkleSpeed: Math.random() * 0.03 + 0.008,
        twinklePhase: Math.random() * Math.PI * 2,
        vx: (Math.random() - 0.5) * 0.08,
        vy: (Math.random() - 0.5) * 0.08
      });
    }

    function draw(now) {
      if (!running) return;
      ctx.clearRect(0, 0, width, height);

      const time = now * 0.001;
      for (let i = 0; i < stars.length; i++) {
        const s = stars[i];
        s.x += s.vx;
        s.y += s.vy;
        if (s.x < 0) s.x = width;
        if (s.x > width) s.x = 0;
        if (s.y < 0) s.y = height;
        if (s.y > height) s.y = 0;

        const currentAlpha = Math.max(0.12, Math.min(1.0, s.alpha + Math.sin(time * s.twinkleSpeed * 60 + s.twinklePhase) * 0.35));
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${currentAlpha.toFixed(3)})`;
        ctx.shadowColor = '#ffffff';
        ctx.shadowBlur = s.r > 1.2 ? 4 : 0;
        ctx.fill();
      }

      animId = requestAnimationFrame(draw);
    }
    animId = requestAnimationFrame(draw);

    const onResize = () => resize();
    window.addEventListener('resize', onResize);

    return function cleanup() {
      running = false;
      if (animId) cancelAnimationFrame(animId);
      window.removeEventListener('resize', onResize);
    };
  }

  function initSupportModal() {
    if (supportModalOverlayEl) return;

    supportModalOverlayEl = document.createElement('div');
    supportModalOverlayEl.id = 'supportModalOverlay';
    supportModalOverlayEl.className = 'support-modal-overlay galaxy-overlay';
    supportModalOverlayEl.innerHTML = `
      <!-- Expansive Black & White Floating Supporters Galaxy Window -->
      <div class="galaxy-modal-container" id="supportMainCard">
        <button type="button" class="galaxy-modal-close" aria-label="Close modal">&times;</button>
        
        <!-- White Twinkling Dots Background Canvas -->
        <canvas id="galaxyStarsCanvas" class="galaxy-stars-canvas"></canvas>
        
        <!-- Floating Live Verified Stargazers Orbit Layer -->
        <div class="galaxy-orbit-field" id="stargazersField">
          <!-- Populated by physics loop -->
        </div>

        <!-- Center Floating Glass Island / HUD -->
        <div class="galaxy-center-hud" id="galaxyCenterHud">
          <div class="galaxy-hud-sparkle">✦ ✦ ✦</div>
          <h2 class="galaxy-hud-title">star and follow to be here</h2>
          <div class="galaxy-hud-callout">★ <b>Star</b> the repository and <b>Follow</b> @sherlock-dev-ai to have your username floating around here in live orbit!</div>
          <p class="galaxy-hud-sub">Starring and following would help a lot since I spent weeks making Clipify AI completely free, private & open-source for everyone! Your support keeps continuous free updates coming.</p>
          
          <div class="galaxy-hud-actions">
            <a class="galaxy-btn-star" href="https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE" target="_blank" rel="noopener noreferrer">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>
              </svg>
              <span>★ Star the Repository ★</span>
            </a>
            <a class="galaxy-btn-follow" href="https://github.com/sherlock-dev-ai" target="_blank" rel="noopener noreferrer">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
              </svg>
              <span>Follow @sherlock-dev-ai</span>
            </a>
            <button type="button" class="galaxy-btn-promoters" id="btnOpenPromotersFromSupport">
              <span>Promoters Highlighted (Spotlight) →</span>
            </button>
          </div>

          <div class="galaxy-hud-footer">
            <span class="galaxy-live-dot">●</span> <span id="galaxyStargazerCountText">34 Real Supporters in Orbit</span>
            <button type="button" class="galaxy-btn-refresh" id="btnRefreshSupporters" title="Refresh live supporters in orbit">
              <svg id="galaxyRefreshIcon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
              </svg>
              <span>Reload</span>
            </button>
          </div>
        </div>
      </div>
    `;

    supportModalOverlayEl.querySelector('.galaxy-modal-close')?.addEventListener('click', closeSupportModal);
    supportModalOverlayEl.querySelector('#btnOpenPromotersFromSupport')?.addEventListener('click', () => {
      closeSupportModal();
      setTimeout(showPromotersModal, 120);
    });

    supportModalOverlayEl.querySelector('#btnRefreshSupporters')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const btn = supportModalOverlayEl.querySelector('#btnRefreshSupporters');
      const icon = supportModalOverlayEl.querySelector('#galaxyRefreshIcon');
      if (icon) icon.style.animation = 'galaxySpin 0.75s linear infinite';
      if (btn) btn.disabled = true;
      try {
        await loadAndRenderStargazers(true);
      } finally {
        setTimeout(() => {
          if (icon) icon.style.animation = 'none';
          if (btn) btn.disabled = false;
        }, 650);
      }
    });

    supportModalOverlayEl.addEventListener('click', (e) => {
      if (e.target === supportModalOverlayEl) {
        closeSupportModal();
      }
    });

    supportModalOverlayEl.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
          e.preventDefault();
          window.AndroidBridge.openBrowser(link.href);
        }
      });
    });

    document.body.appendChild(supportModalOverlayEl);
  }

  function showMainSupportView() {
    loadAndRenderStargazers();
  }

  async function loadAndRenderStargazers(forceFetch = false) {
    const field = document.getElementById('stargazersField');
    if (!field) return;
    field.innerHTML = '';

    if (forceFetch && navigator.onLine) {
      try {
        const res = await fetch('https://api.github.com/repos/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/stargazers?per_page=100', {
          headers: { 'Accept': 'application/vnd.github.v3+json' },
          cache: 'no-store'
        });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            REAL_STARGAZERS = data.map(u => ({ login: u.login, avatar_url: u.avatar_url }));
          }
        }
      } catch (err) {
        console.log('[Galaxy] Offline fallback preserved for supporters', err);
      }
    }

    // Always use real verified GitHub community creators
    let items = REAL_STARGAZERS;

    const countText = document.getElementById('galaxyStargazerCountText');
    if (countText) countText.textContent = `${items.length} Real Supporters in Orbit`;

    supportersList = [];
    const container = document.getElementById('supportMainCard');
    const fW = Math.max(480, (container && container.clientWidth) || field.clientWidth || 980);
    const fH = Math.max(380, (container && container.clientHeight) || field.clientHeight || 640);

    // Center HUD exclusion zone coordinates so pills orbit around the island
    const hudW = 440;
    const hudH = 340;
    const hudX1 = (fW - hudW) / 2 - 20;
    const hudY1 = (fH - hudH) / 2 - 20;
    const hudX2 = (fW + hudW) / 2 + 20;
    const hudY2 = (fH + hudH) / 2 + 20;

    items.forEach((user, idx) => {
      const pill = document.createElement('a');
      pill.className = 'galaxy-stargazer-pill';
      pill.href = `https://github.com/${encodeURIComponent(user.login)}`;
      pill.target = '_blank';
      pill.rel = 'noopener noreferrer';
      pill.title = `Open GitHub profile: https://github.com/${user.login}`;
      pill.innerHTML = `
        <img class="galaxy-pill-avatar" src="${user.avatar_url}" alt="${user.login}" onerror="this.src='https://github.com/github.png'">
        <span class="galaxy-pill-name">@${user.login}</span>
        <span class="galaxy-pill-star">★</span>
      `;

      field.appendChild(pill);

      const pW = 150;
      const pH = 36;

      // Spawn in outer regions avoiding the center HUD island with safe padding from rounded corners
      let x, y;
      let attempts = 0;
      const cornerPad = 32;
      do {
        x = Math.max(cornerPad, Math.min(fW - pW - cornerPad, Math.random() * (fW - pW)));
        y = Math.max(cornerPad, Math.min(fH - pH - cornerPad, Math.random() * (fH - pH)));
        attempts++;
      } while (attempts < 20 && x > hudX1 && x < hudX2 && y > hudY1 && y < hudY2);

      const angle = Math.random() * Math.PI * 2;
      const speed = 0.35 + Math.random() * 0.45;
      const vx = Math.cos(angle) * speed;
      const vy = Math.sin(angle) * speed;

      supportersList.push({
        el: pill,
        x,
        y,
        vx,
        vy,
        w: pW,
        h: pH,
        phase: Math.random() * Math.PI * 2,
        isHovered: false
      });

      pill.addEventListener('mouseenter', () => {
        supportersList[idx].isHovered = true;
      });
      pill.addEventListener('mouseleave', () => {
        supportersList[idx].isHovered = false;
      });
      pill.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
          e.preventDefault();
          window.AndroidBridge.openBrowser(pill.href);
        }
      });
    });

    startSupportersPhysics(fW, fH);
  }

  function startSupportersPhysics(fieldWidth, fieldHeight) {
    stopSupportersPhysics();
    supportersPhysicsActive = true;
    let lastTime = performance.now();

    function step(now) {
      if (!supportersPhysicsActive) return;
      const dt = Math.min(0.04, (now - lastTime) / 1000);
      lastTime = now;
      const t = now * 0.0012;

      const container = document.getElementById('supportMainCard');
      const curW = (container && container.clientWidth) || fieldWidth;
      const curH = (container && container.clientHeight) || fieldHeight;

      // HUD center exclusion bounds
      const hudW = 420;
      const hudH = 320;
      const cX = curW / 2;
      const cY = curH / 2;
      const minRadiusX = hudW / 2 + 15;
      const minRadiusY = hudH / 2 + 15;

      supportersList.forEach(item => {
        if (item.isHovered) return;

        // Smooth harmonic wave addition for floating feeling
        const harmonicX = Math.sin(t + item.phase) * 10 * dt;
        const harmonicY = Math.cos(t * 1.1 + item.phase) * 10 * dt;

        item.x += item.vx * 60 * dt + harmonicX;
        item.y += item.vy * 60 * dt + harmonicY;

        // Repulsive gentle deflect from center HUD island
        const dx = (item.x + item.w / 2) - cX;
        const dy = (item.y + item.h / 2) - cY;
        if (Math.abs(dx) < minRadiusX && Math.abs(dy) < minRadiusY) {
          if (Math.abs(dx) / minRadiusX > Math.abs(dy) / minRadiusY) {
            item.vx = dx > 0 ? Math.abs(item.vx) : -Math.abs(item.vx);
          } else {
            item.vy = dy > 0 ? Math.abs(item.vy) : -Math.abs(item.vy);
          }
        }

        // Corner avoidance: gently redirect away from the 4 rounded modal corners (radius 24px)
        const cornerZone = 38;
        if (item.x < cornerZone && item.y < cornerZone) {
          item.vx = Math.abs(item.vx) || 0.35;
          item.vy = Math.abs(item.vy) || 0.35;
        } else if (item.x + item.w > curW - cornerZone && item.y < cornerZone) {
          item.vx = -Math.abs(item.vx) || -0.35;
          item.vy = Math.abs(item.vy) || 0.35;
        } else if (item.x < cornerZone && item.y + item.h > curH - cornerZone) {
          item.vx = Math.abs(item.vx) || 0.35;
          item.vy = -Math.abs(item.vy) || -0.35;
        } else if (item.x + item.w > curW - cornerZone && item.y + item.h > curH - cornerZone) {
          item.vx = -Math.abs(item.vx) || -0.35;
          item.vy = -Math.abs(item.vy) || -0.35;
        }

        // Bounce off galaxy walls with 20px safe gutter
        const wallPad = 20;
        if (item.x <= wallPad) {
          item.x = wallPad;
          item.vx = Math.abs(item.vx);
        } else if (item.x + item.w >= curW - wallPad) {
          item.x = curW - item.w - wallPad;
          item.vx = -Math.abs(item.vx);
        }

        if (item.y <= wallPad) {
          item.y = wallPad;
          item.vy = Math.abs(item.vy);
        } else if (item.y + item.h >= curH - wallPad) {
          item.y = curH - item.h - wallPad;
          item.vy = -Math.abs(item.vy);
        }

        item.el.style.transform = `translate3d(${item.x.toFixed(1)}px, ${item.y.toFixed(1)}px, 0)`;
      });

      supportersAnimId = requestAnimationFrame(step);
    }

    supportersAnimId = requestAnimationFrame(step);
  }

  function stopSupportersPhysics() {
    supportersPhysicsActive = false;
    if (supportersAnimId) {
      cancelAnimationFrame(supportersAnimId);
      supportersAnimId = null;
    }
  }

  function mountOrShowInlineSection(sectionId, navId, overlayEl) {
    const mainEl = document.querySelector('main.main');
    if (!mainEl) return false;
    let sec = document.getElementById(sectionId);
    if (!sec) {
      sec = document.createElement('section');
      sec.id = sectionId;
      sec.className = 'page-section secondary-section inline-bw-section';
      const footerEl = mainEl.querySelector('footer');
      if (footerEl) mainEl.insertBefore(sec, footerEl);
      else mainEl.appendChild(sec);
    }
    if (overlayEl && overlayEl.parentElement !== sec) {
      sec.appendChild(overlayEl);
    }
    document.querySelectorAll('.page-section').forEach(s => {
      s.classList.remove('visible');
      s.style.display = 'none';
    });
    sec.classList.add('visible');
    sec.style.display = 'block';
    document.querySelectorAll('.sidebar nav a').forEach(a => a.classList.remove('active'));
    const navEl = document.getElementById(navId);
    if (navEl) navEl.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return true;
  }

  function showSupportModal() {
    initSupportModal();
    if (!mountOrShowInlineSection('support', 'navSupportLink', supportModalOverlayEl)) {
      supportModalOverlayEl.style.display = 'flex';
      supportModalOverlayEl.classList.add('active');
    } else {
      supportModalOverlayEl.style.display = 'block';
      supportModalOverlayEl.classList.add('active');
    }
    if (galaxyStarsCleanup) galaxyStarsCleanup();
    galaxyStarsCleanup = initStarfieldCanvas('galaxyStarsCanvas', 140);
    loadAndRenderStargazers();
  }

  function closeSupportModal() {
    if (!supportModalOverlayEl) return;
    stopSupportersPhysics();
    if (galaxyStarsCleanup) {
      galaxyStarsCleanup();
      galaxyStarsCleanup = null;
    }
    supportModalOverlayEl.classList.remove('active');
    setTimeout(() => {
      supportModalOverlayEl.style.display = 'none';
    }, 280);
  }

  // ==========================================
  // PROMOTERS HIGHLIGHTED MODAL (Black & White Creator Spotlight)
  // ==========================================
  let promotersModalOverlayEl = null;

  function initPromotersModal() {
    if (promotersModalOverlayEl) return;

    promotersModalOverlayEl = document.createElement('div');
    promotersModalOverlayEl.id = 'promotersModalOverlay';
    promotersModalOverlayEl.className = 'promoters-modal-overlay galaxy-overlay';
    promotersModalOverlayEl.innerHTML = `
      <div class="promoters-bw-container" id="promotersBwCard">
        <button type="button" class="galaxy-modal-close" id="btnPromotersClose" aria-label="Close modal">&times;</button>
        
        <!-- White Twinkling Dots Background Canvas -->
        <canvas id="promotersStarsCanvas" class="galaxy-stars-canvas"></canvas>

        <div class="promoters-content-layer">
          <!-- Top Callout Banner with exact user required phrase -->
          <div class="promoter-bw-callout">
            <span class="promoter-bw-tag">★ CREATOR SPOTLIGHT</span>
            <h3 class="promoter-bw-title">make reels/videos about clipify to get your social highlighed here</h3>
            <p class="promoter-bw-desc">Create an Instagram Reel, TikTok, or YouTube Short showcasing Clipify AI in action. Tag <b>@sherlock.fy</b> or use <b>#ClipifyAI</b> to get your channel, social handle, and videos permanently pinned on this wall!</p>
          </div>

          <!-- Empty Showcase List State in Sleek Monochrome -->
          <div class="promoter-bw-empty-card">
            <div class="promoter-bw-empty-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect>
                <line x1="7" y1="2" x2="7" y2="22"></line>
                <line x1="17" y1="2" x2="17" y2="22"></line>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <line x1="2" y1="7" x2="7" y2="7"></line>
                <line x1="2" y1="17" x2="7" y2="17"></line>
                <line x1="17" y1="17" x2="22" y2="17"></line>
                <line x1="17" y1="7" x2="22" y2="7"></line>
              </svg>
            </div>
            <h4>No Creator Videos Pinned Yet</h4>
            <p>Be the very first creator highlighted on the main spotlight wall! Publish your Clipify tutorial, review, or workflow and submit below to get pinned.</p>
          </div>

          <!-- Action Buttons in Strict Black & White -->
          <div class="promoter-bw-actions">
            <a class="promoter-bw-btn-submit" href="https://ig.me/j/AQj1lYCWh_iV_S7J/" target="_blank" rel="noopener noreferrer">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
              <span>Submit Your Reel / Tag Us 📢</span>
            </a>
            <a class="promoter-bw-btn-social" href="https://www.instagram.com/sherlock.fy" target="_blank" rel="noopener noreferrer">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/>
              </svg>
              <span>Follow @sherlock.fy on Instagram</span>
            </a>
          </div>

          <div class="promoter-bw-footer">
            <button type="button" class="promoter-bw-dismiss" id="btnPromotersDismiss">Back to Clipify AI</button>
          </div>
        </div>
      </div>
    `;

    promotersModalOverlayEl.querySelector('#btnPromotersClose')?.addEventListener('click', closePromotersModal);
    promotersModalOverlayEl.querySelector('#btnPromotersDismiss')?.addEventListener('click', closePromotersModal);

    promotersModalOverlayEl.addEventListener('click', (e) => {
      if (e.target === promotersModalOverlayEl) {
        closePromotersModal();
      }
    });

    promotersModalOverlayEl.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', (e) => {
        if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
          e.preventDefault();
          window.AndroidBridge.openBrowser(link.href);
        }
      });
    });

    document.body.appendChild(promotersModalOverlayEl);
  }

  function showPromotersModal() {
    initPromotersModal();
    if (!mountOrShowInlineSection('promoters', 'navPromotersLink', promotersModalOverlayEl)) {
      promotersModalOverlayEl.style.display = 'flex';
      promotersModalOverlayEl.classList.add('active');
    } else {
      promotersModalOverlayEl.style.display = 'block';
      promotersModalOverlayEl.classList.add('active');
    }
    if (promotersStarsCleanup) promotersStarsCleanup();
    promotersStarsCleanup = initStarfieldCanvas('promotersStarsCanvas', 100);
  }

  function closePromotersModal() {
    if (!promotersModalOverlayEl) return;
    if (promotersStarsCleanup) {
      promotersStarsCleanup();
      promotersStarsCleanup = null;
    }
    promotersModalOverlayEl.classList.remove('active');
    setTimeout(() => {
      promotersModalOverlayEl.style.display = 'none';
    }, 280);
  }

  
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
    if (!mountOrShowInlineSection('campaigns', 'navCampaignsLink', campaignsModalOverlayEl)) {
      campaignsModalOverlayEl.style.display = 'flex';
      campaignsModalOverlayEl.classList.add('active');
    } else {
      campaignsModalOverlayEl.style.display = 'block';
      campaignsModalOverlayEl.classList.add('active');
    }
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

  function bindNavLinks() {
    document.querySelectorAll('#navGuideLink').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        startTour(true);
      });
    });

    document.querySelectorAll('#navSupportLink').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        showSupportModal();
      });
    });

    document.querySelectorAll('#navCampaignsLink').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        showCampaignsModal();
      });
    });

    document.querySelectorAll('#navPromotersLink').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        showPromotersModal();
      });
    });

    function handleHash() {
      const h = window.location.hash.toLowerCase();
      if (h === '#support') {
        showSupportModal();
      } else if (h === '#promoters') {
        showPromotersModal();
      } else if (h === '#campaigns') {
        showCampaignsModal();
      } else if (h === '#guide') {
        setTimeout(() => startTour(true), 120);
      }
    }
    window.addEventListener('hashchange', handleHash);
    window.addEventListener('load', handleHash);
    handleHash();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindNavLinks);
  } else {
    bindNavLinks();
  }

  window.startClipifyTour = function (arg1, arg2) {
    const ctx = typeof arg1 === 'string' ? arg1 : (typeof arg2 === 'string' ? arg2 : null);
    startTour(true, ctx);
  };
  window.showSupportModal = () => showSupportModal();
  window.showPromotersModal = () => showPromotersModal();
  window.showCampaignsModal = () => showCampaignsModal();
})();
