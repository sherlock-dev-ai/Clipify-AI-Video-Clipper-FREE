package dev.sherlock.clipifyai.network

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

object YouTubeStreamDownloader {
    private const val TAG = "YouTubeStreamDownloader"

    data class CaptionSegment(
        val startMs: Long,
        val endMs: Long,
        val text: String
    )

    data class DownloadResult(
        val ok: Boolean,
        val title: String = "",
        val file: File? = null,
        val captions: List<CaptionSegment> = emptyList(),
        val width: Int = 0,
        val height: Int = 0,
        val error: String = ""
    )

    data class LiveStreamInfo(
        val ok: Boolean,
        val title: String = "",
        val hlsManifestUrl: String? = null,
        val directStreamUrl: String? = null,
        val isLive: Boolean = false,
        val error: String = ""
    )

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    fun extractVideoId(url: String): String? {
        val patterns = listOf(
            "(?:v=|/v/|youtu\\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})"
        )
        for (p in patterns) {
            val m = Pattern.compile(p).matcher(url)
            if (m.find()) return m.group(1)
        }
        return null
    }

    fun isYouTubeUrl(url: String): Boolean {
        val lower = url.lowercase()
        return lower.contains("youtube.com") || lower.contains("youtu.be")
    }

    private fun fetchPlayerJsonForClient(
        videoId: String,
        clientName: String,
        clientVer: String,
        userAgent: String
    ): Pair<JSONObject?, String> {
        return try {
            val clientObj = JSONObject().apply {
                put("clientName", clientName)
                put("clientVersion", clientVer)
                put("hl", "en")
                put("gl", "US")
                if (clientName == "ANDROID") {
                    put("androidSdkVersion", 34)
                } else if (clientName == "IOS") {
                    put("deviceMake", "Apple")
                    put("deviceModel", "iPhone16,2")
                }
            }
            val payload = JSONObject().apply {
                put("videoId", videoId)
                put("context", JSONObject().apply { put("client", clientObj) })
                put("contentCheckOk", true)
                put("racyCheckOk", true)
            }
            val req = Request.Builder()
                .url("https://www.youtube.com/youtubei/v1/player?prettyPrint=false")
                .header("User-Agent", userAgent)
                .header("Content-Type", "application/json")
                .post(payload.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                .build()

            client.newCall(req).execute().use { resp ->
                val bodyStr = resp.body?.string() ?: ""
                if (resp.isSuccessful && bodyStr.isNotEmpty()) {
                    val json = JSONObject(bodyStr)
                    val playability = json.optJSONObject("playabilityStatus")
                    val status = playability?.optString("status", "") ?: ""
                    val reason = playability?.optString("reason", "") ?: ""
                    val streamingData = json.optJSONObject("streamingData")
                    if (streamingData != null) {
                        return Pair(json, userAgent)
                    } else {
                        Log.w(TAG, "$clientName status=$status reason=$reason")
                        return Pair(null, reason)
                    }
                }
            }
            Pair(null, "")
        } catch (e: Exception) {
            Log.w(TAG, "$clientName player fetch failed: ${e.message}")
            Pair(null, e.message ?: "")
        }
    }

    private fun fetchPlayerJson(videoId: String): Pair<JSONObject?, String> {
        val clients = listOf(
            Triple("ANDROID", "20.10.38", "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip"),
            Triple("IOS", "20.10.4", "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"),
            Triple("ANDROID_VR", "1.60.19", "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip")
        )
        var lastReason = ""
        for ((clientName, clientVer, userAgent) in clients) {
            val (json, reasonOrUa) = fetchPlayerJsonForClient(videoId, clientName, clientVer, userAgent)
            if (json != null) return Pair(json, reasonOrUa)
            if (reasonOrUa.isNotEmpty()) lastReason = reasonOrUa
        }
        return Pair(null, lastReason)
    }

    fun resolveLiveStream(url: String): LiveStreamInfo {
        val videoId = extractVideoId(url)
            ?: return LiveStreamInfo(ok = false, error = "Invalid YouTube live URL.")
        val (json, reasonOrUa) = fetchPlayerJson(videoId)
        if (json == null) {
            return LiveStreamInfo(ok = false, error = reasonOrUa.ifEmpty { "Could not resolve live stream." })
        }
        val vd = json.optJSONObject("videoDetails")
        val title = vd?.optString("title", "YouTube Live") ?: "YouTube Live"
        val isLive = vd?.optBoolean("isLive", false) ?: false
        val sd = json.optJSONObject("streamingData")
        val hlsUrl = sd?.optString("hlsManifestUrl", "")?.takeIf { it.isNotEmpty() }
        var directUrl: String? = null
        val formats = sd?.optJSONArray("formats")
        if (formats != null) {
            var bestH = -1
            for (i in 0 until formats.length()) {
                val f = formats.optJSONObject(i) ?: continue
                val u = f.optString("url", "")
                val mime = f.optString("mimeType", "")
                val h = f.optInt("height", 0)
                if (u.isNotEmpty() && mime.contains("video/mp4") && h >= bestH) {
                    bestH = h
                    directUrl = u
                }
            }
        }
        if (hlsUrl == null && directUrl == null) {
            return LiveStreamInfo(ok = false, error = "No playable live or VOD stream found.")
        }
        return LiveStreamInfo(
            ok = true,
            title = title,
            hlsManifestUrl = hlsUrl,
            directStreamUrl = directUrl,
            isLive = isLive
        )
    }

    private fun fetchCaptions(json: JSONObject, userAgent: String): List<CaptionSegment> {
        val result = mutableListOf<CaptionSegment>()
        try {
            val captionsObj = json.optJSONObject("captions") ?: return result
            val renderer = captionsObj.optJSONObject("playerCaptionsTracklistRenderer") ?: return result
            val tracks = renderer.optJSONArray("captionTracks") ?: return result
            var chosenUrl: String? = null
            for (i in 0 until tracks.length()) {
                val t = tracks.optJSONObject(i) ?: continue
                val lang = t.optString("languageCode", "")
                val base = t.optString("baseUrl", "")
                if (base.isNotEmpty()) {
                    if (lang.startsWith("en")) {
                        chosenUrl = base
                        break
                    }
                    if (chosenUrl == null) chosenUrl = base
                }
            }
            if (chosenUrl == null) return result
            val jsonUrl = if (chosenUrl.contains("fmt=")) {
                chosenUrl.replace(Regex("fmt=[^&]+"), "fmt=json3")
            } else {
                "$chosenUrl&fmt=json3"
            }
            val req = Request.Builder().url(jsonUrl).header("User-Agent", userAgent).get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return result
                val raw = resp.body?.string() ?: return result
                val root = JSONObject(raw)
                val events = root.optJSONArray("events") ?: return result
                for (i in 0 until events.length()) {
                    val ev = events.optJSONObject(i) ?: continue
                    val startMs = ev.optLong("tStartMs", -1L)
                    val durMs = ev.optLong("dDurationMs", 2500L).coerceAtLeast(500L)
                    if (startMs < 0L) continue
                    val segs = ev.optJSONArray("segs") ?: continue
                    val sb = StringBuilder()
                    for (j in 0 until segs.length()) {
                        val s = segs.optJSONObject(j)?.optString("utf8", "") ?: ""
                        sb.append(s)
                    }
                    val txt = sb.toString().replace("\n", " ").replace(Regex("\\s+"), " ").trim()
                    if (txt.isNotEmpty() && !txt.startsWith("[")) {
                        result.add(CaptionSegment(startMs, startMs + durMs, txt))
                    }
                }
            }
            Log.i(TAG, "Fetched ${result.size} caption segments")
        } catch (e: Exception) {
            Log.w(TAG, "Caption fetch skipped: ${e.message}")
        }
        return result
    }

