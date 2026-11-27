package dev.sherlock.clipifyai.network

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

object MobileTrendingFetcher {
    private const val TAG = "MobileTrendingFetcher"

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    fun fetchTrending(platform: String, query: String): String {
        val cleanQuery = query.trim()
        val videoQ = if (cleanQuery.isNotEmpty()) "$cleanQuery gameplay" else "trending gaming highlights 2026"
        val liveQ = if (cleanQuery.isNotEmpty()) "$cleanQuery live" else "live gaming stream"

        val gameplayVideos = fetchYouTubeSearch(videoQ, liveOnly = false, limit = 8)
        val liveStreams = fetchYouTubeSearch(liveQ, liveOnly = true, limit = 6)

        val root = JSONObject().apply {
            put("ok", true)
            put("platform", platform)
            put("query", cleanQuery)
            put("source", "youtube_live_fetch")
            put("gameplay_videos", gameplayVideos)
            put("live_streams", liveStreams)
        }
        return root.toString()
    }

    private fun fetchYouTubeSearch(query: String, liveOnly: Boolean, limit: Int): JSONArray {
        val arr = JSONArray()
        try {
            val encoded = URLEncoder.encode(query, "UTF-8")
            val sp = if (liveOnly) "&sp=EgJAAQ%253D%253D" else ""
            val url = "https://www.youtube.com/results?search_query=$encoded$sp"
            val req = Request.Builder()
                .url(url)
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
                .header("Accept-Language", "en-US,en;q=0.9")
                .get()
                .build()

            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return arr
                val html = resp.body?.string() ?: return arr
                val jsonStr = extractYtInitialData(html) ?: return arr
                val data = JSONObject(jsonStr)
                collectVideoRenderers(data, arr, liveOnly, limit)
            }
        } catch (e: Exception) {
            Log.w(TAG, "YouTube fetch failed for '$query': ${e.message}")
        }
        return arr
    }

    private fun extractYtInitialData(html: String): String? {
        val markers = listOf("var ytInitialData = ", "window[\"ytInitialData\"] = ")
        for (marker in markers) {
            val idx = html.indexOf(marker)
            if (idx >= 0) {
                val start = html.indexOf('{', idx + marker.length)
                if (start >= 0) {
                    var depth = 0
                    var inStr = false
                    var esc = false
                    for (i in start until html.length) {
                        val c = html[i]
                        if (esc) {
                            esc = false
                            continue
                        }
                        if (c == '\\' && inStr) {
                            esc = true
                            continue
                        }
                        if (c == '"') {
                            inStr = !inStr
                            continue
                        }
                        if (!inStr) {
                            if (c == '{') depth++
                            else if (c == '}') {
                                depth--
                                if (depth == 0) {
                                    return html.substring(start, i + 1)
                                }
                            }
                        }
                    }
                }
            }
        }
        return null
    }

    private fun collectVideoRenderers(node: Any?, out: JSONArray, liveOnly: Boolean, limit: Int) {
        if (out.length() >= limit || node == null) return
        when (node) {
            is JSONObject -> {
                if (node.has("videoRenderer")) {
                    val vr = node.optJSONObject("videoRenderer")
                    if (vr != null) {
                        parseVideoRenderer(vr, liveOnly)?.let { out.put(it) }
                    }
                    return
                }
                val keys = node.keys()
                while (keys.hasNext() && out.length() < limit) {
                    val k = keys.next()
                    collectVideoRenderers(node.opt(k), out, liveOnly, limit)
                }
            }
            is JSONArray -> {
                for (i in 0 until node.length()) {
                    if (out.length() >= limit) break
                    collectVideoRenderers(node.opt(i), out, liveOnly, limit)
                }
            }
        }
    }

    private fun parseVideoRenderer(vr: JSONObject, liveOnly: Boolean): JSONObject? {
        val videoId = vr.optString("videoId", "")
        if (videoId.isEmpty()) return null

        val title = readText(vr.optJSONObject("title"))
        if (title.isEmpty()) return null

        val channel = readText(vr.optJSONObject("ownerText")).ifEmpty {
            readText(vr.optJSONObject("longBylineText")).ifEmpty { "Creator" }
        }
        val lengthText = readText(vr.optJSONObject("lengthText"))
        val viewText = readText(vr.optJSONObject("shortViewCountText")).ifEmpty {
            readText(vr.optJSONObject("viewCountText"))
        }

        val isLive = lengthText.isEmpty() || liveOnly
        val thumb = "https://i.ytimg.com/vi/$videoId/hqdefault.jpg"

        return JSONObject().apply {
            put("id", videoId)
            put("title", title)
            put("channel", channel)
            put("thumbnail", thumb)
            put("url", "https://www.youtube.com/watch?v=$videoId")
            put("is_live", isLive)
            put("game", if (isLive) "Live Stream" else "Gameplay")
            if (isLive) {
                put("viewers", viewText.replace(" watching", "").ifEmpty { "LIVE" })
            } else {
                put("duration", lengthText)
                put("views", viewText.replace(" views", ""))
            }
        }
    }

    private fun readText(obj: JSONObject?): String {
        if (obj == null) return ""
        val simple = obj.optString("simpleText", "")
        if (simple.isNotEmpty()) return simple
        val runs = obj.optJSONArray("runs") ?: return ""
        val sb = StringBuilder()
        for (i in 0 until runs.length()) {
            sb.append(runs.optJSONObject(i)?.optString("text", "") ?: "")
        }
        return sb.toString().trim()
    }
}

