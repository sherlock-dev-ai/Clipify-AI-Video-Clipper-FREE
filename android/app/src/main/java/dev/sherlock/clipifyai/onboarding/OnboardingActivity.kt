package dev.sherlock.clipifyai.onboarding

import android.annotation.SuppressLint
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import dev.sherlock.clipifyai.MainActivity
import dev.sherlock.clipifyai.databinding.ActivityOnboardingBinding
import org.json.JSONObject
import java.util.Locale

class OnboardingActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOnboardingBinding
    private lateinit var prefs: SharedPreferences

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("clipify_prefs", Context.MODE_PRIVATE)

        binding = ActivityOnboardingBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupInstallerWebView()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupInstallerWebView() {
        binding.installerWebview.setBackgroundColor(android.graphics.Color.parseColor("#090a0d"))
        binding.installerWebview.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        binding.installerWebview.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            useWideViewPort = false
            loadWithOverviewMode = false
            setSupportZoom(false)
            displayZoomControls = false
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        }

        binding.installerWebview.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress < 100) {
                    binding.installerProgress.visibility = View.VISIBLE
                    binding.installerProgress.progress = newProgress
                } else {
                    binding.installerProgress.visibility = View.GONE
                }
            }
        }

        binding.installerWebview.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: return false
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    openExternalUrl(url)
                    return true
                }
                return false
            }
        }

        binding.installerWebview.addJavascriptInterface(InstallerBridge(), "AndroidBridge")
        binding.installerWebview.loadUrl("file:///android_asset/www/installer/index.html")
    }

    private fun openExternalUrl(url: String) {
        try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(this, "Could not open browser", Toast.LENGTH_SHORT).show()
        }
    }

    inner class InstallerBridge {
        @JavascriptInterface
        fun finishOnboarding() {
            runOnUiThread {
                prefs.edit().putBoolean("onboarding_complete", true).apply()
                val intent = Intent(this@OnboardingActivity, MainActivity::class.java)
                startActivity(intent)
                finish()
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
                Toast.makeText(this@OnboardingActivity, msg, Toast.LENGTH_SHORT).show()
            }
        }

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
    }
}
