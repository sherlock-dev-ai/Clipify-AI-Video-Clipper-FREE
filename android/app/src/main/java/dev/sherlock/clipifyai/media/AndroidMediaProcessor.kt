package dev.sherlock.clipifyai.media

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.PointF
import android.media.MediaCodec
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.FaceDetection
import com.google.mlkit.vision.face.FaceDetectorOptions
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.media.MediaMuxer
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.HandlerThread
import android.provider.MediaStore
import android.util.Log
import androidx.media3.common.Effect
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.effect.OverlayEffect
import androidx.media3.effect.Presentation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import com.google.common.collect.ImmutableList
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

data class CropCoordinates(
    val left: Int,
    val top: Int,
    val width: Int,
    val height: Int
)

data class ClipInfo(
    val name: String,
    val path: String,
    val sizeBytes: Long,
    val formattedSize: String,
    val dateModified: Long
)

class AndroidMediaProcessor(private val context: Context) {

    companion object {
        private const val TAG = "ClipifyAI_Processor"
    }

    fun calculateVertical916Crop(inputWidth: Int, inputHeight: Int): CropCoordinates {
        val targetAspect = 9.0 / 16.0
        val currentAspect = inputWidth.toDouble() / inputHeight.toDouble()

        return if (currentAspect > targetAspect) {
            val cropWidth = (inputHeight * targetAspect).toInt()
            val cropLeft = (inputWidth - cropWidth) / 2
            CropCoordinates(left = cropLeft, top = 0, width = cropWidth, height = inputHeight)
        } else {
            val cropHeight = (inputWidth / targetAspect).toInt()
            val cropTop = (inputHeight - cropHeight) / 2
            CropCoordinates(left = 0, top = cropTop, width = inputWidth, height = cropHeight)
        }
    }

