package dev.sherlock.clipifyai

import android.annotation.SuppressLint
import android.app.ActivityManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.speech.tts.TextToSpeech
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import dev.sherlock.clipifyai.databinding.ActivityMainBinding
import dev.sherlock.clipifyai.media.AndroidMediaProcessor
import dev.sherlock.clipifyai.media.MobileLiveManager
import dev.sherlock.clipifyai.media.ProjectManager
import dev.sherlock.clipifyai.network.DesktopSyncClient
import dev.sherlock.clipifyai.network.MobileTrendingFetcher
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader
import dev.sherlock.clipifyai.onboarding.OnboardingActivity
import dev.sherlock.clipifyai.service.RenderForegroundService
import dev.sherlock.clipifyai.service.RenderState
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "ClipifyMainActivity"
    }

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: SharedPreferences
    private lateinit var projectManager: ProjectManager
    private lateinit var mediaProcessor: AndroidMediaProcessor
    private lateinit var liveManager: MobileLiveManager
    private lateinit var syncClient: DesktopSyncClient
    private val apiExecutor = Executors.newCachedThreadPool()
    private var tts: TextToSpeech? = null
    private var mCurrentVideoUri: Uri? = null

    private val commandReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            handleCustomIntent(intent)
        }
    }

    private val selectVideoLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            mCurrentVideoUri = it
            handleSelectedVideo(it)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        prefs = getSharedPreferences("clipify_prefs", Context.MODE_PRIVATE)
        val skipOnboarding = intent.getBooleanExtra("skip_onboarding", false)
        val onboardingComplete = prefs.getBoolean("onboarding_complete", false) || skipOnboarding
        if (!onboardingComplete) {
            startActivity(Intent(this, OnboardingActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        projectManager = ProjectManager(this)
        mediaProcessor = AndroidMediaProcessor(this)
        liveManager = MobileLiveManager(this)
        val desktopHost = prefs.getString("desktop_ip", "http://127.0.0.1:5000") ?: "http://127.0.0.1:5000"
        syncClient = DesktopSyncClient(desktopHost)

        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.US
            }
        }

        setupWebView()
        setupNavigation()
        setupHeaderListeners()
        setupRenderListener()
        loadInitialPage()
        handleCustomIntent(intent)

        val filter = IntentFilter("dev.sherlock.clipifyai.ACTION_CMD")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(commandReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(commandReceiver, filter)
        }
    }

    private fun handleCustomIntent(intent: Intent?) {
        val evalB64 = intent?.getStringExtra("eval_b64")
        val rawJs = intent?.getStringExtra("eval_js")
        val jsToEval = when {
            !evalB64.isNullOrBlank() -> {
                try {
                    String(android.util.Base64.decode(evalB64, android.util.Base64.DEFAULT), Charsets.UTF_8)
                } catch (e: Exception) {
                    null
                }
            }
            !rawJs.isNullOrBlank() -> rawJs
            else -> null
        }

        if (!jsToEval.isNullOrBlank()) {
            runOnUiThread {
                binding.webView.evaluateJavascript(jsToEval) { res ->
                    Log.i(TAG, "evaluateJavascript returned: $res")
                }
            }
        }

        val tab = intent?.getStringExtra("tab")
        if (!tab.isNullOrBlank()) {
            runOnUiThread {
                if (tab == "more") {
                    binding.webView.evaluateJavascript("if (typeof window.toggleMobileMoreDrawer === 'function') window.toggleMobileMoreDrawer();", null)
                } else {
                    binding.webView.evaluateJavascript("if (typeof navigateTo === 'function') navigateTo('$tab');", null)
                }
            }
        }

        val selectVideoPath = intent?.getStringExtra("select_video_path")
        if (!selectVideoPath.isNullOrBlank()) {
            try {
                val rawSrc = File(selectVideoPath)
                val extFiles = getExternalFilesDir(null)
                val src = when {
                    rawSrc.exists() && rawSrc.canRead() -> rawSrc
                    File(extFiles, rawSrc.name).exists() -> File(extFiles, rawSrc.name)
                    File(extFiles, "user_selected_video.mp4").exists() -> File(extFiles, "user_selected_video.mp4")
                    else -> rawSrc
                }
                if (src.exists() && src.length() > 0) {
                    val destFile = File(filesDir, "user_selected_video.mp4")
                    src.copyTo(destFile, overwrite = true)
                    mCurrentVideoUri = Uri.fromFile(destFile)
                    val pathClean = destFile.absolutePath.replace("\\", "/")
                    val jsCall = "if (window.onAndroidVideoSelected) window.onAndroidVideoSelected('$pathClean', '${src.name.replace("'", "\\'")}', 0);"
                    runOnUiThread {
                        binding.webView.evaluateJavascript(jsCall, null)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error handling select_video_path intent", e)
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        WebView.setWebContentsDebuggingEnabled(true)
        binding.webView.setBackgroundColor(android.graphics.Color.parseColor("#000000"))
        binding.webView.setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)
        binding.webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            allowFileAccessFromFileURLs = true
            allowUniversalAccessFromFileURLs = true
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            useWideViewPort = false
            loadWithOverviewMode = false
            setSupportZoom(false)
            displayZoomControls = false
            mediaPlaybackRequiresUserGesture = false
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        }

        binding.webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress < 100) {
                    binding.webProgress.visibility = android.view.View.VISIBLE
                    binding.webProgress.progress = newProgress
                } else {
                    binding.webProgress.visibility = android.view.View.GONE
                }
            }

            override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage?): Boolean {
                if (consoleMessage != null) {
                    Log.d("ClipifyWebConsole", "[${consoleMessage.messageLevel()}] ${consoleMessage.message()} (${consoleMessage.sourceId()}:${consoleMessage.lineNumber()})")
                }
                return super.onConsoleMessage(consoleMessage)
            }
        }

        binding.webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: return false
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    if (url.contains("github.com") || url.contains("youtube.com") || url.contains("twitch.tv") || url.contains("kick.com")) {
                        openExternalUrl(url)
                        return true
                    }
                }
                return false
            }
        }

        binding.webView.addJavascriptInterface(ClipifyAndroidBridge(), "AndroidBridge")
    }

    private fun setupRenderListener() {
        RenderState.listener = { progress, stage, outputPath ->
            runOnUiThread {
                val outJson = JSONObject.quote(outputPath?.replace("\\", "/") ?: "")
                val stageQ = JSONObject.quote(stage)
                val metaQ = JSONObject.quote(RenderState.lastMetadataJson)
                val outsQ = JSONObject.quote(RenderState.lastOutputsJson)
                val js = "if (window.onMobileRenderProgress) window.onMobileRenderProgress($progress, $stageQ, $outJson, $metaQ, $outsQ);"
                binding.webView.evaluateJavascript(js, null)
            }
        }
    }

    private fun loadInitialPage() {
        val target = intent.getStringExtra("target_url")
        if (!target.isNullOrEmpty()) {
            binding.webView.loadUrl(target)
        } else {
            binding.webView.loadUrl("file:///android_asset/www/index.html")
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleCustomIntent(intent)
        val target = intent?.getStringExtra("target_url")
        if (!target.isNullOrEmpty()) {
            binding.webView.loadUrl(target)
        }
        if (intent?.getBooleanExtra("trigger_render", false) == true) {
            val uri = intent.getStringExtra("render_uri") ?: ""
            val dur = intent.getIntExtra("render_dur", 15)
            ClipifyAndroidBridge().startRender(uri, dur, "center", true)
        }
    }

    private fun setupHeaderListeners() {
        binding.btnHeaderUpdate.setOnClickListener {
            binding.webView.evaluateJavascript(
                "(function(){ if (typeof window.openClipifyUpdate === 'function') { window.openClipifyUpdate(); } else { window.location.href = 'index.html#update'; } })();",
                null
            )
        }
        binding.btnHeaderGithub.setOnClickListener {
            openExternalUrl("https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE")
        }
        binding.btnHeaderTour.setOnClickListener {
            binding.webView.evaluateJavascript(
                "(function(){ if (typeof window.ClipifyToggleClippy === 'function') { window.ClipifyToggleClippy(); } else { var btn = document.getElementById('clippyToggleBtn'); if (btn) btn.click(); } })();",
                null
            )
        }
    }

    private fun setupNavigation() {
        val tabs = listOf(
            binding.navTabCreate to "create",
            binding.navTabInstant to "instant",
            binding.navTabTrending to "trending",
            binding.navTabEditor to "editor",
            binding.navTabLive to "live",
            binding.navTabNarrate to "narrate",
            binding.navTabProjects to "projects",
            binding.navTabBeta to "beta",
            binding.navTabMore to "more"
        )

        fun selectTabUi(activeView: android.view.View) {
            val activeColor = android.graphics.Color.parseColor("#FFFFFF")
            val mutedColor = android.graphics.Color.parseColor("#71717A")
            val activeBg = android.graphics.Color.parseColor("#18181B")
            for ((v, _) in tabs) {
                val isSelected = v == activeView
                v.setBackgroundColor(if (isSelected) activeBg else android.graphics.Color.TRANSPARENT)
                if (v is android.view.ViewGroup && v.childCount >= 2) {
                    val icon = v.getChildAt(0) as? android.widget.ImageView
                    val label = v.getChildAt(1) as? android.widget.TextView
                    icon?.setColorFilter(if (isSelected) activeColor else mutedColor)
                    label?.setTextColor(if (isSelected) activeColor else mutedColor)
                    label?.setTypeface(null, if (isSelected) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
                }
            }
            binding.bottomNavScroll.post {
                val scrollX = (activeView.left - (binding.bottomNavScroll.width - activeView.width) / 2).coerceAtLeast(0)
                binding.bottomNavScroll.smoothScrollTo(scrollX, 0)
            }
        }

        for ((tabView, target) in tabs) {
            tabView.setOnClickListener {
                selectTabUi(tabView)
                when (target) {
                    "live" -> binding.webView.evaluateJavascript("if (typeof window.closeMobileMoreDrawer === 'function') window.closeMobileMoreDrawer(); window.location.href = 'live.html';", null)
                    "narrate" -> binding.webView.evaluateJavascript("if (typeof window.closeMobileMoreDrawer === 'function') window.closeMobileMoreDrawer(); window.location.href = 'narrate.html';", null)
                    "more" -> binding.webView.evaluateJavascript("if (typeof window.toggleMobileMoreDrawer === 'function') window.toggleMobileMoreDrawer();", null)
                    else -> binding.webView.evaluateJavascript("if (typeof window.closeMobileMoreDrawer === 'function') window.closeMobileMoreDrawer(); if (typeof navigateTo === 'function') navigateTo('$target'); else window.location.href = 'index.html#$target';", null)
                }
            }
        }
    }

    private fun handleSelectedVideo(videoUri: Uri) {
        val fileName = getFileNameFromUri(videoUri)
        Toast.makeText(this, "Importing: $fileName...", Toast.LENGTH_SHORT).show()

        Thread {
            try {
                val destFile = File(filesDir, "user_selected_video.mp4")
                contentResolver.openInputStream(videoUri)?.use { input ->
                    destFile.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
                mCurrentVideoUri = Uri.fromFile(destFile)

                runOnUiThread {
                    Toast.makeText(this, "✓ Ready: $fileName", Toast.LENGTH_SHORT).show()
                    val pathClean = destFile.absolutePath.replace("\\", "/")
                    val jsCall = "if (window.onAndroidVideoSelected) window.onAndroidVideoSelected('$pathClean', '${fileName.replace("'", "\\'")}', 0);"
                    binding.webView.evaluateJavascript(jsCall, null)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Could not import video: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun getFileNameFromUri(uri: Uri): String {
        var name = "imported_video.mp4"
        try {
            contentResolver.query(uri, arrayOf(android.provider.MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idx = cursor.getColumnIndex(android.provider.MediaStore.MediaColumns.DISPLAY_NAME)
                    if (idx >= 0) {
                        name = cursor.getString(idx) ?: name
                    }
                }
            }
        } catch (_: Exception) {
            name = uri.lastPathSegment?.substringAfterLast('/') ?: name
        }
        return name
    }

    private fun openExternalUrl(url: String) {
        try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(this, "Could not open browser", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onDestroy() {
        try { unregisterReceiver(commandReceiver) } catch (_: Exception) {}
        try { apiExecutor.shutdownNow() } catch (_: Exception) {}
        RenderState.listener = null
        tts?.stop()
        tts?.shutdown()
        super.onDestroy()
    }

    inner class ClipifyAndroidBridge {
        @JavascriptInterface
        fun getDeviceInfoJson(): String {
            return try {
                val manufacturer = Build.MANUFACTURER.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.US) else it.toString() }
                val model = Build.MODEL
                val brand = Build.BRAND.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.US) else it.toString() }
                val deviceName = if (model.startsWith(manufacturer, ignoreCase = true)) {
                    model
                } else if (model.startsWith(brand, ignoreCase = true)) {
                    model
                } else {
                    "$brand $model"
                }

                val arch = if (Build.SUPPORTED_ABIS.isNotEmpty()) Build.SUPPORTED_ABIS[0] else "arm64-v8a"

                val actManager = getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
                val memInfo = ActivityManager.MemoryInfo()
                actManager?.getMemoryInfo(memInfo)
                val totalRamGb = String.format(Locale.US, "%.1f", memInfo.totalMem.toDouble() / (1024 * 1024 * 1024))
                val androidVer = "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})"

                val obj = JSONObject()
                obj.put("deviceName", deviceName)
                obj.put("model", model)
                obj.put("manufacturer", manufacturer)
                obj.put("brand", brand)
                obj.put("arch", arch)
                obj.put("totalRamGb", totalRamGb)
                obj.put("androidVer", androidVer)
                obj.toString()
            } catch (e: Exception) {
                "{}"
            }
        }

        @JavascriptInterface
        fun callApi(method: String, endpoint: String, body: String?, headers: String?): String {
            return syncClient.executeApiCall(method, endpoint, body, headers)
        }

        @JavascriptInterface
        fun callApiAsync(requestId: String, method: String, endpoint: String, body: String?, headers: String?) {
            apiExecutor.execute {
                var resJson = try {
                    syncClient.executeApiCall(method, endpoint, body, headers)
                } catch (e: Exception) {
                    JSONObject().apply {
                        put("ok", false)
                        put("status", 503)
                        put("error", e.message ?: "Bridge error")
                    }.toString()
                }
                // If PC server is offline, handle standalone mobile endpoints on-device
                try {
                    val parsed = JSONObject(resJson)
                    if (parsed.optInt("status", 503) == 503) {
                        if (endpoint.startsWith("/api/trending/")) {
                            val pathPart = endpoint.substringAfter("/api/trending/").substringBefore("?")
                            val queryParam = if (endpoint.contains("q=")) {
                                java.net.URLDecoder.decode(endpoint.substringAfter("q=").substringBefore("&"), "UTF-8")
                            } else ""
                            val trendingBody = MobileTrendingFetcher.fetchTrending(pathPart, queryParam)
                            resJson = JSONObject().apply {
                                put("ok", true)
                                put("status", 200)
                                put("body", trendingBody)
                            }.toString()
                        } else if (endpoint == "/api/models/config" || endpoint.startsWith("/api/models/config?")) {
                            if (method.equals("POST", ignoreCase = true)) {
                                val reqJson = try { JSONObject(body ?: "{}") } catch (_: Exception) { JSONObject() }
                                val editor = prefs.edit()
                                val prov = reqJson.optString("provider", "")
                                if (prov in listOf("ollama", "huggingface", "heuristic", "mediacodec")) {
                                    editor.putString("ai_provider", prov)
                                }
                                val tok = reqJson.optString("hf_token", "").trim()
                                if (tok.isNotEmpty() && !tok.startsWith("hf_...")) {
                                    editor.putString("hf_token", tok)
                                }
                                val hfModel = reqJson.optString("hf_model", "").trim()
                                if (hfModel.isNotEmpty()) {
                                    editor.putString("hf_model", hfModel)
                                }
                                editor.apply()
                                val cfgObj = JSONObject().apply {
                                    put("provider", prefs.getString("ai_provider", "huggingface") ?: "huggingface")
                                    put("hf_token", prefs.getString("hf_token", "") ?: "")
                                    put("hf_model", prefs.getString("hf_model", "Qwen/Qwen2.5-7B-Instruct") ?: "Qwen/Qwen2.5-7B-Instruct")
                                }
                                val respBody = JSONObject().apply {
                                    put("ok", true)
                                    put("config", cfgObj)
                                }.toString()
                                resJson = JSONObject().apply {
                                    put("ok", true)
                                    put("status", 200)
                                    put("body", respBody)
                                }.toString()
                            } else {
                                val hfToken = prefs.getString("hf_token", "") ?: ""
                                val masked = when {
                                    hfToken.length > 8 -> "hf_...${hfToken.takeLast(4)}"
                                    hfToken.isNotEmpty() -> "hf_configured"
                                    else -> ""
                                }
                                val modelsArr = JSONArray().apply {
                                    put(JSONObject().apply {
                                        put("id", "Qwen/Qwen2.5-7B-Instruct")
                                        put("name", "Qwen 2.5 7B Instruct (Recommended - Fast & Free)")
                                        put("recommended", true)
                                    })
                                    put(JSONObject().apply {
                                        put("id", "meta-llama/Llama-3.2-3B-Instruct")
                                        put("name", "Meta Llama 3.2 3B Instruct (Ultra-Fast - Free)")
                                        put("recommended", false)
                                    })
                                    put(JSONObject().apply {
                                        put("id", "mistralai/Mistral-7B-Instruct-v0.3")
                                        put("name", "Mistral 7B Instruct v0.3 (Free)")
                                        put("recommended", false)
                                    })
                                    put(JSONObject().apply {
                                        put("id", "google/gemma-2-9b-it")
                                        put("name", "Google Gemma 2 9B IT (Free)")
                                        put("recommended", false)
                                    })
                                }
                                val respBody = JSONObject().apply {
                                    put("ok", true)
                                    put("provider", prefs.getString("ai_provider", "huggingface") ?: "huggingface")
                                    put("hf_token_configured", hfToken.isNotEmpty())
                                    put("hf_token_masked", masked)
                                    put("hf_model", prefs.getString("hf_model", "Qwen/Qwen2.5-7B-Instruct") ?: "Qwen/Qwen2.5-7B-Instruct")
                                    put("available_hf_models", modelsArr)
                                    put("ollama_models", JSONArray())
                                    put("default_ollama_model", "")
                                }.toString()
                                resJson = JSONObject().apply {
                                    put("ok", true)
                                    put("status", 200)
                                    put("body", respBody)
                                }.toString()
                            }
                        } else if (endpoint == "/api/models/huggingface/verify" || endpoint == "/api/models/verify-hf") {
                            val reqJson = try { JSONObject(body ?: "{}") } catch (_: Exception) { JSONObject() }
                            var token = (reqJson.optString("token", "").ifBlank {
                                reqJson.optString("hf_token", "").ifBlank { reqJson.optString("url", "") }
                            }).trim()
                            if (token.lowercase().contains("huggingface.co/settings/tokens") && !token.contains("hf_")) {
                                val errBody = JSONObject().apply {
                                    put("ok", false)
                                    put("error", "You pasted the settings page URL. Please copy an Access Token from that page (starts with hf_...) and paste it here.")
                                }.toString()
                                resJson = JSONObject().apply {
                                    put("ok", false)
                                    put("status", 400)
                                    put("body", errBody)
                                }.toString()
                            } else {
                                if (token.startsWith("Bearer ")) token = token.substring(7).trim()
                                token = token.trim('"', '\'', ' ', '\t', '\r', '\n')
                                val hfMatch = Regex("hf_[A-Za-z0-9]+").find(token)
                                if (hfMatch != null) token = hfMatch.value
                                if (token.isEmpty() || token.startsWith("hf_...")) {
                                    token = prefs.getString("hf_token", "") ?: ""
                                }
                                if (token.isEmpty()) {
                                    val errBody = JSONObject().apply {
                                        put("ok", false)
                                        put("error", "Please enter a valid Hugging Face token (starts with hf_).")
                                    }.toString()
                                    resJson = JSONObject().apply {
                                        put("ok", false)
                                        put("status", 400)
                                        put("body", errBody)
                                    }.toString()
                                } else {
                                    val client = okhttp3.OkHttpClient.Builder()
                                        .connectTimeout(12, java.util.concurrent.TimeUnit.SECONDS)
                                        .readTimeout(12, java.util.concurrent.TimeUnit.SECONDS)
                                        .build()
                                    val request = okhttp3.Request.Builder()
                                        .url("https://huggingface.co/api/whoami-v2")
                                        .header("Authorization", "Bearer $token")
                                        .header("User-Agent", "ClipifyAI/5.0.6")
                                        .get()
                                        .build()
                                    client.newCall(request).execute().use { resp ->
                                        val raw = resp.body?.string().orEmpty()
                                        if (resp.isSuccessful) {
                                            val data = try { JSONObject(raw) } catch (_: Exception) { JSONObject() }
                                            val userName = data.optString("name", "User")
                                            val userType = data.optString("type", "user")
                                            prefs.edit()
                                                .putString("hf_token", token)
                                                .putString("ai_provider", "huggingface")
                                                .apply()
                                            val okBody = JSONObject().apply {
                                                put("ok", true)
                                                put("name", userName)
                                                put("user", userName)
                                                put("type", userType)
                                                put("message", "Verified Hugging Face token for @$userName")
                                            }.toString()
                                            resJson = JSONObject().apply {
                                                put("ok", true)
                                                put("status", 200)
                                                put("body", okBody)
                                            }.toString()
                                        } else if (resp.code == 401) {
                                            val errBody = JSONObject().apply {
                                                put("ok", false)
                                                put("error", "Invalid Hugging Face token. Please check your token at huggingface.co/settings/tokens.")
                                            }.toString()
                                            resJson = JSONObject().apply {
                                                put("ok", false)
                                                put("status", 401)
                                                put("body", errBody)
                                            }.toString()
                                        } else {
                                            prefs.edit().putString("hf_token", token).apply()
                                            val okBody = JSONObject().apply {
                                                put("ok", true)
                                                put("name", "Cloud User")
                                                put("message", "Token saved (HF returned ${resp.code})")
                                            }.toString()
                                            resJson = JSONObject().apply {
                                                put("ok", true)
                                                put("status", 200)
                                                put("body", okBody)
                                            }.toString()
                                        }
                                    }
                                }
                            }
                        } else if (endpoint.startsWith("/api/live/")) {
                            val reqJson = try { JSONObject(body ?: "{}") } catch (_: Exception) { JSONObject() }
                            val respObj = when {
                                endpoint.contains("/api/live/connect") -> {
                                    liveManager.connect(
                                        reqJson.optString("source_url", ""),
                                        reqJson.optString("source_type", "youtube")
                                    )
                                }
                                endpoint.contains("/api/live/status") -> liveManager.getStatusJson()
                                endpoint.contains("/api/live/instant-clip") -> {
                                    liveManager.instantClip(
                                        reqJson.optInt("duration", 30),
                                        reqJson.optString("layout", "split"),
                                        reqJson.optBoolean("captions", true)
                                    )
                                }
                                endpoint.contains("/api/live/auto-clip") -> {
                                    liveManager.setAutoClip(reqJson.optBoolean("enabled", true))
                                }
                                endpoint.contains("/api/live/preferences") -> {
                                    if (reqJson.has("auto_clip_enabled")) {
                                        liveManager.setAutoClip(reqJson.optBoolean("auto_clip_enabled", false))
                                    } else {
                                        JSONObject().apply { put("ok", true) }
                                    }
                                }
                                endpoint.contains("/api/live/disconnect") -> liveManager.disconnect()
                                endpoint.contains("/api/live/clips") -> liveManager.getClipsJson()
                                endpoint.contains("/api/live/transcript") -> liveManager.getTranscriptJson()
                                else -> JSONObject().apply { put("ok", true) }
                            }
                            val okFlag = respObj.optBoolean("ok", true)
                            resJson = JSONObject().apply {
                                put("ok", okFlag)
                                put("status", if (okFlag) 200 else 400)
                                put("body", respObj.toString())
                            }.toString()
                        }
                    }
                } catch (_: Exception) {}
                val quoted = JSONObject.quote(resJson)
                val reqQuoted = JSONObject.quote(requestId)
                runOnUiThread {
                    binding.webView.evaluateJavascript(
                        "if (window.__onAndroidApiResult) window.__onAndroidApiResult($reqQuoted, $quoted);",
                        null
                    )
                }
            }
        }

        @JavascriptInterface
        fun getAppVersionName(): String {
            return try {
                packageManager.getPackageInfo(packageName, 0).versionName ?: "5.0.6-beta"
            } catch (_: Exception) {
                "5.0.6-beta"
            }
        }

        @JavascriptInterface
        fun pickVideo() {
            runOnUiThread {
                selectVideoLauncher.launch("video/*")
            }
        }

        @JavascriptInterface
        fun openBrowser(url: String) {
            runOnUiThread {
                openExternalUrl(url)
            }
        }

        @JavascriptInterface
        fun downloadAndInstallApk(apkUrl: String, versionLabel: String) {
            Thread {
                try {
                    val outDir = getExternalFilesDir(android.os.Environment.DIRECTORY_DOWNLOADS) ?: cacheDir
                    val apkFile = File(outDir, "ClipifyAI_update.apk")
                    val conn = (java.net.URL(apkUrl).openConnection() as java.net.HttpURLConnection).apply {
                        instanceFollowRedirects = true
                        connectTimeout = 15000
                        readTimeout = 30000
                        setRequestProperty("User-Agent", "ClipifyAI-Android")
                    }
                    val total = conn.contentLengthLong.coerceAtLeast(1L)
                    var downloaded = 0L
                    var lastPct = -1
                    conn.inputStream.use { input ->
                        java.io.FileOutputStream(apkFile).use { output ->
                            val buf = ByteArray(16384)
                            while (true) {
                                val r = input.read(buf)
                                if (r <= 0) break
                                output.write(buf, 0, r)
                                downloaded += r
                                val pct = ((downloaded * 100L) / total).toInt().coerceIn(0, 100)
                                if (pct != lastPct && (pct % 5 == 0 || pct == 100)) {
                                    lastPct = pct
                                    runOnUiThread {
                                        binding.webView.evaluateJavascript(
                                            "window.onMobileUpdateProgress && window.onMobileUpdateProgress($pct, 'Downloading $versionLabel ($pct%)...');",
                                            null
                                        )
                                    }
                                }
                            }
                        }
                    }
                    runOnUiThread {
                        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O &&
                            !packageManager.canRequestPackageInstalls()
                        ) {
                            Toast.makeText(
                                this@MainActivity,
                                "Allow 'Install unknown apps' for Clipify AI to finish updating",
                                Toast.LENGTH_LONG
                            ).show()
                            val permIntent = Intent(
                                android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:$packageName")
                            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            startActivity(permIntent)
                            binding.webView.evaluateJavascript(
                                "window.onMobileUpdateReady && window.onMobileUpdateReady(false, 'Enable \"Install unknown apps\" permission, then tap Install again.');",
                                null
                            )
                            return@runOnUiThread
                        }
                        val apkUri = androidx.core.content.FileProvider.getUriForFile(
                            this@MainActivity,
                            "dev.sherlock.clipifyai.fileprovider",
                            apkFile
                        )
                        val installIntent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(apkUri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(installIntent)
                        binding.webView.evaluateJavascript(
                            "window.onMobileUpdateReady && window.onMobileUpdateReady(true, 'Installer opened! Tap Install to complete update.');",
                            null
                        )
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        binding.webView.evaluateJavascript(
                            "window.onMobileUpdateReady && window.onMobileUpdateReady(false, 'Download failed. Opening release page...');",
                            null
                        )
                        openExternalUrl(apkUrl)
                    }
                }
            }.start()
        }

        @JavascriptInterface
        fun showToast(msg: String) {
            runOnUiThread {
                Toast.makeText(this@MainActivity, msg, Toast.LENGTH_SHORT).show()
            }
        }

        @JavascriptInterface
        fun speakText(text: String) {
            runOnUiThread {
                try {
                    tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "clipify_preview_${System.currentTimeMillis()}")
                } catch (_: Exception) {}
            }
        }

        @JavascriptInterface
        fun startRender(uriStr: String?, durationSec: Int, layout: String?, captionsEnabled: Boolean) {
            startRenderWithCount(uriStr, durationSec, layout, captionsEnabled, 1)
        }

        @JavascriptInterface
        fun startRenderWithCount(uriStr: String?, durationSec: Int, layout: String?, captionsEnabled: Boolean, clipsCount: Int) {
            runOnUiThread {
                val savedUserVideo = File(filesDir, "user_selected_video.mp4")
                val extUserVideo = File(getExternalFilesDir(null), "user_selected_video.mp4")
                val targetPath = when {
                    !uriStr.isNullOrEmpty() && (File(uriStr).exists() || uriStr.startsWith("http") || uriStr.startsWith("content://") || uriStr.startsWith("file://")) -> uriStr
                    savedUserVideo.exists() && savedUserVideo.length() > 1024 -> savedUserVideo.absolutePath
                    extUserVideo.exists() && extUserVideo.length() > 1024 -> extUserVideo.absolutePath
                    mCurrentVideoUri != null -> mCurrentVideoUri.toString()
                    else -> ""
                }

                if (targetPath.isEmpty()) {
                    Toast.makeText(this@MainActivity, "Please choose a video from your gallery first!", Toast.LENGTH_LONG).show()
                    val js = "if (window.onMobileRenderProgress) window.onMobileRenderProgress(100, 'Please select a video from your gallery first', '');"
                    binding.webView.evaluateJavascript(js, null)
                    return@runOnUiThread
                }

                val dur = if (durationSec in 5..180) durationSec else 30
                val count = clipsCount.coerceIn(1, 5)
                val projId = projectManager.createProject("Mobile Clip " + System.currentTimeMillis(), targetPath)
                Toast.makeText(this@MainActivity, "Rendering $count 9:16 Short(s) with Media3 HD...", Toast.LENGTH_SHORT).show()

                val serviceIntent = Intent(this@MainActivity, RenderForegroundService::class.java).apply {
                    action = RenderForegroundService.ACTION_START_RENDER
                    putExtra("video_uri", targetPath)
                    putExtra("project_id", projId)
                    putExtra("duration_sec", dur)
                    putExtra("layout", layout ?: "center")
                    putExtra("captions", captionsEnabled)
                    putExtra("clipsCount", count)
                }
                startForegroundService(serviceIntent)
            }
        }

        @JavascriptInterface
        fun startYouTubeImport(url: String) {
            apiExecutor.execute {
                val destFile = File(filesDir, "user_selected_video.mp4")
                val res = YouTubeStreamDownloader.downloadYouTubeMp4(url, destFile) { pct, msg ->
                    val msgQ = JSONObject.quote(msg)
                    runOnUiThread {
                        binding.webView.evaluateJavascript(
                            "if (window.onMobileImportProgress) window.onMobileImportProgress($pct, $msgQ, '', '', '');",
                            null
                        )
                    }
                }
                val pathClean = if (res.ok && res.file != null) res.file.absolutePath.replace("\\", "/") else ""
                val pathQ = JSONObject.quote(pathClean)
                val titleQ = JSONObject.quote(res.title)
                val errQ = JSONObject.quote(res.error)
                if (res.ok && res.file != null) {
                    mCurrentVideoUri = Uri.fromFile(res.file)
                }
                runOnUiThread {
                    val stageMsg = if (res.ok) JSONObject.quote("Download complete: ${res.title}") else JSONObject.quote(res.error)
                    binding.webView.evaluateJavascript(
                        "if (window.onMobileImportProgress) window.onMobileImportProgress(100, $stageMsg, $pathQ, $titleQ, $errQ);",
                        null
                    )
                }
            }
        }

        @JavascriptInterface
        fun startYouTubeClip(url: String, mode: String) {
            runOnUiThread {
                Toast.makeText(this@MainActivity, "Processing video: $url", Toast.LENGTH_SHORT).show()
                val projId = projectManager.createProject("YouTube Clip " + System.currentTimeMillis(), url)

                val serviceIntent = Intent(this@MainActivity, RenderForegroundService::class.java).apply {
                    action = RenderForegroundService.ACTION_START_RENDER
                    putExtra("video_uri", url)
                    putExtra("project_id", projId)
                    putExtra("duration_sec", 30)
                    putExtra("layout", "center")
                    putExtra("captions", true)
                }
                startForegroundService(serviceIntent)
            }
        }

        @JavascriptInterface
        fun playVideo(filePath: String) {
            runOnUiThread {
                try {
                    val file = File(filePath)
                    if (!file.exists()) {
                        Toast.makeText(this@MainActivity, "File not found: $filePath", Toast.LENGTH_SHORT).show()
                        return@runOnUiThread
                    }
                    val uri = FileProvider.getUriForFile(this@MainActivity, "dev.sherlock.clipifyai.fileprovider", file)
                    val intent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(uri, "video/mp4")
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(intent, "Play Clipify Short"))
                } catch (e: Exception) {
                    Toast.makeText(this@MainActivity, "Could not open video player: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }

        @JavascriptInterface
        fun shareVideo(filePath: String) {
            runOnUiThread {
                try {
                    val file = File(filePath)
                    if (!file.exists()) {
                        Toast.makeText(this@MainActivity, "File not found", Toast.LENGTH_SHORT).show()
                        return@runOnUiThread
                    }
                    val uri = FileProvider.getUriForFile(this@MainActivity, "dev.sherlock.clipifyai.fileprovider", file)
                    val intent = Intent(Intent.ACTION_SEND).apply {
                        type = "video/mp4"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(intent, "Share 9:16 Short"))
                } catch (e: Exception) {
                    Toast.makeText(this@MainActivity, "Could not share video: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }

        @JavascriptInterface
        fun getRecentProjectsJson(): String {
            return try {
                val clips = mediaProcessor.getRecentClips()
                val arr = JSONArray()
                for (clip in clips) {
                    val obj = JSONObject()
                    obj.put("name", clip.name)
                    obj.put("path", clip.path)
                    obj.put("sizeBytes", clip.sizeBytes)
                    obj.put("formattedSize", clip.formattedSize)
                    obj.put("dateModified", clip.dateModified)
                    arr.put(obj)
                }
                arr.toString()
            } catch (e: Exception) {
                "[]"
            }
        }
    }
}
