package dev.sherlock.clipifyai.network

import android.os.Build
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

class DesktopSyncClient(private var desktopHost: String = "http://127.0.0.1:5000") {

    companion object {
        private const val TAG = "DesktopSyncClient"
    }

    @Volatile
    private var isDesktopAvailable: Boolean = false

    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    private val candidateHosts = listOf(
        "http://127.0.0.1:5000",
        "http://10.254.251.44:5000",
        "http://192.168.68.121:5000",
        "http://192.168.56.1:5000",
        "http://10.0.2.2:5000"
    )

    fun getActiveHost(): String = desktopHost

    fun isConnected(): Boolean {
        val hostsToTry = mutableListOf<String>()
        hostsToTry.add(desktopHost)
        for (h in candidateHosts) {
            if (!hostsToTry.contains(h)) hostsToTry.add(h)
        }

        for (h in hostsToTry) {
            try {
                val req = Request.Builder()
                    .url("$h/api/health")
                    .get()
                    .build()
                client.newCall(req).execute().use { res ->
                    if (res.isSuccessful) {
                        desktopHost = h
                        isDesktopAvailable = true
                        return true
                    }
                }
            } catch (ex: Exception) {
                Log.w(TAG, "Connection failed for host $h: ${ex.javaClass.simpleName} - ${ex.message}")
            }
        }
        isDesktopAvailable = false
        return false
    }

    fun startInstantJob(
        youtubeUrl: String,
        durationSec: Int = 30,
        layout: String = "center_crop",
        captions: Boolean = true
    ): String? {
        val payload = JSONObject().apply {
            put("youtube_url", youtubeUrl)
            put("duration", durationSec.toDouble())
            put("layout", if (layout == "split") "split" else "center_crop")
            put("captions", if (captions) "yes" else "no")
            put("num_clips", 1)
        }
        val res = executeApiCall("POST", "/api/instant/start", payload.toString(), null)
        return try {
            val root = JSONObject(res)
            if (root.optBoolean("ok", false)) {
                val bodyStr = root.optString("body", "{}")
                val bodyObj = JSONObject(bodyStr)
                if (bodyObj.optBoolean("ok", false)) {
                    val jid = bodyObj.optString("job_id", "")
                    if (jid.isNotEmpty()) jid else null
                } else null
            } else null
        } catch (e: Exception) {
            Log.e(TAG, "Error starting instant job", e)
            null
        }
    }

    fun pollInstantJob(jobId: String): JSONObject? {
        val res = executeApiCall("GET", "/api/instant/status/$jobId", null, null)
        return try {
            val root = JSONObject(res)
            if (root.optBoolean("ok", false)) {
                val bodyStr = root.optString("body", "{}")
                JSONObject(bodyStr)
            } else null
        } catch (e: Exception) {
            null
        }
    }

    fun downloadFile(urlOrPath: String, destFile: File): Boolean {
        try {
            val url = when {
                urlOrPath.startsWith("http://") || urlOrPath.startsWith("https://") -> urlOrPath
                urlOrPath.startsWith("/") -> "$desktopHost$urlOrPath"
                else -> "$desktopHost/$urlOrPath"
            }
            val req = Request.Builder().url(url).build()
            client.newCall(req).execute().use { res ->
                if (res.isSuccessful) {
                    val body = res.body ?: return false
                    destFile.parentFile?.mkdirs()
                    destFile.outputStream().use { out ->
                        body.byteStream().copyTo(out)
                    }
                    return destFile.exists() && destFile.length() > 1024
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error downloading file from desktop", e)
        }
        return false
    }

    fun executeApiCall(method: String, endpoint: String, bodyStr: String?, headersJson: String?): String {
        val hostsToTry = mutableListOf<String>()
        hostsToTry.add(desktopHost)
        for (h in candidateHosts) {
            if (!hostsToTry.contains(h)) hostsToTry.add(h)
        }

        for (host in hostsToTry) {
            try {
                val clean = if (endpoint.startsWith("/")) endpoint else "/$endpoint"
                val url = if (endpoint.startsWith("http://") || endpoint.startsWith("https://")) endpoint else "$host$clean"
                val builder = Request.Builder().url(url)
                if (headersJson != null && headersJson.isNotEmpty() && headersJson != "{}") {
                    try {
                        val obj = JSONObject(headersJson)
                        val keys = obj.keys()
                        while (keys.hasNext()) {
                            val k = keys.next()
                            if (!k.equals("host", ignoreCase = true) && !k.equals("content-length", ignoreCase = true)) {
                                builder.addHeader(k, obj.getString(k))
                            }
                        }
                    } catch (ex: Exception) {
                        Log.w(TAG, "Failed parsing custom headers: ${ex.message}")
                    }
                }
                val mediaType = "application/json; charset=utf-8".toMediaType()
                val requestBody = bodyStr?.toRequestBody(mediaType)
                when (method.uppercase()) {
                    "GET" -> builder.get()
                    "POST" -> builder.post(requestBody ?: "".toRequestBody(mediaType))
                    "PUT" -> builder.put(requestBody ?: "".toRequestBody(mediaType))
                    "DELETE" -> builder.delete(requestBody)
                    else -> builder.get()
                }

                val response = client.newCall(builder.build()).execute()
                val respBody = response.body?.string() ?: ""
                if (response.isSuccessful || response.code in 200..499) {
                    desktopHost = host
                    isDesktopAvailable = true
                    val resObj = JSONObject()
                    resObj.put("ok", response.isSuccessful)
                    resObj.put("status", response.code)
                    resObj.put("body", respBody)
                    return resObj.toString()
                }
            } catch (ex: Exception) {
                Log.w(TAG, "Connection failed for host $host: ${ex.javaClass.simpleName} - ${ex.message}")
            }
        }

        val errObj = JSONObject()
        errObj.put("ok", false)
        errObj.put("status", 503)
        errObj.put("error", "Desktop server offline")
        return errObj.toString()
    }
}