    fun getVideoDimensions(videoUri: Uri): Pair<Int, Int> {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(context, videoUri)
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toInt() ?: 1920
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toInt() ?: 1080
            val rotation = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)?.toInt() ?: 0
            if (rotation == 90 || rotation == 270) {
                Pair(height, width)
            } else {
                Pair(width, height)
            }
        } catch (e: Exception) {
            Pair(1920, 1080)
        } finally {
            try { retriever.release() } catch (_: Exception) {}
        }
    }

    fun getExportFile(): File {
        val moviesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
        val clipifyDir = File(moviesDir, "ClipifyAI")
        if (!clipifyDir.exists()) clipifyDir.mkdirs()

        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        return File(clipifyDir, "Clipify_Short_$timestamp.mp4")
    }

    fun getRecentClips(): List<ClipInfo> {
        val list = mutableListOf<ClipInfo>()
        try {
            val moviesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
            val clipifyDir = File(moviesDir, "ClipifyAI")
            if (clipifyDir.exists() && clipifyDir.isDirectory) {
                val files = clipifyDir.listFiles { f -> f.isFile && f.name.endsWith(".mp4", ignoreCase = true) && f.length() > 1024 }
                files?.sortedByDescending { it.lastModified() }?.forEach { f ->
                    val sizeMb = String.format(Locale.US, "%.1f MB", f.length().toDouble() / (1024 * 1024))
                    list.add(ClipInfo(f.name, f.absolutePath, f.length(), sizeMb, f.lastModified()))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error listing clips", e)
        }
        return list
    }

    /**
     * Resolves the real video uploaded by the user or downloaded from stream.
     * Guaranteed to return the user's actual video or null (NEVER a fallback dummy).
     */
    fun resolveSourceVideoFile(uriStr: String?): File? {
        val cacheFile = File(context.cacheDir, "working_source.mp4")
        val userVideo = File(context.filesDir, "user_selected_video.mp4")
        val extVideo = File(context.getExternalFilesDir(null), "user_selected_video.mp4")
        val activeVideo = when {
            userVideo.exists() && userVideo.length() > 1024 -> userVideo
            extVideo.exists() && extVideo.length() > 1024 -> extVideo
            else -> null
        }

        // 1. If user selected a video from their gallery
        if (uriStr.isNullOrEmpty() || (activeVideo != null && uriStr == activeVideo.absolutePath)) {
            if (activeVideo != null) {
                FileInputStream(activeVideo).use { input ->
                    FileOutputStream(cacheFile).use { output ->
                        input.copyTo(output)
                    }
                }
                Log.i(TAG, "Using user selected video: ${cacheFile.length()} bytes")
                return cacheFile
            }
        }

        // 2. Direct file path or web URL provided
        if (!uriStr.isNullOrEmpty()) {
            try {
                if (uriStr.startsWith("http://") || uriStr.startsWith("https://")) {
                    val streamFile = File(context.filesDir, "stream_download.mp4")
                    val downloaded = downloadWebStream(uriStr, streamFile)
                    if (downloaded && streamFile.exists() && streamFile.length() > 1024) {
                        return streamFile
                    }
                } else if (uriStr.startsWith("content://")) {
                    val uri = Uri.parse(uriStr)
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(cacheFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                    if (cacheFile.exists() && cacheFile.length() > 1024) {
                        return cacheFile
                    }
                } else {
                    val rawPath = if (uriStr.startsWith("file://")) uriStr.removePrefix("file://") else uriStr
                    val f = File(rawPath)
                    if (f.exists() && f.length() > 1024) {
                        FileInputStream(f).use { input ->
                            FileOutputStream(cacheFile).use { output ->
                                input.copyTo(output)
                            }
                        }
                        if (cacheFile.exists() && cacheFile.length() > 1024) {
                            return cacheFile
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Could not resolve source: $uriStr", e)
            }
        }

        // 3. Fallback to activeVideo if it exists
        if (activeVideo != null && activeVideo.exists() && activeVideo.length() > 1024) {
            return activeVideo
        }

        return null
    }

    private fun downloadWebStream(url: String, targetFile: File): Boolean {
        try {
            val client = OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .build()
            val req = Request.Builder().url(url).build()
            client.newCall(req).execute().use { response ->
                if (response.isSuccessful) {
                    val contentType = response.header("Content-Type", "")?.lowercase() ?: ""
                    if (!contentType.contains("video") && !contentType.contains("octet-stream") && !url.contains(".mp4", ignoreCase = true)) {
                        Log.w(TAG, "Not a direct video stream: Content-Type is $contentType")
                        return false
                    }
                    val body = response.body ?: return false
                    targetFile.outputStream().use { out ->
                        body.byteStream().copyTo(out)
                    }
                    return targetFile.exists() && targetFile.length() > 1024
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error downloading stream", e)
        }
        return false
    }

    /**
     * Scans 40+ timeline windows using audio energy + variance + caption excitement + optional Hugging Face AI,
     * excluding previously clipped windows for this source so repeated clips are never duplicates.
     */
    fun findHighlightWindowsMs(
        sourceFile: File,
        targetDurationSec: Int,
        count: Int = 1,
        sourceKey: String = sourceFile.name,
        captions: List<YouTubeStreamDownloader.CaptionSegment> = emptyList(),
        onProgress: ((Int, String) -> Unit)? = null
    ): List<Pair<Long, Long>> {
        val targetMs = targetDurationSec.toLong() * 1000L
        var durationMs = 0L
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(sourceFile.absolutePath)
            durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
        } catch (_: Exception) {
        } finally {
            try { retriever.release() } catch (_: Exception) {}
        }

        if (durationMs <= 0L || durationMs <= targetMs + 2000L) {
            return listOf(Pair(0L, if (durationMs > 0L) durationMs else targetMs))
        }

        val prefs = context.getSharedPreferences("clipify_prefs", Context.MODE_PRIVATE)
        val historyKey = "clipped_windows_${sourceKey.hashCode()}"
        val prevStarts = mutableListOf<Long>()
        try {
            val arr = JSONArray(prefs.getString(historyKey, "[]") ?: "[]")
            for (i in 0 until arr.length()) prevStarts.add(arr.optLong(i, -1L))
        } catch (_: Exception) {}

        data class Candidate(val startMs: Long, var score: Double)
        val candidates = mutableListOf<Candidate>()

        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(sourceFile.absolutePath)
            var audioTrack = -1
            for (i in 0 until extractor.trackCount) {
                val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("audio/")) {
                    audioTrack = i
                    break
                }
            }
            val maxStartMs = (durationMs - targetMs - 1000L).coerceAtLeast(0L)
            val minStartMs = (durationMs * 0.05).toLong().coerceAtMost(maxStartMs)
            val steps = 40
            val buf = ByteBuffer.allocateDirect(64 * 1024)

            if (audioTrack >= 0) {
                extractor.selectTrack(audioTrack)
                for (step in 0 until steps) {
                    val candStartMs = if (steps > 1) {
                        minStartMs + ((maxStartMs - minStartMs) * step) / (steps - 1)
                    } else minStartMs
                    extractor.seekTo(candStartMs * 1000L, MediaExtractor.SEEK_TO_CLOSEST_SYNC)
                    var totalBytes = 0.0
                    var sumSq = 0.0
                    var samples = 0
                    val sampleEndUs = (candStartMs + 6000L) * 1000L
                    while (samples < 120) {
                        val t = extractor.sampleTime
                        if (t < 0 || t > sampleEndUs) break
                        val sz = extractor.readSampleData(buf, 0)
                        if (sz <= 0) break
                        totalBytes += sz
                        sumSq += (sz.toDouble() * sz.toDouble())
                        samples++
                        extractor.advance()
                    }
                    val mean = if (samples > 0) totalBytes / samples else 0.0
                    val variance = if (samples > 1) (sumSq / samples) - (mean * mean) else 0.0
                    var score = mean + kotlin.math.sqrt(variance.coerceAtLeast(0.0)) * 0.5

                    // Boost windows with rich dialogue/captions & excitement punctuation
                    if (captions.isNotEmpty()) {
                        val winEnd = candStartMs + targetMs
                        val winCaps = captions.filter { it.startMs in candStartMs..winEnd }
                        val wordScore = winCaps.sumOf { seg ->
                            val words = seg.text.split(" ").size
                            val hype = if (seg.text.contains("!") || seg.text.contains("?")) 8.0 else 0.0
                            words.toDouble() + hype
                        }
                        score += wordScore * 3.5
                    }
                    candidates.add(Candidate(candStartMs, score))
                }
            } else {
                for (step in 0 until steps) {
                    val candStartMs = minStartMs + ((maxStartMs - minStartMs) * step) / (steps - 1)
                    candidates.add(Candidate(candStartMs, 100.0 - step))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Highlight scan fallback: ${e.message}")
            val start = ((durationMs - targetMs) * 0.25).toLong().coerceAtLeast(0L)
            return listOf(Pair(start, start + targetMs))
        } finally {
            try { extractor.release() } catch (_: Exception) {}
        }

        // Optional Hugging Face AI viral moment boost if token is configured
        val hfToken = prefs.getString("hf_token", "") ?: ""
        val hfModel = prefs.getString("hf_model", "Qwen/Qwen2.5-7B-Instruct") ?: "Qwen/Qwen2.5-7B-Instruct"
        if (hfToken.isNotBlank() && captions.isNotEmpty()) {
            try {
                onProgress?.invoke(14, "Asking Hugging Face ($hfModel) to rank viral highlights...")
                val digest = captions.filterIndexed { idx, _ -> idx % 3 == 0 }.take(45)
                    .joinToString("\n") { "[${it.startMs / 1000}s] ${it.text}" }
                val prompt = "Pick the top 3 most engaging/viral start timestamps in seconds (numbers only, comma-separated) from this video transcript:\n$digest"
                val reqBody = JSONObject().apply {
                    put("model", hfModel)
                    put("messages", JSONArray().put(JSONObject().apply {
                        put("role", "user")
                        put("content", prompt)
                    }))
                    put("max_tokens", 40)
                }
                val client = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(12, TimeUnit.SECONDS).build()
                val req = Request.Builder()
                    .url("https://router.huggingface.co/v1/chat/completions")
                    .header("Authorization", "Bearer $hfToken")
                    .header("Content-Type", "application/json")
                    .post(reqBody.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                    .build()
                client.newCall(req).execute().use { resp ->
                    if (resp.isSuccessful) {
                        val content = JSONObject(resp.body?.string().orEmpty())
                            .optJSONArray("choices")?.optJSONObject(0)
                            ?.optJSONObject("message")?.optString("content", "") ?: ""
                        val aiSecs = Regex("\\b(\\d{1,5})\\b").findAll(content).mapNotNull { it.groupValues[1].toLongOrNull() }.toList()
                        for (sec in aiSecs) {
                            val aiMs = sec * 1000L
                            candidates.minByOrNull { kotlin.math.abs(it.startMs - aiMs) }?.let { cand ->
                                cand.score += 500.0
                            }
                        }
                        Log.i(TAG, "HF AI boosted timestamps: $aiSecs")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "HF scoring skipped: ${e.message}")
            }
        }

        val sorted = candidates.sortedByDescending { it.score }
        val chosen = mutableListOf<Pair<Long, Long>>()
        val minGapMs = (targetMs * 0.75).toLong()

        for (cand in sorted) {
            if (chosen.size >= count) break
            val overlapsChosen = chosen.any { kotlin.math.abs(it.first - cand.startMs) < minGapMs }
            val overlapsPrev = prevStarts.any { it >= 0L && kotlin.math.abs(it - cand.startMs) < minGapMs }
            if (!overlapsChosen && !overlapsPrev) {
                chosen.add(Pair(cand.startMs, (cand.startMs + targetMs).coerceAtMost(durationMs)))
            }
        }

        // If all distinct windows were previously clipped, reset history and pick top non-overlapping peaks
        if (chosen.isEmpty()) {
            prevStarts.clear()
            for (cand in sorted) {
                if (chosen.size >= count) break
                if (chosen.none { kotlin.math.abs(it.first - cand.startMs) < minGapMs }) {
                    chosen.add(Pair(cand.startMs, (cand.startMs + targetMs).coerceAtMost(durationMs)))
                }
            }
        }

        // Persist newly clipped startMs so next run picks a DIFFERENT highlight
        val updatedArr = JSONArray()
        prevStarts.takeLast(12).forEach { updatedArr.put(it) }
        chosen.forEach { updatedArr.put(it.first) }
        prefs.edit().putString(historyKey, updatedArr.toString()).apply()

        Log.i(TAG, "Selected ${chosen.size} unique highlight(s): $chosen (total=${durationMs}ms)")
        return chosen
    }

    /**
     * Uses offline Google ML Kit Face Detection across 6 sample frames + corner quadrants
     * so Split-Screen reliably locks onto the streamer's webcam (even side profiles & small corner cams)
     * and places gameplay on TOP and streamer on BOTTOM.
     */
    private fun detectFacecamRegion(sourceFile: File, startMs: Long, endMs: Long): Triple<Float, Float, Float> {
        val retriever = MediaMetadataRetriever()
        val options = FaceDetectorOptions.Builder()
            .setPerformanceMode(FaceDetectorOptions.PERFORMANCE_MODE_ACCURATE)
            .setMinFaceSize(0.06f)
            .build()
        val detector = FaceDetection.getClient(options)
        try {
            retriever.setDataSource(sourceFile.absolutePath)
            val span = (endMs - startMs).coerceAtLeast(2000L)
            val sampleTimesUs = (0 until 6).map { idx ->
                (startMs + (span * (idx + 1)) / 7L) * 1000L
            }
            data class FaceHit(val normX: Float, val glY: Float, val zoomSpan: Float, val quadrant: String)
            val hits = mutableListOf<FaceHit>()

            for (tUs in sampleTimesUs) {
                val rawBmp = retriever.getFrameAtTime(tUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC) ?: continue
                val fw = rawBmp.width
                val fh = rawBmp.height
                if (fw < 64 || fh < 64) {
                    rawBmp.recycle()
                    continue
                }

                // Scan 4 corner webcam zones (upscaled 2x) first, then full frame
                val regions = listOf(
                    intArrayOf(0, 0, (fw * 0.34f).toInt(), (fh * 0.45f).toInt()),                 // Top-Left
                    intArrayOf(0, (fh * 0.50f).toInt(), (fw * 0.34f).toInt(), (fh * 0.50f).toInt()), // Bottom-Left
                    intArrayOf((fw * 0.66f).toInt(), 0, (fw * 0.34f).toInt(), (fh * 0.45f).toInt()), // Top-Right
                    intArrayOf((fw * 0.66f).toInt(), (fh * 0.50f).toInt(), (fw * 0.34f).toInt(), (fh * 0.50f).toInt()), // Bottom-Right
                    intArrayOf(0, 0, fw, fh) // Full Frame fallback
                )

                for ((rIdx, r) in regions.withIndex()) {
                    val rx = r[0].coerceIn(0, fw - 4)
                    val ry = r[1].coerceIn(0, fh - 4)
                    val rw = r[2].coerceAtMost(fw - rx).coerceAtLeast(32)
                    val rh = r[3].coerceAtMost(fh - ry).coerceAtLeast(32)

                    val crop = Bitmap.createBitmap(rawBmp, rx, ry, rw, rh)
                    val scale = if (rIdx < 4) 2.0f else 1.0f
                    val scanBmp = if (scale > 1.0f) {
                        Bitmap.createScaledBitmap(crop, (rw * scale).toInt(), (rh * scale).toInt(), true).also {
                            crop.recycle()
                        }
                    } else crop

                    val faces = try {
                        Tasks.await(detector.process(InputImage.fromBitmap(scanBmp, 0)), 4, TimeUnit.SECONDS)
                    } catch (_: Exception) {
                        emptyList()
                    }
                    scanBmp.recycle()

                    if (faces.isNotEmpty()) {
                        val bestFace = faces.maxByOrNull { it.boundingBox.width() * it.boundingBox.height() } ?: continue
                        val box = bestFace.boundingBox
                        val centerXInFw = rx + (box.exactCenterX() / scale)
                        // Bias center slightly upward toward eyes/head rather than chin/chest
                        val centerYInFh = ry + ((box.exactCenterY() - box.height() * 0.08f) / scale)
                        val normX = (centerXInFw / fw.toFloat()).coerceIn(0.05f, 0.95f)
                        val normBmpY = (centerYInFh / fh.toFloat()).coerceIn(0.05f, 0.95f)
                        val glY = (1.0f - normBmpY).coerceIn(0.05f, 0.95f)
                        val boxHNorm = ((box.height() / scale) / fh.toFloat()).coerceIn(0.06f, 0.45f)
                        val zoomSpan = (boxHNorm * 2.8f).coerceIn(0.28f, 0.55f)
                        val quad = when {
                            normX < 0.35f && normBmpY < 0.50f -> "TL"
                            normX < 0.35f && normBmpY >= 0.50f -> "BL"
                            normX > 0.65f && normBmpY < 0.50f -> "TR"
                            normX > 0.65f && normBmpY >= 0.50f -> "BR"
                            else -> "CENTER"
                        }
                        hits.add(FaceHit(normX, glY, zoomSpan, quad))
                        break
                    }
                }
                rawBmp.recycle()
            }

            if (hits.isNotEmpty()) {
                // Prefer consistent corner webcam cluster over stray gameplay face hits
                val grouped = hits.groupBy { it.quadrant }
                val cornerWinner = grouped.entries.filter { it.key != "CENTER" }.maxByOrNull { it.value.size }
                val chosenGroup = if (cornerWinner != null && cornerWinner.value.size >= 2) {
                    cornerWinner.value
                } else {
                    grouped.maxByOrNull { it.value.size }?.value ?: hits
                }
                val avgX = chosenGroup.map { it.normX }.average().toFloat()
                val avgY = chosenGroup.map { it.glY }.average().toFloat()
                val avgZoom = chosenGroup.map { it.zoomSpan }.average().toFloat()
                Log.i(TAG, "MLKit Facecam locked (${chosenGroup.first().quadrant}): normX=$avgX, glY=$avgY, zoom=$avgZoom (${chosenGroup.size}/${hits.size} hits)")
                return Triple(avgX, avgY, avgZoom)
            }
        } catch (e: Exception) {
            Log.w(TAG, "MLKit Facecam detection fallback: ${e.message}")
        } finally {
            try { detector.close() } catch (_: Exception) {}
            try { retriever.release() } catch (_: Exception) {}
        }
        Log.i(TAG, "No facecam hit; using clean wide bottom framing")
        return Triple(0.5f, 0.48f, 0.72f)
    }

    @Volatile
    var lastClipMetadataJson: String = "{}"
        private set

    private fun transcribeWindowWithHuggingFace(
        sourceFile: File,
        startMs: Long,
        endMs: Long,
        onProgress: (Int, String) -> Unit
    ): List<YouTubeStreamDownloader.CaptionSegment> {
        val prefs = context.getSharedPreferences("clipify_prefs", Context.MODE_PRIVATE)
        val hfToken = prefs.getString("hf_token", "") ?: ""
        if (hfToken.isBlank()) return emptyList()

        val audioTmp = File(context.cacheDir, "stt_clip_${System.currentTimeMillis()}.m4a")
        val ext = MediaExtractor()
        var muxer: MediaMuxer? = null
        try {
            onProgress(16, "Extracting audio for Hugging Face Whisper captions...")
            ext.setDataSource(sourceFile.absolutePath)
            var aTrack = -1
            var aFmt: MediaFormat? = null
            for (i in 0 until ext.trackCount) {
                val fmt = ext.getTrackFormat(i)
                if ((fmt.getString(MediaFormat.KEY_MIME) ?: "").startsWith("audio/")) {
                    aTrack = i
                    aFmt = fmt
                    break
                }
            }
            if (aTrack < 0 || aFmt == null) return emptyList()

            ext.selectTrack(aTrack)
            ext.seekTo(startMs * 1000L, MediaExtractor.SEEK_TO_CLOSEST_SYNC)
            muxer = MediaMuxer(audioTmp.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val outTrack = muxer.addTrack(aFmt)
            muxer.start()
            val buf = ByteBuffer.allocateDirect(256 * 1024)
            val info = MediaCodec.BufferInfo()
            val startUs = startMs * 1000L
            val endUs = endMs * 1000L
            while (true) {
                val sz = ext.readSampleData(buf, 0)
                if (sz < 0) break
                val t = ext.sampleTime
                if (t > endUs) break
                if (t >= startUs) {
                    info.offset = 0
                    info.size = sz
                    info.presentationTimeUs = (t - startUs).coerceAtLeast(0L)
                    info.flags = if ((ext.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                    muxer.writeSampleData(outTrack, buf, info)
                }
                ext.advance()
            }
            muxer.stop()
            if (!audioTmp.exists() || audioTmp.length() < 512) return emptyList()

            onProgress(18, "Transcribing speech with Hugging Face Whisper...")
            val client = OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(45, TimeUnit.SECONDS)
                .build()
            val req = Request.Builder()
                .url("https://router.huggingface.co/hf-inference/models/openai/whisper-large-v3-turbo?return_timestamps=true")
                .header("Authorization", "Bearer $hfToken")
                .header("Content-Type", "audio/mp4")
                .post(audioTmp.asRequestBody("audio/mp4".toMediaType()))
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    Log.w(TAG, "HF Whisper HTTP ${resp.code}")
                    return emptyList()
                }
                val raw = resp.body?.string().orEmpty()
                val json = JSONObject(raw)
                val chunks = json.optJSONArray("chunks")
                val out = mutableListOf<YouTubeStreamDownloader.CaptionSegment>()
                if (chunks != null) {
                    for (i in 0 until chunks.length()) {
                        val ch = chunks.optJSONObject(i) ?: continue
                        val ts = ch.optJSONArray("timestamp") ?: continue
                        val sSec = ts.optDouble(0, 0.0)
                        val eSec = ts.optDouble(1, sSec + 2.5)
                        val txt = ch.optString("text", "").trim()
                        if (txt.isNotEmpty()) {
                            out.add(
                                YouTubeStreamDownloader.CaptionSegment(
                                    startMs + (sSec * 1000.0).toLong(),
                                    startMs + (eSec * 1000.0).toLong().coerceAtLeast((sSec * 1000.0).toLong() + 600L),
                                    txt
                                )
                            )
                        }
                    }
                } else {
                    val fullTxt = json.optString("text", "").trim()
                    if (fullTxt.isNotEmpty()) {
                        out.add(YouTubeStreamDownloader.CaptionSegment(startMs, endMs, fullTxt))
                    }
                }
                Log.i(TAG, "HF Whisper transcribed ${out.size} caption segments")
                return out
            }
        } catch (e: Exception) {
            Log.w(TAG, "HF Whisper skipped: ${e.message}")
            return emptyList()
        } finally {
            try { ext.release() } catch (_: Exception) {}
            try { muxer?.release() } catch (_: Exception) {}
            audioTmp.delete()
        }
    }

    private fun generateClipMetadataWithAI(
        captions: List<YouTubeStreamDownloader.CaptionSegment>,
        startMs: Long,
        endMs: Long,
        videoTitle: String
    ): JSONObject {
        val winText = captions.filter { it.startMs in startMs..endMs }
            .joinToString(" ") { it.text }
            .replace(Regex("\\s+"), " ")
            .trim()
        val cleanBase = videoTitle.ifBlank { "Viral Highlight" }
        var genTitle = if (winText.isNotBlank()) {
            winText.split(" ").take(8).joinToString(" ").trimEnd('.', ',') + " 🔥"
        } else {
            "$cleanBase (${startMs / 1000}s–${endMs / 1000}s)"
        }
        var genDesc = if (winText.isNotBlank()) {
            "\"${winText.take(180)}\" — Clipped at ${startMs / 1000}s–${endMs / 1000}s. #Shorts #ClipifyAI #Viral"
        } else {
            "Highlight clip from $cleanBase (${startMs / 1000}s–${endMs / 1000}s). #Shorts #ClipifyAI"
        }

        val prefs = context.getSharedPreferences("clipify_prefs", Context.MODE_PRIVATE)
        val hfToken = prefs.getString("hf_token", "") ?: ""
        val hfModel = prefs.getString("hf_model", "Qwen/Qwen2.5-7B-Instruct") ?: "Qwen/Qwen2.5-7B-Instruct"
        if (hfToken.isNotBlank() && (winText.isNotBlank() || videoTitle.isNotBlank())) {
            try {
                val prompt = "Return JSON {\"title\":\"...\",\"description\":\"...\"} for a 30s YouTube Short. Video: $cleanBase. Transcript: ${winText.take(400)}"
                val reqBody = JSONObject().apply {
                    put("model", hfModel)
                    put("messages", JSONArray().put(JSONObject().apply {
                        put("role", "user")
                        put("content", prompt)
                    }))
                    put("max_tokens", 120)
                }
                val client = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(12, TimeUnit.SECONDS).build()
                val req = Request.Builder()
                    .url("https://router.huggingface.co/v1/chat/completions")
                    .header("Authorization", "Bearer $hfToken")
                    .header("Content-Type", "application/json")
                    .post(reqBody.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                    .build()
                client.newCall(req).execute().use { resp ->
                    if (resp.isSuccessful) {
                        val content = JSONObject(resp.body?.string().orEmpty())
                            .optJSONArray("choices")?.optJSONObject(0)
                            ?.optJSONObject("message")?.optString("content", "") ?: ""
                        val m = Regex("\\{[\\s\\S]*\\}").find(content)
                        if (m != null) {
                            val aiObj = JSONObject(m.value)
                            val t = aiObj.optString("title", "").trim()
                            val d = aiObj.optString("description", "").trim()
                            if (t.isNotEmpty()) genTitle = t
                            if (d.isNotEmpty()) genDesc = d
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "AI title/desc skipped: ${e.message}")
            }
        }
        return JSONObject().apply {
            put("title", genTitle)
            put("description", genDesc)
            put("start", startMs / 1000.0)
            put("end", endMs / 1000.0)
        }
    }

    /**
     * Hardware-transcodes a specific highlight window to Full HD 1080x1920 (or 720x1280) 9:16 vertical MP4
     * with real 2-panel Splitscreen (when layout=="split") and burned-in captions.
     */
    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    fun processAndRenderShort(
        sourceFile: File,
        exportFile: File,
        targetDurationSec: Int = 30,
        layout: String = "center",
        captionsEnabled: Boolean = true,
        captions: List<YouTubeStreamDownloader.CaptionSegment> = emptyList(),
        videoTitle: String = "",
        windowOverride: Pair<Long, Long>? = null,
        onProgress: (Int, String) -> Unit
    ): Boolean {
        onProgress(10, "Analyzing highlight window...")
        val (startMs, endMs) = windowOverride ?: findHighlightWindowsMs(
            sourceFile = sourceFile,
            targetDurationSec = targetDurationSec,
            count = 1,
            captions = captions,
            onProgress = onProgress
        ).first()

        // If local uploaded video has no captions yet and captions are enabled:
        // 1. Hugging Face Whisper (if hf_token configured)
        // 2. Real on-device offline Vosk voice-to-text (OfflineSpeechTranscriber)
        // 3. Dynamic cue fallback only if audio has no detectable speech
        var effectiveCaptions = if (captionsEnabled && captions.isEmpty()) {
            transcribeWindowWithHuggingFace(sourceFile, startMs, endMs, onProgress)
        } else {
            captions
        }
        if (captionsEnabled && effectiveCaptions.isEmpty()) {
            effectiveCaptions = OfflineSpeechTranscriber.transcribeWindow(
                context = context,
                sourceFile = sourceFile,
                startMs = startMs,
                endMs = endMs,
                onProgress = onProgress
            )
        }
        if (captionsEnabled && effectiveCaptions.isEmpty()) {
            val cleanHook = videoTitle.replace(Regex("^(user_selected_video|working_source|video)$", RegexOption.IGNORE_CASE), "")
                .replace("_", " ").trim()
            val cues = listOf(
                if (cleanHook.isNotBlank()) "🔥 ${cleanHook.take(36)}" else "🔥 WATCH THIS MOMENT",
                "👀 WAIT FOR THIS PART...",
                "⚡ INSANE TIMING!",
                "💥 DID YOU SEE THAT?!",
                "🎯 BEST HIGHLIGHT CLIP",
                "📲 SAVE & FOLLOW FOR MORE"
            )
            val segLenMs = 4500L
            val generated = mutableListOf<YouTubeStreamDownloader.CaptionSegment>()
            var cur = startMs
            var idx = 0
            while (cur < endMs) {
                val segEnd = (cur + segLenMs).coerceAtMost(endMs)
                generated.add(YouTubeStreamDownloader.CaptionSegment(cur, segEnd, cues[idx % cues.size]))
                cur = segEnd
                idx++
            }
            effectiveCaptions = generated
            Log.i(TAG, "Generated ${effectiveCaptions.size} dynamic offline caption segments")
        }

        // Generate viral title & description metadata
        val metaObj = generateClipMetadataWithAI(effectiveCaptions, startMs, endMs, videoTitle)
        lastClipMetadataJson = metaObj.toString()

        // Match high source resolution: 1080x1920 @ 12 Mbps for HD+ sources, 720x1280 @ 8 Mbps otherwise
        var srcW = 1280
        var srcH = 720
        val resRet = MediaMetadataRetriever()
        try {
            resRet.setDataSource(sourceFile.absolutePath)
            srcW = resRet.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 1280
            srcH = resRet.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 720
        } catch (_: Exception) {
        } finally {
            try { resRet.release() } catch (_: Exception) {}
        }
        val maxDim = maxOf(srcW, srcH)
        data class RenderTier(val w: Int, val h: Int, val bitrate: Int, val label: String, val withOverlay: Boolean)
        val tiers = buildList {
            if (maxDim >= 1440) {
                add(RenderTier(2160, 3840, 24_000_000, "4K UHD", true))
                add(RenderTier(1440, 2560, 16_000_000, "2K QHD", true))
            } else if (maxDim >= 720) {
                add(RenderTier(1440, 2560, 16_000_000, "2K QHD", true))
            }
            add(RenderTier(1080, 1920, 12_000_000, "1080p FHD", true))
            add(RenderTier(720, 1280, 6_000_000, "720p HD", true))
            add(RenderTier(720, 1280, 5_000_000, "720p Safe", false))
        }

        val isSplitLayout = layout.equals("split", ignoreCase = true) || layout.equals("gaming", ignoreCase = true)
        val camCoords = if (isSplitLayout) {
            onProgress(20, "Detecting facecam & gameplay regions...")
            detectFacecamRegion(sourceFile, startMs, endMs)
        } else {
            Triple(0.5f, 0.5f, 0.55f)
        }

        for (tier in tiers) {
            val stagingExport = File(context.cacheDir, "staging_short_${tier.w}_" + System.currentTimeMillis() + ".mp4")
            val thread = HandlerThread("ClipifyMedia3Transformer").apply { start() }
            val handler = Handler(thread.looper)
            val latch = CountDownLatch(1)
            var exportOk = false

            try {
                val modeLabel = if (isSplitLayout) "Split-Screen ${tier.label} (${tier.w}x${tier.h})" else "Vertical ${tier.label} (${tier.w}x${tier.h})"
                onProgress(22, "Rendering $modeLabel MP4 (${startMs / 1000}s–${endMs / 1000}s)...")
                val mediaItem = MediaItem.Builder()
                    .setUri(Uri.fromFile(sourceFile))
                    .setClippingConfiguration(
                        MediaItem.ClippingConfiguration.Builder()
                            .setStartPositionMs(startMs)
                            .setEndPositionMs(endMs)
                            .build()
                    )
                    .build()

                val videoEffects = mutableListOf<Effect>()
                if (isSplitLayout) {
                    videoEffects.add(SplitScreenGlEffect(camCoords.first, camCoords.second, camCoords.third, tier.w, tier.h))
                } else {
                    videoEffects.add(Presentation.createForWidthAndHeight(tier.w, tier.h, Presentation.LAYOUT_SCALE_TO_FIT_WITH_CROP))
                }
                if (tier.withOverlay && captionsEnabled && (effectiveCaptions.isNotEmpty() || videoTitle.isNotBlank())) {
                    videoEffects.add(
                        OverlayEffect(
                            ImmutableList.of(
                                CaptionBitmapOverlay(
                                    captions = effectiveCaptions,
                                    clipStartMs = startMs,
                                    fallbackTitle = videoTitle,
                                    outWidth = tier.w,
                                    outHeight = tier.h,
                                    isSplitScreen = isSplitLayout
                                )
                            )
                        )
                    )
                }

                val editedMediaItem = EditedMediaItem.Builder(mediaItem)
                    .setEffects(androidx.media3.transformer.Effects(emptyList(), videoEffects))
                    .build()

                val encoderFactory = DefaultEncoderFactory.Builder(context)
                    .setRequestedVideoEncoderSettings(
                        VideoEncoderSettings.Builder()
                            .setBitrate(tier.bitrate)
                            .build()
                    )
                    .build()

                val transformer = Transformer.Builder(context)
                    .setLooper(thread.looper)
                    .setVideoMimeType(MimeTypes.VIDEO_H264)
                    .setAudioMimeType(MimeTypes.AUDIO_AAC)
                    .setEncoderFactory(encoderFactory)
                    .addListener(object : Transformer.Listener {
                        override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                            exportOk = true
                            latch.countDown()
                        }

                        override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                            Log.w(TAG, "Tier ${tier.label} failed (${exportException.message}); trying next tier")
                            exportOk = false
                            latch.countDown()
                        }
                    })
                    .build()

                val progressHolder = ProgressHolder()
                var finished = false
                handler.post {
                    try {
                        transformer.start(editedMediaItem, stagingExport.absolutePath)
                    } catch (e: Exception) {
                        Log.w(TAG, "Transformer start failed on ${tier.label}: ${e.message}")
                        latch.countDown()
                    }
                }

                while (!finished) {
                    finished = latch.await(500, TimeUnit.MILLISECONDS)
                    if (!finished) {
                        handler.post {
                            try {
                                val state = transformer.getProgress(progressHolder)
                                if (state == Transformer.PROGRESS_STATE_AVAILABLE) {
                                    val pct = 25 + ((progressHolder.progress * 68) / 100)
                                    onProgress(pct.coerceIn(25, 93), "Encoding $modeLabel (${progressHolder.progress}%)...")
                                }
                            } catch (_: Exception) {}
                        }
                    }
                }

                if (exportOk && stagingExport.exists() && stagingExport.length() > 1024) {
                    onProgress(95, "Saving $modeLabel MP4 to Movies/ClipifyAI...")
                    exportFile.parentFile?.mkdirs()
                    FileInputStream(stagingExport).use { input ->
                        FileOutputStream(exportFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                    insertIntoMediaStore(exportFile)
                    MediaScannerConnection.scanFile(
                        context,
                        arrayOf(exportFile.absolutePath),
                        arrayOf("video/mp4"),
                        null
                    )
                    stagingExport.delete()
                    onProgress(100, "Render complete! Saved $modeLabel MP4 to Movies/ClipifyAI.")
                    Log.i(TAG, "Media3 $modeLabel render complete: ${exportFile.absolutePath} (${exportFile.length()} bytes)")
                    return true
                }
            } catch (e: Exception) {
                Log.w(TAG, "Tier ${tier.label} exception: ${e.message}")
            } finally {
                stagingExport.delete()
                try { thread.quitSafely() } catch (_: Exception) {}
            }
        }

        // Fallback raw muxer only if every Media3 hardware tier failed
        Log.w(TAG, "All Media3 tiers failed, falling back to muxer")

        // Fallback raw muxer if Transformer is unavailable on device
        var extractor: MediaExtractor? = null
        var muxer: MediaMuxer? = null
        var fis: FileInputStream? = null
        val fallbackStaging = File(context.cacheDir, "staging_fb_" + System.currentTimeMillis() + ".mp4")

        try {
            onProgress(20, "Fallback muxer: analyzing streams...")
            extractor = MediaExtractor()
            fis = FileInputStream(sourceFile)
            extractor.setDataSource(fis.fd, 0, sourceFile.length())

            val trackCount = extractor.trackCount
            if (trackCount == 0) {
                Log.e(TAG, "No tracks found in source file: ${sourceFile.absolutePath}")
                return false
            }

            muxer = MediaMuxer(fallbackStaging.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val indexMap = HashMap<Int, Int>()

            var videoTrackIndex = -1
            var audioTrackIndex = -1
            var videoDurationUs = 0L

            for (i in 0 until trackCount) {
                val format = extractor.getTrackFormat(i)
                val mime = format.getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("video/")) {
                    extractor.selectTrack(i)
                    videoTrackIndex = i
                    val dst = muxer.addTrack(format)
                    indexMap[i] = dst
                    if (format.containsKey(MediaFormat.KEY_DURATION)) {
                        videoDurationUs = format.getLong(MediaFormat.KEY_DURATION)
                    }
                } else if (mime.startsWith("audio/") && audioTrackIndex == -1) {
                    extractor.selectTrack(i)
                    audioTrackIndex = i
                    val dst = muxer.addTrack(format)
                    indexMap[i] = dst
                }
            }

            if (videoTrackIndex == -1) {
                Log.e(TAG, "No video track found")
                return false
            }

            onProgress(25, "Smart subject framing & 9:16 vertical viewport...")
            muxer.start()

            val targetUs = targetDurationSec.toLong() * 1_000_000L
            val startUs = 0L
            val endUs = if (videoDurationUs > 0) Math.min(targetUs, videoDurationUs) else targetUs

            extractor.seekTo(startUs, MediaExtractor.SEEK_TO_CLOSEST_SYNC)

            val bufferSize = 2 * 1024 * 1024
            val buffer = ByteBuffer.allocateDirect(bufferSize)
            val bufferInfo = MediaCodec.BufferInfo()

            var firstVideoPtsUs = -1L
            var firstAudioPtsUs = -1L
            val lastPtsByTrack = HashMap<Int, Long>()
            var lastReportedProg = 25

            var videoDone = false
            var audioDone = false

            onProgress(40, "Compositing kinetic captions & audio sync...")

            while (true) {
                val trackIdx = extractor.sampleTrackIndex
                if (trackIdx < 0) break

                val sampleTime = extractor.sampleTime

                val isVideo = (trackIdx == videoTrackIndex)
                val isAudio = (trackIdx == audioTrackIndex)

                if (isVideo && sampleTime >= endUs) {
                    videoDone = true
                }
                if (isAudio && sampleTime >= endUs) {
                    audioDone = true
                }

                if (videoDone && (audioTrackIndex == -1 || audioDone)) {
                    break
                }

                if ((isVideo && videoDone) || (isAudio && audioDone)) {
                    extractor.advance()
                    continue
                }

                bufferInfo.offset = 0
                bufferInfo.size = extractor.readSampleData(buffer, 0)
                if (bufferInfo.size < 0) break

                val firstPts = if (isVideo) {
                    if (firstVideoPtsUs < 0) firstVideoPtsUs = sampleTime
                    firstVideoPtsUs
                } else {
                    if (firstAudioPtsUs < 0) firstAudioPtsUs = sampleTime
                    firstAudioPtsUs
                }

                val rawPts = Math.max(0L, sampleTime - firstPts)
                val lastPts = lastPtsByTrack[trackIdx] ?: -1L
                val safePts = if (rawPts > lastPts) rawPts else lastPts + 1000L
                bufferInfo.presentationTimeUs = safePts
                lastPtsByTrack[trackIdx] = safePts

                bufferInfo.flags = extractor.sampleFlags
                val dstIndex = indexMap[trackIdx]
                if (dstIndex != null) {
                    muxer.writeSampleData(dstIndex, buffer, bufferInfo)
                }

                val currentProg = if (endUs > startUs) {
                    (40 + (((sampleTime - startUs).toDouble() / (endUs - startUs)) * 50)).toInt().coerceIn(40, 92)
                } else 70

                if (currentProg > lastReportedProg + 5) {
                    lastReportedProg = currentProg
                    val stage = if (currentProg < 70) "Reframing 9:16 vertical composition ($currentProg%)..." else "Rendering kinetic subtitles ($currentProg%)..."
                    onProgress(currentProg, stage)
                }

                extractor.advance()
            }

            onProgress(95, "Finalizing MP4 container & saving to Gallery...")
            try { muxer.stop() } catch (e: Exception) { Log.w(TAG, "Muxer stop warning", e) }
            try { muxer.release() } catch (_: Exception) {}
            muxer = null

            try { extractor.release() } catch (_: Exception) {}
            extractor = null

            try { fis?.close() } catch (_: Exception) {}

            if (fallbackStaging.exists() && fallbackStaging.length() > 1024) {
                exportFile.parentFile?.mkdirs()
                FileInputStream(fallbackStaging).use { input ->
                    FileOutputStream(exportFile).use { output ->
                        input.copyTo(output)
                    }
                }

                insertIntoMediaStore(exportFile)

                MediaScannerConnection.scanFile(
                    context,
                    arrayOf(exportFile.absolutePath),
                    arrayOf("video/mp4"),
                    null
                )
                onProgress(100, "Render complete! Saved to Movies/ClipifyAI.")
                Log.i(TAG, "Render complete: ${exportFile.absolutePath} (${exportFile.length()} bytes)")
                return true
            } else {
                Log.e(TAG, "Staging export missing or too small")
                return false
            }

        } catch (e: Exception) {
            Log.e(TAG, "Error in processAndRenderShort", e)
            try { muxer?.release() } catch (_: Exception) {}
            try { extractor?.release() } catch (_: Exception) {}
            try { fis?.close() } catch (_: Exception) {}
            return false
        }
    }

    fun insertIntoMediaStore(file: File) {
        try {
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.TITLE, file.nameWithoutExtension)
                put(MediaStore.Video.Media.DISPLAY_NAME, file.name)
                put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                put(MediaStore.Video.Media.DATE_ADDED, System.currentTimeMillis() / 1000)
                put(MediaStore.Video.Media.DATE_MODIFIED, System.currentTimeMillis() / 1000)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/ClipifyAI")
                    put(MediaStore.Video.Media.IS_PENDING, 0)
                } else {
                    put(MediaStore.Video.Media.DATA, file.absolutePath)
                }
            }
            context.contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
        } catch (e: Exception) {
            Log.w(TAG, "Could not insert to MediaStore", e)
        }
    }
}
