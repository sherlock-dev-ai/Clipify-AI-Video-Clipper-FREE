package dev.sherlock.clipifyai.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import dev.sherlock.clipifyai.R
import dev.sherlock.clipifyai.media.AndroidMediaProcessor
import dev.sherlock.clipifyai.network.DesktopSyncClient
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader
import java.io.File

object RenderState {
    var listener: ((progress: Int, stage: String, outputPath: String?) -> Unit)? = null
    var isRendering: Boolean = false
    var lastExportPath: String? = null
    var lastMetadataJson: String = "{}"
    var lastOutputsJson: String = "[]"
}

class RenderForegroundService : Service() {

    companion object {
        const val CHANNEL_ID = "clipify_render_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_START_RENDER = "ACTION_START_RENDER"
        const val ACTION_CANCEL_RENDER = "ACTION_CANCEL_RENDER"
        private const val TAG = "ClipifyAI_RenderService"
        private val renderExecutor = java.util.concurrent.Executors.newSingleThreadExecutor()
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL_RENDER) {
            RenderState.isRendering = false
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        val videoUriStr = intent?.getStringExtra("video_uri") ?: ""
        val durationSec = intent?.getIntExtra("duration_sec", 30) ?: 30
        val layout = intent?.getStringExtra("layout") ?: "center"
        val captions = intent?.getBooleanExtra("captions", true) ?: true
        val maxHeight = intent?.getIntExtra("max_height", 4320) ?: 4320

        val notification = createNotification("Preparing 9:16 vertical render...", 0)
        startForeground(NOTIFICATION_ID, notification)
        RenderState.isRendering = true

        renderExecutor.execute {
            try {
                val processor = AndroidMediaProcessor(this)
                val syncClient = DesktopSyncClient()
                val isOnlineStream = videoUriStr.startsWith("http://", ignoreCase = true) ||
                        videoUriStr.startsWith("https://", ignoreCase = true)

                if (isOnlineStream) {
                    Log.i(TAG, "isOnlineStream=true ($videoUriStr), checking syncClient connection...")
                    // Check if desktop AI engine is reachable
                    val connected = syncClient.isConnected()
                    Log.i(TAG, "syncClient.isConnected() = $connected, activeHost=${syncClient.getActiveHost()}")
                    if (connected) {
                        updateNotification("Connecting to Clipify AI Desktop engine...", 10)
                        RenderState.listener?.invoke(10, "Connecting to Clipify AI Desktop engine...", null)

                        val jobId = syncClient.startInstantJob(videoUriStr, durationSec, layout, captions)
                        Log.i(TAG, "startInstantJob returned jobId=$jobId")
                        if (!jobId.isNullOrEmpty()) {
                            var done = false
                            var finalOutputUrl: String? = null
                            var errorMsg: String? = null

                            while (!done && RenderState.isRendering) {
                                Thread.sleep(1500)
                                val statusObj = syncClient.pollInstantJob(jobId)
                                if (statusObj == null) continue

                                val status = statusObj.optString("status", "")
                                val progress = statusObj.optInt("progress", 15)
                                val stage = statusObj.optString("stage", "Processing video with WhisperX & Smart Framing...")

                                updateNotification(stage, progress)
                                RenderState.listener?.invoke(progress, stage, null)

                                if (status == "completed") {
                                    done = true
                                    val out = statusObj.optString("output_url", "")
                                    if (out.isNotEmpty()) finalOutputUrl = out
                                } else if (status == "error" || status == "failed") {
                                    done = true
                                    errorMsg = statusObj.optString("error", "Desktop processing failed")
                                }
                            }

                            if (!finalOutputUrl.isNullOrEmpty()) {
                                updateNotification("Downloading 9:16 Short to phone Gallery...", 95)
                                RenderState.listener?.invoke(95, "Downloading 9:16 Short to device...", null)

                                val exportFile = processor.getExportFile()
                                val downloaded = syncClient.downloadFile(finalOutputUrl, exportFile)
                                if (downloaded && exportFile.exists() && exportFile.length() > 1024) {
                                    processor.insertIntoMediaStore(exportFile)
                                    MediaScannerConnection.scanFile(
                                        this,
                                        arrayOf(exportFile.absolutePath),
                                        arrayOf("video/mp4"),
                                        null
                                    )
                                    RenderState.lastExportPath = exportFile.absolutePath
                                    updateNotification("✓ 9:16 Short saved to Gallery!", 100)
                                    RenderState.listener?.invoke(100, "Render complete! Saved to Movies/ClipifyAI.", exportFile.absolutePath)
                                    return@execute
                                }
                            }

                            if (errorMsg != null) {
                                updateNotification(errorMsg, 100)
                                RenderState.listener?.invoke(100, errorMsg, null)
                                return@execute
                            }
                        } else {
                            updateNotification("Could not start desktop instant job", 100)
                            RenderState.listener?.invoke(100, "Could not start desktop instant job", null)
                            return@execute
                        }
                    } else {
                        // Independent Mobile Mode: download YouTube or direct MP4 stream on-device, then render 9:16 Short!
                        val dlFile = File(filesDir, "user_selected_video.mp4")
                        var dlCaptions: List<YouTubeStreamDownloader.CaptionSegment> = emptyList()
                        var dlTitle = ""
                        val sourceFile: File? = if (YouTubeStreamDownloader.isYouTubeUrl(videoUriStr)) {
                            updateNotification("Downloading YouTube HD video on mobile...", 10)
                            RenderState.listener?.invoke(10, "[YouTube] Resolving HD stream & captions...", null)
                            val res = YouTubeStreamDownloader.downloadYouTubeMp4(videoUriStr, dlFile, maxHeight) { pct, msg ->
                                val scaled = (pct * 0.45).toInt().coerceIn(10, 48)
                                updateNotification(msg, scaled)
                                RenderState.listener?.invoke(scaled, msg, null)
                            }
                            if (!res.ok || res.file == null) {
                                updateNotification(res.error, 100)
                                RenderState.listener?.invoke(100, "ERROR: ${res.error}", null)
                                return@execute
                            }
                            dlCaptions = res.captions
                            dlTitle = res.title
                            res.file
                        } else {
                            updateNotification("Downloading video stream...", 15)
                            RenderState.listener?.invoke(15, "[Download] Fetching direct video stream...", null)
                            processor.resolveSourceVideoFile(videoUriStr)
                        }

                        if (sourceFile == null || !sourceFile.exists() || sourceFile.length() < 1024) {
                            val msg = "ERROR: Could not download video stream. Pick a video from Gallery or try another link."
                            updateNotification(msg, 100)
                            RenderState.listener?.invoke(100, msg, null)
                            return@execute
                        }

                        val clipsCount = intent?.getIntExtra("clipsCount", 1)?.coerceIn(1, 5) ?: 1
                        val sourceKey = YouTubeStreamDownloader.extractVideoId(videoUriStr) ?: videoUriStr
                        val windows = processor.findHighlightWindowsMs(
                            sourceFile = sourceFile,
                            targetDurationSec = durationSec,
                            count = clipsCount,
                            sourceKey = sourceKey,
                            captions = dlCaptions
                        ) { pct, msg ->
                            val scaled = 48 + (pct / 5)
                            RenderState.listener?.invoke(scaled.coerceAtMost(55), msg, null)
                        }

                        var lastSavedFile: File? = null
                        val savedUrls = mutableListOf<String>()
                        val metaMap = org.json.JSONObject()
                        val candArr = org.json.JSONArray()
                        for ((idx, win) in windows.withIndex()) {
                            val exportFile = processor.getExportFile()
                            val clipPrefix = if (windows.size > 1) "[Clip ${idx + 1}/${windows.size}] " else ""
                            RenderState.listener?.invoke(52 + (idx * 10), "$clipPrefix Rendering $layout 9:16 MP4 (${win.first / 1000}s–${win.second / 1000}s)...", null)
                            val success = processor.processAndRenderShort(
                                sourceFile = sourceFile,
                                exportFile = exportFile,
                                targetDurationSec = durationSec,
                                layout = layout,
                                captionsEnabled = captions,
                                captions = dlCaptions,
                                videoTitle = dlTitle,
                                windowOverride = win
                            ) { progress, stage ->
                                val base = 50 + ((idx * 48) / windows.size)
                                val span = 48 / windows.size
                                val scaled = base + ((progress * span) / 100)
                                updateNotification("$clipPrefix$stage", scaled)
                                RenderState.listener?.invoke(scaled.coerceAtMost(99), "$clipPrefix$stage", null)
                            }
                            if (success && exportFile.exists() && exportFile.length() > 1024) {
                                lastSavedFile = exportFile
                                val fUrl = "file://${exportFile.absolutePath.replace("\\", "/")}"
                                savedUrls.add(fUrl)
                                try {
                                    val m = org.json.JSONObject(processor.lastClipMetadataJson)
                                    metaMap.put(fUrl, m)
                                    candArr.put(m)
                                } catch (_: Exception) {}
                            }
                        }

                        if (lastSavedFile != null) {
                            RenderState.lastExportPath = lastSavedFile.absolutePath
                            RenderState.lastOutputsJson = org.json.JSONArray(savedUrls).toString()
                            RenderState.lastMetadataJson = org.json.JSONObject().apply {
                                put("metadata", metaMap)
                                put("candidates", candArr)
                            }.toString()
                            updateNotification("✓ ${savedUrls.size} Short(s) saved to Gallery!", 100)
                            RenderState.listener?.invoke(100, "✔ Render complete! Saved ${savedUrls.size} Short(s).", lastSavedFile.absolutePath)
                        } else {
                            updateNotification("Could not render short", 100)
                            RenderState.listener?.invoke(100, "ERROR: Could not render MP4 short.", null)
                        }
                        return@execute
                    }
                } else {
                    // Local user video processing on-device
                    val sourceFile = processor.resolveSourceVideoFile(videoUriStr)
                    if (sourceFile == null || !sourceFile.exists() || sourceFile.length() < 1024) {
                        updateNotification("Please choose a video from your gallery first", 100)
                        RenderState.listener?.invoke(100, "Please choose a video from your gallery first", null)
                        return@execute
                    }
                    val clipsCount = intent?.getIntExtra("clipsCount", 1)?.coerceIn(1, 5) ?: 1
                    RenderState.listener?.invoke(10, "Scanning local video for best highlight moments...", null)
                    updateNotification("Scanning local video for highlights...", 15)
                    val windows = processor.findHighlightWindowsMs(
                        sourceFile = sourceFile,
                        targetDurationSec = durationSec,
                        count = clipsCount,
                        sourceKey = sourceFile.name + "_" + sourceFile.length()
                    ) { pct, msg ->
                        RenderState.listener?.invoke(pct.coerceIn(10, 20), msg, null)
                    }

                    var lastSavedFile: File? = null
                    val savedUrls = mutableListOf<String>()
                    val metaMap = org.json.JSONObject()
                    val candArr = org.json.JSONArray()
                    for ((idx, win) in windows.withIndex()) {
                        val exportFile = processor.getExportFile()
                        val clipPrefix = if (windows.size > 1) "[Clip ${idx + 1}/${windows.size}] " else ""
                        val success = processor.processAndRenderShort(
                            sourceFile = sourceFile,
                            exportFile = exportFile,
                            targetDurationSec = durationSec,
                            layout = layout,
                            captionsEnabled = captions,
                            videoTitle = sourceFile.nameWithoutExtension,
                            windowOverride = win
                        ) { progress, stage ->
                            val base = (idx * 98) / windows.size
                            val span = 98 / windows.size
                            val scaled = (base + ((progress * span) / 100)).coerceIn(12, 99)
                            updateNotification("$clipPrefix$stage", scaled)
                            RenderState.listener?.invoke(scaled, "$clipPrefix$stage", null)
                        }
                        if (success && exportFile.exists() && exportFile.length() > 1024) {
                            lastSavedFile = exportFile
                            val fUrl = "file://${exportFile.absolutePath.replace("\\", "/")}"
                            savedUrls.add(fUrl)
                            try {
                                val m = org.json.JSONObject(processor.lastClipMetadataJson)
                                metaMap.put(fUrl, m)
                                candArr.put(m)
                            } catch (_: Exception) {}
                        }
                    }

                    if (lastSavedFile != null) {
                        RenderState.lastExportPath = lastSavedFile.absolutePath
                        RenderState.lastOutputsJson = org.json.JSONArray(savedUrls).toString()
                        RenderState.lastMetadataJson = org.json.JSONObject().apply {
                            put("metadata", metaMap)
                            put("candidates", candArr)
                        }.toString()
                        updateNotification("✓ ${savedUrls.size} Short(s) saved to Gallery!", 100)
                        RenderState.listener?.invoke(100, "Render complete! Saved ${savedUrls.size} Short(s).", lastSavedFile.absolutePath)
                    } else {
                        updateNotification("Could not complete render", 100)
                        RenderState.listener?.invoke(100, "Could not render short.", null)
                    }
                }

                Thread.sleep(1000)
            } catch (e: Exception) {
                Log.e(TAG, "Error in render worker thread", e)
                RenderState.listener?.invoke(100, "Error rendering: ${e.message}", null)
            } finally {
                RenderState.isRendering = false
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }

        return START_NOT_STICKY
    }

    private fun createNotification(message: String, progress: Int): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Clipify AI Studio")
            .setContentText(message)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setProgress(100, progress, false)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateNotification(message: String, progress: Int) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, createNotification(message, progress))
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Clipify AI Video Rendering",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shows real-time progress of video reframing and subtitle generation"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
