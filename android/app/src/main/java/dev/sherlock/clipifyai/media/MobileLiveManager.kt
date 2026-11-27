package dev.sherlock.clipifyai.media

import android.content.Context
import android.util.Log
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class MobileLiveManager(private val context: Context) {

    companion object {
        private const val TAG = "MobileLiveManager"
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    private val processor = AndroidMediaProcessor(context)
    private val executor = Executors.newCachedThreadPool()
    private val running = AtomicBoolean(false)
    private val autoClipEnabled = AtomicBoolean(false)

    @Volatile private var status = "idle"
    @Volatile private var statusDetail = "Ready to connect to live stream"
    @Volatile private var sourceType = "youtube"
    @Volatile private var sourceUrl = ""
    @Volatile private var streamTitle = ""
    @Volatile private var bufferChunks = 0
    @Volatile private var bufferDurationSec = 0.0
    @Volatile private var activeBufferFile: File? = null
    @Volatile private var previewPath: String? = null
    @Volatile private var lastAutoClipTimeMs = 0L

    private val consoleLogs = CopyOnWriteArrayList<JSONObject>()
    private val liveClips = CopyOnWriteArrayList<JSONObject>()

    private fun addLog(level: String, msg: String) {
        val t = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        consoleLogs.add(JSONObject().apply {
            put("level", level)
            put("message", msg)
            put("time", t)
        })
        while (consoleLogs.size > 40) {
            consoleLogs.removeAt(0)
        }
    }

    fun connect(url: String, type: String): JSONObject {
        disconnect()
        sourceUrl = url.trim()
        sourceType = type.ifBlank { "youtube" }
        status = "connecting"
        statusDetail = "Resolving live stream..."
        bufferChunks = 0
        bufferDurationSec = 0.0
        activeBufferFile = null
        previewPath = null
        consoleLogs.clear()
        addLog("system", "Connecting to ${sourceType.uppercase()} stream: $sourceUrl")

        running.set(true)
        executor.execute {
            try {
                val liveDir = File(context.cacheDir, "live_buffer").apply { mkdirs() }
                liveDir.listFiles()?.forEach { it.delete() }

                var resolvedDirectUrl: String? = null
                var hlsUrl: String? = null

                if (YouTubeStreamDownloader.isYouTubeUrl(sourceUrl)) {
                    val info = YouTubeStreamDownloader.resolveLiveStream(sourceUrl)
                    if (!info.ok) {
                        status = "error"
                        statusDetail = info.error
                        addLog("error", info.error)
                        running.set(false)
                        return@execute
                    }
                    streamTitle = info.title
                    hlsUrl = info.hlsManifestUrl
                    resolvedDirectUrl = info.directStreamUrl
                    addLog("info", "Resolved: $streamTitle (live=${info.isLive})")
                    if (!info.isLive) {
                        val bufFile = File(liveDir, "live_vod_hd.mp4")
                        addLog("info", "Downloading 1080p HD stream buffer for Live Studio...")
                        val dlRes = YouTubeStreamDownloader.downloadYouTubeMp4(sourceUrl, bufFile, 1080) { pct, msg ->
                            bufferChunks = (pct / 5).coerceAtLeast(1)
                            bufferDurationSec = (pct * 0.9)
                            if (pct % 20 == 0) addLog("info", msg)
                        }
                        if (dlRes.ok && dlRes.file != null && dlRes.file.exists()) {
                            activeBufferFile = dlRes.file
                            previewPath = "file://${dlRes.file.absolutePath}"
                            status = "live"
                            statusDetail = "HD Live VOD ready (${dlRes.height}p)"
                            addLog("system", "HD Live buffer ready (${dlRes.height}p)! Preview & Instant Clip enabled.")
                            return@execute
                        }
                    }
                } else {
                    resolvedDirectUrl = sourceUrl
                }

                if (resolvedDirectUrl != null) {
                    // Download stream into rolling buffer file for reliable Media3 clipping & preview
                    val bufFile = File(liveDir, "live_stream_source.mp4")
                    addLog("info", "Buffering stream into local ingestion cache...")
                    val req = Request.Builder()
                        .url(resolvedDirectUrl)
                        .header("User-Agent", "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip")
                        .get()
                        .build()

                    client.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) {
                            throw IllegalStateException("Stream HTTP ${resp.code}")
                        }
                        val body = resp.body ?: throw IllegalStateException("Empty stream body")
                        val buf = ByteArray(64 * 1024)
                        var total = 0L
                        val maxCapBytes = 45L * 1024L * 1024L // cap live buffer at 45 MB
                        FileOutputStream(bufFile).use { out ->
                            body.byteStream().use { inp ->
                                while (running.get() && total < maxCapBytes) {
                                    val r = inp.read(buf)
                                    if (r == -1) break
                                    out.write(buf, 0, r)
                                    total += r
                                    val chunksNow = ((total / (512 * 1024)) + 1).toInt()
                                    if (chunksNow != bufferChunks) {
                                        bufferChunks = chunksNow
                                        bufferDurationSec = (chunksNow * 4.0).coerceAtMost(90.0)
                                        if (status != "live" && total > 5 * 1024 * 1024) {
                                            val durMs = probeVideoDurationMs(bufFile)
                                            if (durMs >= 10_000L) {
                                                activeBufferFile = bufFile
                                                previewPath = "file://${bufFile.absolutePath}"
                                                status = "live"
                                                statusDetail = "Live ingestion active (${durMs / 1000}s / ${String.format("%.1f", total / (1024.0 * 1024.0))} MB buffered)"
                                                addLog("system", "Live buffer ready (${durMs / 1000}s)! Preview & Instant Clip enabled.")
                                            }
                                        }
                                        if (autoClipEnabled.get() && status == "live" && total > 8 * 1024 * 1024 &&
                                            System.currentTimeMillis() - lastAutoClipTimeMs > 30_000L
                                        ) {
                                            lastAutoClipTimeMs = System.currentTimeMillis()
                                            addLog("info", "Auto-Clip triggered on live energy spike!")
                                            triggerClipInternal(30, "split", true)
                                        }
                                    }
                                }
                            }
                        }
                        if (bufFile.exists() && bufFile.length() > 1024) {
                            activeBufferFile = bufFile
                            previewPath = "file://${bufFile.absolutePath}"
                            status = "live"
                            statusDetail = "Live buffer active (${String.format("%.1f", bufFile.length() / (1024.0 * 1024.0))} MB)"
                            addLog("info", "Stream buffer ready (${bufferChunks} chunks).")
                        }
                    }
                } else if (hlsUrl != null) {
                    status = "live"
                    statusDetail = "HLS live manifest resolved"
                    addLog("info", "HLS manifest ready: ${hlsUrl.take(60)}...")
                    // Download fallback full MP4 via YouTubeStreamDownloader if HLS-only
                    val bufFile = File(liveDir, "live_hls_source.mp4")
                    val dlRes = YouTubeStreamDownloader.downloadYouTubeMp4(sourceUrl, bufFile) { pct, msg ->
                        bufferChunks = (pct / 10).coerceAtLeast(1)
                        bufferDurationSec = (pct * 0.6)
                        if (pct % 20 == 0) addLog("info", msg)
                    }
                    if (dlRes.ok && dlRes.file != null) {
                        activeBufferFile = dlRes.file
                        previewPath = "file://${dlRes.file.absolutePath}"
                        addLog("system", "Live buffer ready for clipping!")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Live connect failed", e)
                if (running.get()) {
                    status = "error"
                    statusDetail = "Live stream error: ${e.message}"
                    addLog("error", statusDetail)
                }
            }
        }

        return getStatusJson()
    }

    fun getStatusJson(): JSONObject {
        return JSONObject().apply {
            put("ok", true)
            put("status", status)
            put("status_detail", statusDetail)
            put("source_type", sourceType)
            put("source_url", sourceUrl)
            put("title", streamTitle)
            put("buffer_chunks", bufferChunks)
            put("buffer_duration_seconds", bufferDurationSec)
            put("clips_count", liveClips.size)
            put("has_preview", previewPath != null)
            put("preview_url", previewPath ?: "")
            put("auto_clip_enabled", autoClipEnabled.get())
            put("console_logs", JSONArray().apply { consoleLogs.forEach { put(it) } })
        }
    }

    fun setAutoClip(enabled: Boolean): JSONObject {
        autoClipEnabled.set(enabled)
        addLog("system", "Auto-Clip ${if (enabled) "ENABLED" else "DISABLED"}")
        return JSONObject().apply {
            put("ok", true)
            put("auto_clip_enabled", enabled)
        }
    }

    fun instantClip(durationSec: Int, layout: String, captions: Boolean): JSONObject {
        val src = activeBufferFile
        if (src == null || !src.exists() || src.length() < 1024) {
            return JSONObject().apply {
                put("ok", false)
                put("error", "Live buffer is still warming up. Wait a few seconds and try again.")
            }
        }
        addLog("info", "Rendering ${durationSec}s live Short ($layout)...")
        val outFile = triggerClipInternal(durationSec, layout, captions)
        return if (outFile != null && outFile.exists()) {
            JSONObject().apply {
                put("ok", true)
                put("clip_id", "live_${System.currentTimeMillis()}")
                put("filename", outFile.name)
                put("path", "file://${outFile.absolutePath}")
                put("message", "Saved ${durationSec}s Live Short to Movies/ClipifyAI!")
            }
        } else {
            JSONObject().apply {
                put("ok", false)
                put("error", "Failed to render live clip from buffer.")
            }
        }
    }

    private fun probeVideoDurationMs(file: File): Long {
        if (!file.exists() || file.length() < 1024) return 0L
        val ret = android.media.MediaMetadataRetriever()
        return try {
            ret.setDataSource(file.absolutePath)
            ret.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
        } catch (_: Exception) {
            0L
        } finally {
            try { ret.release() } catch (_: Exception) {}
        }
    }

    private fun triggerClipInternal(durationSec: Int, layout: String, captions: Boolean): File? {
        val src = activeBufferFile ?: return null
        val snapFile = File(context.cacheDir, "live_snap_${System.currentTimeMillis()}.mp4")
        try {
            src.inputStream().use { inp -> snapFile.outputStream().use { out -> inp.copyTo(out) } }
        } catch (e: Exception) {
            Log.w(TAG, "Live snapshot copy failed: ${e.message}")
            return null
        }
        val snapDurMs = probeVideoDurationMs(snapFile)
        if (snapDurMs < 8000L) {
            snapFile.delete()
            addLog("info", "Live buffer has ${snapDurMs / 1000}s so far; waiting for at least 8s before clipping.")
            return null
        }
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val exportDir = File(
            android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_MOVIES),
            "ClipifyAI"
        ).apply { mkdirs() }
        val exportFile = File(exportDir, "Clipify_Live_$ts.mp4")
        val ok = try {
            processor.processAndRenderShort(
                sourceFile = snapFile,
                exportFile = exportFile,
                targetDurationSec = durationSec.coerceIn(10, 180),
                layout = layout,
                captionsEnabled = captions,
                videoTitle = streamTitle
            ) { pct, msg ->
                if (pct == 22 || pct == 100) addLog("info", msg)
            }
        } finally {
            snapFile.delete()
        }
        if (ok && exportFile.exists() && exportFile.length() > 1024) {
            liveClips.add(0, JSONObject().apply {
                put("id", "live_${System.currentTimeMillis()}")
                put("filename", exportFile.name)
                put("path", "file://${exportFile.absolutePath}")
                put("duration", durationSec)
                put("created_at", System.currentTimeMillis())
            })
            addLog("system", "Live Short saved: ${exportFile.name}")
            return exportFile
        }
        return null
    }

    fun getClipsJson(): JSONObject {
        return JSONObject().apply {
            put("ok", true)
            put("clips", JSONArray().apply { liveClips.forEach { put(it) } })
        }
    }

    fun getTranscriptJson(): JSONObject {
        val src = activeBufferFile
        val segsArr = JSONArray()
        if (src != null && src.exists() && src.length() > 1024) {
            try {
                val segs = OfflineSpeechTranscriber.transcribeWindow(context, src, 0L, 25_000L)
                for (s in segs) {
                    segsArr.put(JSONObject().apply {
                        put("start", s.startMs / 1000.0)
                        put("end", s.endMs / 1000.0)
                        put("text", s.text)
                    })
                }
            } catch (_: Exception) {}
        }
        return JSONObject().apply {
            put("ok", true)
            put("transcript", segsArr)
            put("segments", segsArr)
        }
    }

    fun disconnect(): JSONObject {
        running.set(false)
        status = "idle"
        statusDetail = "Ready to connect to live stream"
        bufferChunks = 0
        bufferDurationSec = 0.0
        previewPath = null
        return JSONObject().apply {
            put("ok", true)
            put("status", "idle")
        }
    }
}

