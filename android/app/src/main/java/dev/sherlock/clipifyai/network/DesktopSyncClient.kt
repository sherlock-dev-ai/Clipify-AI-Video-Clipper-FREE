package dev.sherlock.clipifyai.network

import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class DesktopSyncClient(private var desktopHost: String = "http://127.0.0.1:5000") {

    @Volatile
    private var isDesktopAvailable: Boolean = false

    @Volatile
    private var lastCheckTime: Long = 0L

    private val client = OkHttpClient.Builder()
        .connectTimeout(1, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .build()

    private fun isEmulator(): Boolean {
        val fp = Build.FINGERPRINT.lowercase()
        val model = Build.MODEL.lowercase()
        val hw = Build.HARDWARE.lowercase()
        return fp.startsWith("generic") || fp.startsWith("unknown") ||
                model.contains("google_sdk") || model.contains("emulator") ||
                model.contains("android sdk built for x86") ||
                hw.contains("goldfish") || hw.contains("ranchu")
    }

    fun executeApiCall(method: String, endpoint: String, bodyStr: String?, headersJson: String?): String {
        val now = System.currentTimeMillis()
        // Fast fail: if desktop is known offline and checked recently, do not freeze caller thread
        if (!isDesktopAvailable && now - lastCheckTime < 15000L) {
            val errObj = JSONObject()
            errObj.put("ok", false)
            errObj.put("status", 503)
            errObj.put("error", "Desktop server offline")
            return errObj.toString()
        }

        try {
            val url = if (endpoint.startsWith("http://") || endpoint.startsWith("https://")) {
                endpoint
            } else {
                val clean = if (endpoint.startsWith("/")) endpoint else "/$endpoint"
                "$desktopHost$clean"
            }
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
                } catch (_: Exception) {}
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
            isDesktopAvailable = response.isSuccessful
            lastCheckTime = now

            val resObj = JSONObject()
            resObj.put("ok", response.isSuccessful)
            resObj.put("status", response.code)
            resObj.put("body", respBody)
            return resObj.toString()
        } catch (e: Exception) {
            lastCheckTime = System.currentTimeMillis()
            isDesktopAvailable = false

            // Only retry 10.0.2.2 if on emulator
            if (isEmulator() && desktopHost.contains("127.0.0.1")) {
                desktopHost = "http://10.0.2.2:5000"
                return executeApiCall(method, endpoint, bodyStr, headersJson)
            }
            val errObj = JSONObject()
            errObj.put("ok", false)
            errObj.put("status", 503)
            errObj.put("error", e.localizedMessage ?: "Connection to desktop server failed")
            return errObj.toString()
        }
    }

    fun testConnection(callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$desktopHost/api/health")
            .build()

        client.newCall(request).enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                isDesktopAvailable = false
                lastCheckTime = System.currentTimeMillis()
                callback(false, e.localizedMessage)
            }

            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                val successful = response.isSuccessful
                val body = response.body?.string()
                isDesktopAvailable = successful
                lastCheckTime = System.currentTimeMillis()
                callback(successful, body)
            }
        })
    }

    fun fetchAvailableModels(callback: (List<String>) -> Unit) {
        val request = Request.Builder()
            .url("$desktopHost/api/models")
            .build()

        client.newCall(request).enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                callback(emptyList())
            }

            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                val result = mutableListOf<String>()
                if (response.isSuccessful) {
                    try {
                        val body = response.body?.string() ?: "{}"
                        val json = JSONObject(body)
                        val models = json.optJSONArray("models") ?: JSONArray()
                        for (i in 0 until models.length()) {
                            result.add(models.getString(i))
                        }
                    } catch (e: Exception) {
                        // fallback
                    }
                }
                callback(result)
            }
        })
    }

    fun syncProjectToDesktop(projectJsonString: String, callback: (Boolean, String?) -> Unit) {
        val mediaType = "application/json; charset=utf-8".toMediaType()
        val body = projectJsonString.toRequestBody(mediaType)
        val request = Request.Builder()
            .url("$desktopHost/api/projects/sync")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                callback(false, e.localizedMessage)
            }

            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                callback(response.isSuccessful, response.body?.string())
            }
        })
    }

    fun updateHost(newHost: String) {
        this.desktopHost = newHost.trim().removeSuffix("/")
        this.lastCheckTime = 0L // reset so next call checks new host
    }
}
