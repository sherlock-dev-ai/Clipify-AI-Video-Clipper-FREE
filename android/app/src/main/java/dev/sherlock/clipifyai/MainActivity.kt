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
import dev.sherlock.clipifyai.media.ProjectManager
import dev.sherlock.clipifyai.network.DesktopSyncClient
import dev.sherlock.clipifyai.onboarding.OnboardingActivity
import dev.sherlock.clipifyai.service.RenderForegroundService
import dev.sherlock.clipifyai.service.RenderState
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "ClipifyMainActivity"
    }

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: SharedPreferences
    private lateinit var projectManager: ProjectManager
    private lateinit var mediaProcessor: AndroidMediaProcessor
    private lateinit var syncClient: DesktopSyncClient
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
                val outJson = outputPath?.replace("\\", "/") ?: ""
                val stageEsc = stage.replace("'", "\\'")
                val js = "if (window.onMobileRenderProgress) window.onMobileRenderProgress($progress, '$stageEsc', '$outJson');"
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
        binding.bottomNavigation.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_create -> {
                    binding.webView.evaluateJavascript("if (typeof navigateTo === 'function') navigateTo('create'); else window.location.hash = '#create';", null)
                    true
                }
                R.id.nav_instant -> {
                    binding.webView.evaluateJavascript("if (typeof navigateTo === 'function') navigateTo('instant'); else window.location.hash = '#instant';", null)
                    true
                }
                R.id.nav_trending -> {
                    binding.webView.evaluateJavascript("if (typeof navigateTo === 'function') navigateTo('trending'); else window.location.hash = '#trending';", null)
                    true
                }
                R.id.nav_editor -> {
                    binding.webView.evaluateJavascript("if (typeof navigateTo === 'function') navigateTo('editor'); else window.location.hash = '#editor';", null)
                    true
                }
                R.id.nav_more -> {
                    binding.webView.evaluateJavascript("if (typeof window.toggleMobileMoreDrawer === 'function') window.toggleMobileMoreDrawer();", null)
                    true
                }
                else -> false
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
        fun showToast(msg: String) {
            runOnUiThread {
                Toast.makeText(this@MainActivity, msg, Toast.LENGTH_SHORT).show()
            }
        }

        @JavascriptInterface
        fun startRender(uriStr: String?, durationSec: Int, layout: String?, captionsEnabled: Boolean) {
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
                val projId = projectManager.createProject("Mobile Clip " + System.currentTimeMillis(), targetPath)
                Toast.makeText(this@MainActivity, "Rendering 9:16 Short with MediaCodec acceleration...", Toast.LENGTH_SHORT).show()

                val serviceIntent = Intent(this@MainActivity, RenderForegroundService::class.java).apply {
                    action = RenderForegroundService.ACTION_START_RENDER
                    putExtra("video_uri", targetPath)
                    putExtra("project_id", projId)
                    putExtra("duration_sec", dur)
                    putExtra("layout", layout ?: "center")
                    putExtra("captions", captionsEnabled)
                }
                startForegroundService(serviceIntent)
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
