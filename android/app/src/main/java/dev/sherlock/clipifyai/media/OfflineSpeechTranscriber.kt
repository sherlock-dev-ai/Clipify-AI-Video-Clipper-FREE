package dev.sherlock.clipifyai.media

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.util.Log
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream

/**
 * Real on-device offline voice-to-text using MediaCodec PCM decoding + Vosk speech recognition.
 * Works 100% standalone on Android without a PC or Hugging Face token.
 */
object OfflineSpeechTranscriber {
    private const val TAG = "OfflineSpeechSTT"
    private const val MODEL_DIR_NAME = "vosk-model-small-en-us-0.15"
    private const val MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

    @Volatile
    private var cachedModel: Model? = null
    private val modelLock = Any()

    private fun getModelDir(context: Context): File = File(context.filesDir, MODEL_DIR_NAME)

    private fun isModelReady(dir: File): Boolean {
        return dir.exists() && File(dir, "am/final.mdl").exists()
    }

    private fun ensureModel(context: Context, onProgress: ((Int, String) -> Unit)?): Model? {
        synchronized(modelLock) {
            cachedModel?.let { return it }
            val modelDir = getModelDir(context)
            if (!isModelReady(modelDir)) {
                val zipFile = File(context.cacheDir, "$MODEL_DIR_NAME.zip")
                try {
                    onProgress?.invoke(15, "Downloading offline voice-to-text model (~40 MB, one-time)...")
                    Log.i(TAG, "Downloading Vosk model from $MODEL_URL")
                    val client = OkHttpClient.Builder()
                        .connectTimeout(20, TimeUnit.SECONDS)
                        .readTimeout(120, TimeUnit.SECONDS)
                        .followRedirects(true)
                        .build()
                    val req = Request.Builder().url(MODEL_URL).get().build()
                    client.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) {
                            Log.w(TAG, "Vosk model download HTTP ${resp.code}")
                            return null
                        }
                        val body = resp.body ?: return null
                        val total = body.contentLength()
                        val buf = ByteArray(64 * 1024)
                        var done = 0L
                        var lastPct = -1
                        FileOutputStream(zipFile).use { out ->
                            body.byteStream().use { inp ->
                                while (true) {
                                    val r = inp.read(buf)
                                    if (r == -1) break
                                    out.write(buf, 0, r)
                                    done += r
                                    if (total > 0) {
                                        val pct = ((done * 100) / total).toInt()
                                        if (pct >= lastPct + 10) {
                                            lastPct = pct
                                            onProgress?.invoke(15 + (pct / 10), "Downloading voice-to-text model ($pct%)...")
                                        }
                                    }
                                }
                            }
                        }
                    }

                    onProgress?.invoke(24, "Extracting offline voice-to-text model...")
                    ZipInputStream(zipFile.inputStream().buffered()).use { zis ->
                        var entry = zis.nextEntry
                        val buf = ByteArray(32 * 1024)
                        while (entry != null) {
                            val outFile = File(context.filesDir, entry.name)
                            if (entry.isDirectory) {
                                outFile.mkdirs()
                            } else {
                                outFile.parentFile?.mkdirs()
                                FileOutputStream(outFile).use { fos ->
                                    while (true) {
                                        val r = zis.read(buf)
                                        if (r == -1) break
                                        fos.write(buf, 0, r)
                                    }
                                }
                            }
                            zis.closeEntry()
                            entry = zis.nextEntry
                        }
                    }
                    zipFile.delete()
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to download/extract Vosk model: ${e.message}", e)
                    zipFile.delete()
                    return null
                }
            }

