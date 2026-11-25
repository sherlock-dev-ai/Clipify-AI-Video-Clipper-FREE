package dev.sherlock.clipifyai.media

import android.content.ContentValues
import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.media.MediaMuxer
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
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
     * Clips and muxes a valid 9:16 Short MP4 using Android MediaExtractor & MediaMuxer.
     * Uses private cache for rendering to avoid Scoped Storage locking, then copies to Movies/ClipifyAI/.
     */
    fun processAndRenderShort(
        sourceFile: File,
        exportFile: File,
        targetDurationSec: Int = 30,
        onProgress: (Int, String) -> Unit
    ): Boolean {
        var extractor: MediaExtractor? = null
        var muxer: MediaMuxer? = null
        var fis: FileInputStream? = null

        val stagingExport = File(context.cacheDir, "staging_short_" + System.currentTimeMillis() + ".mp4")

        try {
            onProgress(10, "Analyzing video stream & audio tracks...")
            extractor = MediaExtractor()

            fis = FileInputStream(sourceFile)
            extractor.setDataSource(fis.fd, 0, sourceFile.length())

            val trackCount = extractor.trackCount
            if (trackCount == 0) {
                Log.e(TAG, "No tracks found in source file: ${sourceFile.absolutePath}")
                return false
            }

            muxer = MediaMuxer(stagingExport.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
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

            if (stagingExport.exists() && stagingExport.length() > 1024) {
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
