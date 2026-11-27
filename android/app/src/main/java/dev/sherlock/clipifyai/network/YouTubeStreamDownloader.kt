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
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
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
        // Try chunked Range requests first for adaptive/googlevideo streams (prevents HTTP 403)
        val chunkSize = 4L * 1024L * 1024L
        var offset = 0L
        var totalBytes = -1L
        var lastPct = pctStart

        try {
            FileOutputStream(targetFile).use { output ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val endByte = offset + chunkSize - 1L
                    val req = Request.Builder()
                        .url(streamUrl)
                        .header("User-Agent", userAgent)
                        .header("Range", "bytes=$offset-$endByte")
                        .get()
                        .build()

                    var gotBytes = 0L
                    var done = false
                    client.newCall(req).execute().use { resp ->
                        if (resp.code == 403 && offset == 0L) {
                            Log.w(TAG, "$label Range download failed HTTP 403")
                            return false
                        }
                        if (!resp.isSuccessful && resp.code != 206) {
                            Log.w(TAG, "$label download failed HTTP ${resp.code}")
                            return false
                        }
                        val cr = resp.header("Content-Range")
                        if (cr != null && cr.contains("/")) {
                            totalBytes = cr.substringAfter("/").trim().toLongOrNull() ?: totalBytes
                        } else if (totalBytes < 0) {
                            val cl = resp.body?.contentLength() ?: -1L
                            if (cl > 0) totalBytes = cl
                        }
                        val body = resp.body ?: return false
                        body.byteStream().use { input ->
                            while (true) {
                                val read = input.read(buf)
                                if (read == -1) break
                                output.write(buf, 0, read)
                                gotBytes += read
                                offset += read
                                if (totalBytes > 0) {
                                    val pct = pctStart + ((offset * pctSpan) / totalBytes).toInt()
                                    if (pct >= lastPct + 6) {
                                        lastPct = pct
                                        val mbDone = String.format("%.1f", offset / (1024.0 * 1024.0))
                                        val mbTotal = String.format("%.1f", totalBytes / (1024.0 * 1024.0))
                                        onProgress(pct.coerceAtMost(pctStart + pctSpan), "$label $pct% ($mbDone / $mbTotal MB)")
                                    }
                                }
                            }
                        }
                        if (resp.code == 200 || gotBytes == 0L || (totalBytes > 0 && offset >= totalBytes)) {
                            done = true
                        }
                    }
                    if (done) break
                }
            }
            return targetFile.exists() && targetFile.length() > 1024
        } catch (e: Exception) {
            Log.w(TAG, "$label chunked download error: ${e.message}")
            return false
        }
    }

    private fun muxVideoAndAudio(videoFile: File, audioFile: File, outFile: File): Boolean {
        val vExt = MediaExtractor()
        val aExt = MediaExtractor()
        var muxer: MediaMuxer? = null
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

            if (vTrackIdx < 0 || vFormat == null) return false

            outFile.parentFile?.mkdirs()
            muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val outV = muxer.addTrack(vFormat)
            val outA = if (aTrackIdx >= 0 && aFormat != null) muxer.addTrack(aFormat) else -1
            muxer.start()

            val buf = ByteBuffer.allocateDirect(1024 * 1024)
            val info = MediaCodec.BufferInfo()

            vExt.selectTrack(vTrackIdx)
            while (true) {
                val sz = vExt.readSampleData(buf, 0)
                if (sz < 0) break
                info.offset = 0
                info.size = sz
                info.presentationTimeUs = vExt.sampleTime
                info.flags = if ((vExt.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                muxer.writeSampleData(outV, buf, info)
                vExt.advance()
            }

            if (outA >= 0) {
                aExt.selectTrack(aTrackIdx)
                while (true) {
                    val sz = aExt.readSampleData(buf, 0)
                    if (sz < 0) break
                    info.offset = 0
                    info.size = sz
                    info.presentationTimeUs = aExt.sampleTime
                    info.flags = if ((aExt.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                    muxer.writeSampleData(outA, buf, info)
                    aExt.advance()
                }
            }
            muxer.stop()
            return outFile.exists() && outFile.length() > 1024
        } catch (e: Exception) {
            Log.e(TAG, "HD muxing failed: ${e.message}", e)
            return false
        } finally {
            try { vExt.release() } catch (_: Exception) {}
            try { aExt.release() } catch (_: Exception) {}
            try { muxer?.release() } catch (_: Exception) {}
        }
    }

    fun downloadYouTubeMp4(
        url: String,
        destFile: File,
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

        // 1. Try adaptive HD (1080p or 720p H.264 video/mp4 + AAC audio/mp4) across IOS -> ANDROID_VR -> ANDROID
        val adaptiveClients = listOf(
            Triple("IOS", "20.10.4", "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"),
            Triple("ANDROID_VR", "1.60.19", "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"),
            Triple("ANDROID", "20.10.38", "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip")
        )
        for ((cName, cVer, cUa) in adaptiveClients) {
            val (cJson, _) = if (cUa == userAgent) Pair(json, cUa) else fetchPlayerJsonForClient(videoId, cName, cVer, cUa)
            val cSd = cJson?.optJSONObject("streamingData") ?: continue
            val adaptiveFormats: JSONArray? = cSd.optJSONArray("adaptiveFormats")
            var bestAdaptiveVideoUrl: String? = null
            var bestAdaptiveHeight = 0
            var bestAdaptiveWidth = 0
            var bestAdaptiveAudioUrl: String? = null
            var bestAudioBitrate = -1

            if (adaptiveFormats != null) {
                for (i in 0 until adaptiveFormats.length()) {
                    val f = adaptiveFormats.optJSONObject(i) ?: continue
                    val fUrl = f.optString("url", "")
                    if (fUrl.isEmpty()) continue
                    val mime = f.optString("mimeType", "")
                    if (mime.contains("video/mp4") && mime.contains("avc1")) {
                        val h = f.optInt("height", 0)
                        val w = f.optInt("width", 0)
                        if (h in (bestAdaptiveHeight + 1)..2160) {
                            bestAdaptiveHeight = h
                            bestAdaptiveWidth = w
                            bestAdaptiveVideoUrl = fUrl
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

            if (bestAdaptiveVideoUrl != null && bestAdaptiveAudioUrl != null && bestAdaptiveHeight >= 720) {
                onProgress(15, "[YouTube HD] Downloading ${bestAdaptiveHeight}p ($cName) + AAC audio for '$videoTitle'...")
                val tmpVid = File(destFile.parentFile, "${destFile.nameWithoutExtension}_v.mp4")
                val tmpAud = File(destFile.parentFile, "${destFile.nameWithoutExtension}_a.m4a")
                try {
                    val vOk = downloadToFile(bestAdaptiveVideoUrl, tmpVid, cUa, 16, 52, "[Download ${bestAdaptiveHeight}p]", onProgress)
                    val aOk = if (vOk) downloadToFile(bestAdaptiveAudioUrl, tmpAud, cUa, 68, 18, "[Download Audio]", onProgress) else false
                    if (vOk && aOk) {
                        onProgress(88, "[Muxer] Combining ${bestAdaptiveHeight}p HD video & audio...")
                        if (muxVideoAndAudio(tmpVid, tmpAud, destFile)) {
                            tmpVid.delete()
                            tmpAud.delete()
                            val mb = String.format("%.1f", destFile.length() / (1024.0 * 1024.0))
                            Log.i(TAG, "Downloaded & muxed ${bestAdaptiveHeight}p HD MP4 via $cName ($mb MB) + ${captions.size} captions")
                            onProgress(98, "[Download] ${bestAdaptiveHeight}p HD MP4 ready ($mb MB)!")
                            return DownloadResult(
                                ok = true,
                                title = videoTitle,
                                file = destFile,
                                captions = captions,
                                width = bestAdaptiveWidth,
                                height = bestAdaptiveHeight
                            )
                        }
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "$cName adaptive HD failed: ${e.message}")
                } finally {
                    tmpVid.delete()
                    tmpAud.delete()
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
        return DownloadResult(ok = false, error = "Downloaded file was empty or interrupted.")
    }
}