            if (!isModelReady(modelDir)) return null
            return try {
                val m = Model(modelDir.absolutePath)
                cachedModel = m
                m
            } catch (e: Exception) {
                Log.e(TAG, "Failed to load Vosk model: ${e.message}", e)
                null
            }
        }
    }

    fun transcribeWindow(
        context: Context,
        sourceFile: File,
        startMs: Long,
        endMs: Long,
        onProgress: ((Int, String) -> Unit)? = null
    ): List<YouTubeStreamDownloader.CaptionSegment> {
        val model = ensureModel(context, onProgress) ?: return emptyList()
        onProgress?.invoke(18, "Transcribing spoken voice to live captions...")

        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(sourceFile.absolutePath)
            var audioTrack = -1
            var audioFmt: MediaFormat? = null
            for (i in 0 until extractor.trackCount) {
                val fmt = extractor.getTrackFormat(i)
                val mime = fmt.getString(MediaFormat.KEY_MIME) ?: ""
                if (mime.startsWith("audio/")) {
                    audioTrack = i
                    audioFmt = fmt
                    break
                }
            }
            if (audioTrack < 0 || audioFmt == null) return emptyList()

            val mime = audioFmt.getString(MediaFormat.KEY_MIME) ?: return emptyList()
            var sampleRate = audioFmt.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            var channels = audioFmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT)

            extractor.selectTrack(audioTrack)
            extractor.seekTo(startMs * 1000L, MediaExtractor.SEEK_TO_CLOSEST_SYNC)

            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(audioFmt, null, null, 0)
            codec.start()

            val recognizer = Recognizer(model, 16000.0f).apply {
                setWords(true)
            }

            val segments = mutableListOf<YouTubeStreamDownloader.CaptionSegment>()
            val info = MediaCodec.BufferInfo()
            val startUs = startMs * 1000L
            val endUs = endMs * 1000L
            var inputDone = false
            var outputDone = false
            val pcmOut = ByteArrayOutputStream(8192)

            while (!outputDone) {
                if (!inputDone) {
                    val inIdx = codec.dequeueInputBuffer(10_000)
                    if (inIdx >= 0) {
                        val inBuf = codec.getInputBuffer(inIdx)
                        if (inBuf != null) {
                            val sz = extractor.readSampleData(inBuf, 0)
                            val pts = extractor.sampleTime
                            if (sz < 0 || pts > endUs) {
                                codec.queueInputBuffer(inIdx, 0, 0, 0L, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                                inputDone = true
                            } else {
                                codec.queueInputBuffer(inIdx, 0, sz, pts, 0)
                                extractor.advance()
                            }
                        }
                    }
                }

                val outIdx = codec.dequeueOutputBuffer(info, 10_000)
                if (outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    val outFmt = codec.outputFormat
                    if (outFmt.containsKey(MediaFormat.KEY_SAMPLE_RATE)) {
                        sampleRate = outFmt.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                    }
                    if (outFmt.containsKey(MediaFormat.KEY_CHANNEL_COUNT)) {
                        channels = outFmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    }
                } else if (outIdx >= 0) {
                    if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                        outputDone = true
                    }
                    val outBuf = codec.getOutputBuffer(outIdx)
                    if (outBuf != null && info.size > 0 && info.presentationTimeUs >= startUs) {
                        outBuf.position(info.offset)
                        outBuf.limit(info.offset + info.size)
                        val resampled = resampleTo16kMono(outBuf, info.size, sampleRate, channels)
                        if (resampled.isNotEmpty()) {
                            pcmOut.write(resampled)
                            if (pcmOut.size() >= 6400) {
                                val chunk = pcmOut.toByteArray()
                                pcmOut.reset()
                                if (recognizer.acceptWaveForm(chunk, chunk.size)) {
                                    parseVoskJson(recognizer.result, startMs, segments)
                                }
                            }
                        }
                    }
                    codec.releaseOutputBuffer(outIdx, false)
                }
            }

            if (pcmOut.size() > 0) {
                val rem = pcmOut.toByteArray()
                recognizer.acceptWaveForm(rem, rem.size)
            }
            parseVoskJson(recognizer.finalResult, startMs, segments)
            recognizer.close()

            Log.i(TAG, "Vosk transcribed ${segments.size} spoken caption segments for ${startMs}..${endMs}ms")
            return segments
        } catch (e: Exception) {
            Log.e(TAG, "Offline transcription error: ${e.message}", e)
            return emptyList()
        } finally {
            try { codec?.stop() } catch (_: Exception) {}
            try { codec?.release() } catch (_: Exception) {}
            try { extractor.release() } catch (_: Exception) {}
        }
    }

    private fun resampleTo16kMono(
        buf: ByteBuffer,
        byteSize: Int,
        srcRate: Int,
        channels: Int
    ): ByteArray {
        val shortBuf = buf.order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val totalShorts = byteSize / 2
        val ch = channels.coerceAtLeast(1)
        val frameCount = totalShorts / ch
        if (frameCount <= 0) return ByteArray(0)

        val mono = ShortArray(frameCount)
        for (i in 0 until frameCount) {
            var sum = 0
            for (c in 0 until ch) {
                sum += shortBuf.get(i * ch + c).toInt()
            }
            mono[i] = (sum / ch).toShort()
        }

        if (srcRate == 16000) {
            val out = ByteArray(frameCount * 2)
            ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().put(mono)
            return out
        }

        val ratio = srcRate.toDouble() / 16000.0
        val outLen = (frameCount / ratio).toInt().coerceAtLeast(1)
        val out = ByteArray(outLen * 2)
        val outShorts = ShortArray(outLen)
        for (i in 0 until outLen) {
            val srcPos = i * ratio
            val idx0 = srcPos.toInt().coerceIn(0, frameCount - 1)
            val idx1 = (idx0 + 1).coerceIn(0, frameCount - 1)
            val frac = srcPos - idx0
            val sample = mono[idx0] * (1.0 - frac) + mono[idx1] * frac
            outShorts[i] = sample.toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().put(outShorts)
        return out
    }

    private fun parseVoskJson(
        jsonStr: String,
        clipStartMs: Long,
        outSegments: MutableList<YouTubeStreamDownloader.CaptionSegment>
    ) {
        try {
            val root = JSONObject(jsonStr)
            val words = root.optJSONArray("result")
            if (words != null && words.length() > 0) {
                val chunkWords = mutableListOf<String>()
                var segStartMs = -1L
                var segEndMs = -1L
                for (i in 0 until words.length()) {
                    val w = words.optJSONObject(i) ?: continue
                    val wordTxt = w.optString("word", "").trim()
                    if (wordTxt.isEmpty()) continue
                    val wStart = clipStartMs + (w.optDouble("start", 0.0) * 1000.0).toLong()
                    val wEnd = clipStartMs + (w.optDouble("end", 0.0) * 1000.0).toLong()
                    if (segStartMs < 0L) segStartMs = wStart
                    segEndMs = wEnd.coerceAtLeast(segStartMs + 350L)
                    chunkWords.add(wordTxt)
                    if (chunkWords.size >= 4) {
                        outSegments.add(
                            YouTubeStreamDownloader.CaptionSegment(
                                segStartMs,
                                segEndMs,
                                chunkWords.joinToString(" ")
                            )
                        )
                        chunkWords.clear()
                        segStartMs = -1L
                    }
                }
                if (chunkWords.isNotEmpty() && segStartMs >= 0L) {
                    outSegments.add(
                        YouTubeStreamDownloader.CaptionSegment(
                            segStartMs,
                            segEndMs.coerceAtLeast(segStartMs + 500L),
                            chunkWords.joinToString(" ")
                        )
                    )
                }
            }
        } catch (_: Exception) {}
    }
}