    private var lastHttpError: String = ""

    private fun downloadPlainGet(
        streamUrl: String,
        targetFile: File,
        userAgent: String,
        pctStart: Int,
        pctSpan: Int,
        label: String,
        onProgress: (Int, String) -> Unit
    ): Boolean {
        return try {
            if (targetFile.exists()) targetFile.delete()
            targetFile.parentFile?.mkdirs()
            val req = Request.Builder()
                .url(streamUrl)
                .header("User-Agent", userAgent)
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    lastHttpError = "HTTP ${resp.code}"
                    Log.w(TAG, "$label plain GET failed HTTP ${resp.code}")
                    return false
                }
                val cl = resp.body?.contentLength() ?: -1L
                val body = resp.body ?: return false
                var offset = 0L
                var lastEmitMs = 0L
                FileOutputStream(targetFile).use { output ->
                    val buf = ByteArray(64 * 1024)
                    body.byteStream().use { input ->
                        while (true) {
                            val read = input.read(buf)
                            if (read == -1) break
                            output.write(buf, 0, read)
                            offset += read
                            val now = System.currentTimeMillis()
                            if (now - lastEmitMs >= 450L) {
                                lastEmitMs = now
                                val mbDone = String.format("%.1f", offset / (1024.0 * 1024.0))
                                if (cl > 0) {
                                    val pct = pctStart + ((offset * pctSpan) / cl).toInt()
                                    val mbTotal = String.format("%.1f", cl / (1024.0 * 1024.0))
                                    onProgress(pct.coerceAtMost(pctStart + pctSpan), "$label ($mbDone / $mbTotal MB)")
                                } else {
                                    onProgress(pctStart + (pctSpan / 2), "$label ($mbDone MB)")
                                }
                            }
                        }
                    }
                }
            }
            targetFile.exists() && targetFile.length() > 1024
        } catch (e: Exception) {
            lastHttpError = e.message ?: "Network error"
            Log.w(TAG, "$label plain GET error: ${e.message}")
            false
        }
    }

    private fun downloadToFile(
        streamUrl: String,
        targetFile: File,
        userAgent: String,
        pctStart: Int,
        pctSpan: Int,
        label: String,
        onProgress: (Int, String) -> Unit
    ): Boolean {
        targetFile.parentFile?.mkdirs()
        if (targetFile.exists()) targetFile.delete()
        val chunkSize = 2L * 1024L * 1024L
        var offset = 0L
        var totalBytes = -1L
        var lastEmitMs = 0L
        var chunkedOk = false

        try {
            FileOutputStream(targetFile).use { output ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val endByte = offset + chunkSize - 1L
                    var gotBytes = 0L
                    var done = false
                    var failedChunk = false

                    for (attempt in 0 until 4) {
                        gotBytes = 0L
                        failedChunk = false
                        val chunkStartOffset = offset
                        try {
                            val req = Request.Builder()
                                .url(streamUrl)
                                .header("User-Agent", userAgent)
                                .header("Range", "bytes=$chunkStartOffset-$endByte")
                                .get()
                                .build()

                            client.newCall(req).execute().use { resp ->
                                if (!resp.isSuccessful && resp.code != 206) {
                                    lastHttpError = "HTTP ${resp.code}"
                                    Log.w(TAG, "$label Range download failed HTTP ${resp.code} at offset=$chunkStartOffset (attempt ${attempt + 1})")
                                    failedChunk = true
                                } else {
                                    val cr = resp.header("Content-Range")
                                    if (cr != null && cr.contains("/")) {
                                        totalBytes = cr.substringAfter("/").trim().toLongOrNull() ?: totalBytes
                                    } else if (totalBytes < 0) {
                                        val cl = resp.body?.contentLength() ?: -1L
                                        if (cl > 0) totalBytes = cl
                                    }
                                    val body = resp.body
                                    if (body == null) {
                                        failedChunk = true
                                    } else {
                                        val chunkBuf = java.io.ByteArrayOutputStream()
                                        body.byteStream().use { input ->
                                            while (true) {
                                                val read = input.read(buf)
                                                if (read == -1) break
                                                chunkBuf.write(buf, 0, read)
                                                gotBytes += read
                                                val now = System.currentTimeMillis()
                                                if (now - lastEmitMs >= 450L) {
                                                    lastEmitMs = now
                                                    val doneBytes = chunkStartOffset + gotBytes
                                                    val mbDone = String.format("%.1f", doneBytes / (1024.0 * 1024.0))
                                                    if (totalBytes > 0) {
                                                        val pct = pctStart + ((doneBytes * pctSpan) / totalBytes).toInt()
                                                        val mbTotal = String.format("%.1f", totalBytes / (1024.0 * 1024.0))
                                                        onProgress(pct.coerceAtMost(pctStart + pctSpan), "$label ($mbDone / $mbTotal MB)")
                                                    } else {
                                                        onProgress(pctStart + (pctSpan / 2), "$label ($mbDone MB)")
                                                    }
                                                }
                                            }
                                        }
                                        output.write(chunkBuf.toByteArray())
                                        offset = chunkStartOffset + gotBytes
                                        if (resp.code == 200 || gotBytes == 0L || (totalBytes > 0 && offset >= totalBytes)) {
                                            done = true
                                        }
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            lastHttpError = e.message ?: "Network error"
                            Log.w(TAG, "$label chunk error at offset=$chunkStartOffset (attempt ${attempt + 1}): ${e.message}")
                            failedChunk = true
                        }
                        if (!failedChunk) break
                        Thread.sleep(600L * (attempt + 1))
                    }
                    if (failedChunk) break
                    if (done) {
                        chunkedOk = true
                        break
                    }
                }
            }
        } catch (e: Exception) {
            lastHttpError = e.message ?: "Network error"
            Log.w(TAG, "$label chunked download error: ${e.message}")
        }

        if (chunkedOk && targetFile.exists() && targetFile.length() > 1024) {
            return true
        }
        return downloadPlainGet(streamUrl, targetFile, userAgent, pctStart, pctSpan, label, onProgress)
    }

    private fun muxVideoAndAudio(videoFile: File, audioFile: File, outFile: File): Boolean {
        val vExt = MediaExtractor()
        val aExt = MediaExtractor()
        var muxer: MediaMuxer? = null
        var muxerStarted = false
        try {
            vExt.setDataSource(videoFile.absolutePath)
            aExt.setDataSource(audioFile.absolutePath)

            var vTrackIdx = -1
            var vFormat: MediaFormat? = null
            for (i in 0 until vExt.trackCount) {
                val fmt = vExt.getTrackFormat(i)
                if ((fmt.getString(MediaFormat.KEY_MIME) ?: "").startsWith("video/")) {
                    vTrackIdx = i
                    vFormat = fmt
                    break
                }
            }

            var aTrackIdx = -1
            var aFormat: MediaFormat? = null
            for (i in 0 until aExt.trackCount) {
                val fmt = aExt.getTrackFormat(i)
                if ((fmt.getString(MediaFormat.KEY_MIME) ?: "").startsWith("audio/")) {
                    aTrackIdx = i
                    aFormat = fmt
                    break
                }
            }

            if (vTrackIdx < 0 || vFormat == null) {
                Log.e(TAG, "muxVideoAndAudio: no video track found in ${videoFile.name}")
                return false
            }

            outFile.parentFile?.mkdirs()
            if (outFile.exists()) outFile.delete()
            muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val outV = muxer.addTrack(vFormat)
            val outA = if (aTrackIdx >= 0 && aFormat != null) muxer.addTrack(aFormat) else -1
            muxer.start()
            muxerStarted = true

            val buf = ByteBuffer.allocateDirect(2 * 1024 * 1024)
            val info = MediaCodec.BufferInfo()

            vExt.selectTrack(vTrackIdx)
            var vSamples = 0
            while (true) {
                val sz = vExt.readSampleData(buf, 0)
                if (sz < 0) break
                info.offset = 0
                info.size = sz
                info.presentationTimeUs = vExt.sampleTime
                info.flags = if ((vExt.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                muxer.writeSampleData(outV, buf, info)
                vExt.advance()
                vSamples++
            }
            Log.i(TAG, "muxVideoAndAudio: wrote $vSamples video samples from ${videoFile.name}")

            if (outA >= 0) {
                aExt.selectTrack(aTrackIdx)
                var aSamples = 0
                while (true) {
                    val sz = aExt.readSampleData(buf, 0)
                    if (sz < 0) break
                    info.offset = 0
                    info.size = sz
                    info.presentationTimeUs = aExt.sampleTime
                    info.flags = if ((aExt.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                    muxer.writeSampleData(outA, buf, info)
                    aExt.advance()
                    aSamples++
                }
                Log.i(TAG, "muxVideoAndAudio: wrote $aSamples audio samples from ${audioFile.name}")
            }
            muxer.stop()
            muxerStarted = false
            val outSize = outFile.length()
            Log.i(TAG, "muxVideoAndAudio: output ${outFile.name} = ${outSize / 1024} KB")
            return outSize > 1024
        } catch (e: Exception) {
            Log.e(TAG, "HD muxing failed: ${e.message}", e)
            return false
        } finally {
            try { vExt.release() } catch (_: Exception) {}
            try { aExt.release() } catch (_: Exception) {}
            if (muxerStarted) {
                try { muxer?.stop() } catch (_: Exception) {}
            }
            try { muxer?.release() } catch (_: Exception) {}
        }
    }

    private fun remuxTsToMp4(tsFile: File, outFile: File): Boolean {
        val ext = MediaExtractor()
        var muxer: MediaMuxer? = null
        var muxerStarted = false
        try {
            ext.setDataSource(tsFile.absolutePath)
            var vIdx = -1
            var aIdx = -1
            var vFmt: MediaFormat? = null
            var aFmt: MediaFormat? = null
            for (i in 0 until ext.trackCount) {
                val fmt = ext.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("video/") && vIdx < 0) {
                    vIdx = i
                    vFmt = fmt
                } else if (mime.startsWith("audio/") && aIdx < 0) {
                    aIdx = i
                    aFmt = fmt
                }
            }
            if (vIdx < 0 || vFmt == null) {
                Log.w(TAG, "remuxTsToMp4: no video track in ${tsFile.name}")
                return false
            }
            outFile.parentFile?.mkdirs()
            if (outFile.exists()) outFile.delete()
            muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val outV = muxer.addTrack(vFmt)
            val outA = if (aIdx >= 0 && aFmt != null) muxer.addTrack(aFmt) else -1
            muxer.start()
            muxerStarted = true

            ext.selectTrack(vIdx)
            if (aIdx >= 0) ext.selectTrack(aIdx)

            val buf = ByteBuffer.allocateDirect(2 * 1024 * 1024)
            val info = MediaCodec.BufferInfo()
            while (true) {
                val trackIdx = ext.sampleTrackIndex
                if (trackIdx < 0) break
                val sz = ext.readSampleData(buf, 0)
                if (sz < 0) break
                info.offset = 0
                info.size = sz
                info.presentationTimeUs = ext.sampleTime.coerceAtLeast(0L)
                info.flags = if ((ext.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                if (trackIdx == vIdx) {
                    muxer.writeSampleData(outV, buf, info)
                } else if (trackIdx == aIdx && outA >= 0) {
                    muxer.writeSampleData(outA, buf, info)
                }
                ext.advance()
            }
            muxer.stop()
            muxerStarted = false
            return outFile.exists() && outFile.length() > 1024
        } catch (e: Exception) {
            Log.w(TAG, "remuxTsToMp4 failed: ${e.message}")
            return false
        } finally {
            try { ext.release() } catch (_: Exception) {}
            if (muxerStarted) {
                try { muxer?.stop() } catch (_: Exception) {}
            }
            try { muxer?.release() } catch (_: Exception) {}
        }
    }

    private fun downloadViaVisionOsHls(
        videoId: String,
        destFile: File,
        maxHeight: Int,
        maxSegments: Int,
        onProgress: (Int, String) -> Unit
    ): Triple<Boolean, Int, Int> {
        return try {
            val watchReq = Request.Builder()
                .url("https://www.youtube.com/watch?v=$videoId")
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
                .get()
                .build()
            val html = client.newCall(watchReq).execute().use { resp ->
                if (!resp.isSuccessful) "" else (resp.body?.string() ?: "")
            }
            val vdMatch = Regex("\"visitorData\":\"([^\"]+)\"").find(html)
            val keyMatch = Regex("\"INNERTUBE_API_KEY\":\"([^\"]+)\"").find(html)
            val visitorData = vdMatch?.groupValues?.get(1) ?: ""
            val apiKey = keyMatch?.groupValues?.get(1) ?: ""
            if (visitorData.isEmpty() || apiKey.isEmpty()) {
                Log.w(TAG, "VISIONOS: missing visitorData/apiKey")
                return Triple(false, 0, 0)
            }

            val ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15"
            val payload = JSONObject().apply {
                put("videoId", videoId)
                put("context", JSONObject().apply {
                    put("client", JSONObject().apply {
                        put("clientName", "VISIONOS")
                        put("clientVersion", "1.02")
                        put("deviceMake", "Apple")
                        put("deviceModel", "RealityDevice17,1")
                        put("osName", "visionOS")
                        put("osVersion", "26.5.23O471")
                        put("visitorData", visitorData)
                        put("hl", "en")
                        put("gl", "US")
                    })
                })
                put("contentCheckOk", true)
                put("racyCheckOk", true)
            }
            val playerReq = Request.Builder()
                .url("https://www.youtube.com/youtubei/v1/player?key=$apiKey&prettyPrint=false")
                .header("Content-Type", "application/json")
                .header("User-Agent", ua)
                .header("X-YouTube-Client-Name", "101")
                .header("X-YouTube-Client-Version", "1.02")
                .post(payload.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                .build()
            val playerJson = client.newCall(playerReq).execute().use { resp ->
                val s = resp.body?.string() ?: ""
                if (resp.isSuccessful && s.isNotEmpty()) JSONObject(s) else null
            } ?: return Triple(false, 0, 0)

            val hlsManifestUrl = playerJson.optJSONObject("streamingData")?.optString("hlsManifestUrl", "") ?: ""
            if (hlsManifestUrl.isEmpty()) {
                Log.w(TAG, "VISIONOS: no hlsManifestUrl")
                return Triple(false, 0, 0)
            }

            val masterM3u8 = client.newCall(Request.Builder().url(hlsManifestUrl).header("User-Agent", ua).get().build()).execute().use { resp ->
                if (resp.isSuccessful) (resp.body?.string() ?: "") else ""
            }
            if (masterM3u8.isEmpty()) return Triple(false, 0, 0)

            val lines = masterM3u8.lines()
            var bestAvcUrl = ""
            var bestAvcH = 0
            var bestAvcW = 0
            var bestAnyUrl = ""
            var bestAnyH = 0
            var bestAnyW = 0
            for (i in lines.indices) {
                val line = lines[i].trim()
                if (line.startsWith("#EXT-X-STREAM-INF:")) {
                    val resMatch = Regex("RESOLUTION=(\\d+)x(\\d+)").find(line)
                    val w = resMatch?.groupValues?.get(1)?.toIntOrNull() ?: 0
                    val h = resMatch?.groupValues?.get(2)?.toIntOrNull() ?: 0
                    val nextUrl = lines.drop(i + 1).firstOrNull { it.trim().isNotEmpty() && !it.trim().startsWith("#") }?.trim() ?: ""
                    if (nextUrl.isNotEmpty() && h in 1..maxHeight) {
                        val isAvc = line.contains("avc1", ignoreCase = true)
                        if (isAvc && h >= bestAvcH) {
                            bestAvcH = h; bestAvcW = w; bestAvcUrl = nextUrl
                        }
                        if (h >= bestAnyH) {
                            bestAnyH = h; bestAnyW = w; bestAnyUrl = nextUrl
                        }
                    }
                }
            }

            val chosenPlaylist = if (bestAvcUrl.isNotEmpty()) bestAvcUrl else bestAnyUrl
            val chosenW = if (bestAvcUrl.isNotEmpty()) bestAvcW else bestAnyW
            val chosenH = if (bestAvcUrl.isNotEmpty()) bestAvcH else bestAnyH
            if (chosenPlaylist.isEmpty()) return Triple(false, 0, 0)

            val variantM3u8 = client.newCall(Request.Builder().url(chosenPlaylist).header("User-Agent", ua).get().build()).execute().use { resp ->
                if (resp.isSuccessful) (resp.body?.string() ?: "") else ""
            }
            val segments = variantM3u8.lines().map { it.trim() }.filter { it.startsWith("http") }
            if (segments.isEmpty()) return Triple(false, 0, 0)

            val takeCount = segments.size.coerceAtMost(maxSegments)
            Log.i(TAG, "VISIONOS HLS ${chosenW}x${chosenH}: downloading $takeCount/${segments.size} segments")
            onProgress(12, "[YouTube HD] Downloading ${chosenH}p HD stream ($takeCount segments)...")

            val tmpTs = File(destFile.parentFile, "${destFile.nameWithoutExtension}_hls.ts")
            if (tmpTs.exists()) tmpTs.delete()
            tmpTs.parentFile?.mkdirs()

            var totalBytes = 0L
            var lastEmit = 0L
            var consecutiveFails = 0
            FileOutputStream(tmpTs).use { out ->
                val buf = ByteArray(64 * 1024)
                for (idx in 0 until takeCount) {
                    val segUrl = segments[idx]
                    var segOk = false
                    for (attempt in 0 until 3) {
                        try {
                            val sReq = Request.Builder().url(segUrl).header("User-Agent", ua).get().build()
                            client.newCall(sReq).execute().use { resp ->
                                if (resp.isSuccessful && resp.body != null) {
                                    resp.body!!.byteStream().use { inp ->
                                        while (true) {
                                            val r = inp.read(buf)
                                            if (r == -1) break
                                            out.write(buf, 0, r)
                                            totalBytes += r
                                        }
                                    }
                                    segOk = true
                                }
                            }
                        } catch (_: Exception) {}
                        if (segOk) break
                        Thread.sleep(300L * (attempt + 1))
                    }
                    if (!segOk) {
                        consecutiveFails++
                        Log.w(TAG, "VISIONOS HLS segment $idx failed after 3 retries (consecutive=$consecutiveFails)")
                        if (consecutiveFails >= 5) break
                        continue
                    }
                    consecutiveFails = 0
                    val now = System.currentTimeMillis()
                    if (now - lastEmit >= 450L || idx == takeCount - 1) {
                        lastEmit = now
                        val pct = 12 + (((idx + 1) * 76) / takeCount)
                        val mb = String.format("%.1f", totalBytes / (1024.0 * 1024.0))
                        onProgress(pct.coerceAtMost(88), "[YouTube ${chosenH}p] Segment ${idx + 1}/$takeCount ($mb MB)")
                    }
                }
            }

            if (!tmpTs.exists() || tmpTs.length() < 1024) {
                tmpTs.delete()
                return Triple(false, 0, 0)
            }

            onProgress(90, "[Muxer] Finalizing ${chosenH}p HD MP4...")
            val remuxed = remuxTsToMp4(tmpTs, destFile)
            if (remuxed) {
                tmpTs.delete()
                return Triple(true, chosenW, chosenH)
            }
            // Fallback: Media3/MediaExtractor supports MPEG-TS directly even with .mp4/.ts
            tmpTs.copyTo(destFile, overwrite = true)
            tmpTs.delete()
            Triple(destFile.exists() && destFile.length() > 1024, chosenW, chosenH)
        } catch (e: Exception) {
            Log.w(TAG, "VISIONOS HLS failed: ${e.message}")
            Triple(false, 0, 0)
        }
    }

    fun downloadYouTubeMp4(
        url: String,
        destFile: File,
        maxHeight: Int = 4320,
        maxSegments: Int = Int.MAX_VALUE,
        onProgress: (Int, String) -> Unit
    ): DownloadResult {
        val videoId = extractVideoId(url)
            ?: return DownloadResult(ok = false, error = "Invalid YouTube URL (could not find video ID).")

        onProgress(8, "[YouTube] Resolving HD stream & captions for $videoId...")
        val (json, reasonOrUa) = fetchPlayerJson(videoId)
        if (json == null) {
            return DownloadResult(
                ok = false,
                error = if (reasonOrUa.isNotEmpty()) "YouTube blocked stream ($reasonOrUa). Try another video or pick from Gallery."
                else "Could not resolve direct MP4 stream for this YouTube video."
            )
        }

        val userAgent = reasonOrUa
        val vd = json.optJSONObject("videoDetails")
        val videoTitle = vd?.optString("title", "YouTube_$videoId")?.takeIf { it.isNotEmpty() } ?: "YouTube_$videoId"
        val streamingData = json.optJSONObject("streamingData")
        val captions = fetchCaptions(json, userAgent)

        // 0. Primary: VISIONOS HLS (1080p60 / 720p60 avc1+AAC MPEG-TS segments with ZERO 40 MB Range cap)
        if (maxHeight >= 720) {
            val (hlsOk, hlsW, hlsH) = downloadViaVisionOsHls(videoId, destFile, maxHeight, maxSegments, onProgress)
            if (hlsOk && destFile.exists() && destFile.length() > 1024) {
                val mb = String.format("%.1f", destFile.length() / (1024.0 * 1024.0))
                Log.i(TAG, "Downloaded ${hlsH}p HD via VISIONOS HLS ($mb MB) + ${captions.size} captions")
                onProgress(98, "[Download] ${hlsH}p HD ready ($mb MB)!")
                return DownloadResult(
                    ok = true,
                    title = videoTitle,
                    file = destFile,
                    captions = captions,
                    width = hlsW,
                    height = hlsH
                )
            }
        }

        // 1. Try adaptive HD/4K/8K (video/mp4 avc1/av01/hvc1 + AAC audio/mp4) across IOS -> ANDROID_VR -> ANDROID -> ANDROID_TESTSUITE
        val adaptiveClients = listOf(
            Triple("IOS", "20.10.4", "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"),
            Triple("ANDROID_VR", "1.60.19", "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"),
            Triple("ANDROID", "20.10.38", "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip"),
            Triple("ANDROID_TESTSUITE", "1.9", "com.google.android.youtube/1.9 (Linux; U; Android 14) gzip")
        )
        for ((cName, cVer, cUa) in adaptiveClients) {
            val (cJson, _) = if (cUa == userAgent) Pair(json, cUa) else fetchPlayerJsonForClient(videoId, cName, cVer, cUa)
            val cSd = cJson?.optJSONObject("streamingData") ?: continue
            val adaptiveFormats: JSONArray? = cSd.optJSONArray("adaptiveFormats")
            var bestAvcUrl: String? = null
            var bestAvcH = 0
            var bestAvcW = 0
            var bestAnyUrl: String? = null
            var bestAnyH = 0
            var bestAnyW = 0
            var bestAdaptiveAudioUrl: String? = null
            var bestAudioBitrate = -1

            if (adaptiveFormats != null) {
                for (i in 0 until adaptiveFormats.length()) {
                    val f = adaptiveFormats.optJSONObject(i) ?: continue
                    val fUrl = f.optString("url", "")
                    if (fUrl.isEmpty()) continue
                    val mime = f.optString("mimeType", "")
                    val isAvc = mime.contains("video/mp4") && mime.contains("avc1")
                    val isOtherMp4 = mime.contains("video/mp4") &&
                        (mime.contains("av01") || mime.contains("hvc1") || mime.contains("hev1"))
                    if (isAvc || isOtherMp4) {
                        val h = f.optInt("height", 0)
                        val w = f.optInt("width", 0)
                        if (h in 1..maxHeight) {
                            if (isAvc && h > bestAvcH) {
                                bestAvcH = h
                                bestAvcW = w
                                bestAvcUrl = fUrl
                            }
                            if (h > bestAnyH) {
                                bestAnyH = h
                                bestAnyW = w
                                bestAnyUrl = fUrl
                            }
                        }
                    } else if (mime.contains("audio/mp4")) {
                        val br = f.optInt("bitrate", 0)
                        if (br >= bestAudioBitrate) {
                            bestAudioBitrate = br
                            bestAdaptiveAudioUrl = fUrl
                        }
                    }
                }
            }

            val minAdaptiveH = if (maxHeight <= 480) 360 else 720
            val candidates = mutableListOf<Triple<String, Int, Int>>()
            // Prefer H.264 avc1 first for rock-solid Android hardware MediaMuxer & Media3 compatibility;
            // if user selected >1080p (4K/2K), try highest resolution first with avc1 as immediate fallback.
            if (maxHeight > 1080 && bestAnyUrl != null && bestAnyH > bestAvcH && bestAnyH >= minAdaptiveH) {
                candidates.add(Triple(bestAnyUrl, bestAnyH, bestAnyW))
            }
            if (bestAvcUrl != null && bestAvcH >= minAdaptiveH) {
                candidates.add(Triple(bestAvcUrl, bestAvcH, bestAvcW))
            }
            if (bestAnyUrl != null && bestAnyH >= minAdaptiveH && bestAnyUrl != bestAvcUrl && maxHeight <= 1080) {
                candidates.add(Triple(bestAnyUrl, bestAnyH, bestAnyW))
            }

            if (bestAdaptiveAudioUrl != null) {
                for ((candUrl, candH, candW) in candidates) {
                    onProgress(15, "[YouTube HD] Downloading ${candH}p ($cName) + AAC audio for '$videoTitle'...")
                    val tmpVid = File(destFile.parentFile, "${destFile.nameWithoutExtension}_v.mp4")
                    val tmpAud = File(destFile.parentFile, "${destFile.nameWithoutExtension}_a.m4a")
                    try {
                        val vOk = downloadToFile(candUrl, tmpVid, cUa, 16, 52, "[Download ${candH}p]", onProgress)
                        val aOk = if (vOk) downloadToFile(bestAdaptiveAudioUrl, tmpAud, cUa, 68, 18, "[Download Audio]", onProgress) else false
                        if (vOk && aOk) {
                            onProgress(88, "[Muxer] Combining ${candH}p HD video & audio...")
                            if (muxVideoAndAudio(tmpVid, tmpAud, destFile)) {
                                tmpVid.delete()
                                tmpAud.delete()
                                val mb = String.format("%.1f", destFile.length() / (1024.0 * 1024.0))
                                Log.i(TAG, "Downloaded & muxed ${candH}p HD MP4 via $cName ($mb MB) + ${captions.size} captions")
                                onProgress(98, "[Download] ${candH}p HD MP4 ready ($mb MB)!")
                                return DownloadResult(
                                    ok = true,
                                    title = videoTitle,
                                    file = destFile,
                                    captions = captions,
                                    width = candW,
                                    height = candH
                                )
                            } else {
                                // Muxing failed — try video-only copy as a last resort for this candidate
                                Log.w(TAG, "$cName muxing failed for ${candH}p — trying video-only fallback")
                                if (tmpVid.exists() && tmpVid.length() > 1024) {
                                    try {
                                        tmpVid.copyTo(destFile, overwrite = true)
                                        tmpVid.delete()
                                        tmpAud.delete()
                                        val mb = String.format("%.1f", destFile.length() / (1024.0 * 1024.0))
                                        Log.i(TAG, "Video-only ${candH}p fallback via $cName ($mb MB)")
                                        onProgress(98, "[Download] ${candH}p video ready ($mb MB, no audio track)")
                                        return DownloadResult(ok = true, title = videoTitle, file = destFile, captions = captions, width = candW, height = candH)
                                    } catch (copyEx: Exception) {
                                        Log.w(TAG, "Video-only copy failed: ${copyEx.message}")
                                    }
                                }
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "$cName adaptive ${candH}p failed: ${e.message}")
                    } finally {
                        tmpVid.delete()
                        tmpAud.delete()
                    }
                }
            }
        }

        // 2. Fallback to progressive formats (360p/720p combined MP4)
        var streamUrl: String? = null
        var bestHeight = -1
        var bestWidth = 0
        val formats = streamingData?.optJSONArray("formats")
        if (formats != null) {
            for (i in 0 until formats.length()) {
                val f = formats.optJSONObject(i) ?: continue
                val fUrl = f.optString("url", "")
                val mime = f.optString("mimeType", "")
                val h = f.optInt("height", 0)
                val w = f.optInt("width", 0)
                if (fUrl.isNotEmpty() && mime.contains("video/mp4") && h >= bestHeight) {
                    bestHeight = h
                    bestWidth = w
                    streamUrl = fUrl
                }
            }
        }

        val resolvedUrl = streamUrl ?: return DownloadResult(
            ok = false,
            error = "Could not resolve playable MP4 stream for this YouTube video."
        )

        onProgress(20, "[Download] Downloading ${bestHeight}p MP4 '$videoTitle'...")
        val ok = downloadToFile(resolvedUrl, destFile, userAgent, 20, 75, "[Download]", onProgress)
        if (ok) {
            val mb = String.format("%.1f", destFile.length() / (1024.0 * 1024.0))
            onProgress(98, "[Download] Downloaded $mb MB MP4!")
            return DownloadResult(
                ok = true,
                title = videoTitle,
                file = destFile,
                captions = captions,
                width = bestWidth,
                height = bestHeight
            )
        }
        val errDetail = if (lastHttpError.isNotEmpty()) " ($lastHttpError)" else ""
        return DownloadResult(ok = false, error = "Downloaded file was empty or interrupted$errDetail.")
    }
}
