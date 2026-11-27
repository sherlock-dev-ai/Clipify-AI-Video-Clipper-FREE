package dev.sherlock.clipifyai.media

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.SpannableString
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.ForegroundColorSpan
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.BitmapOverlay
import androidx.media3.effect.OverlaySettings
import dev.sherlock.clipifyai.network.YouTubeStreamDownloader

/**
 * Burns crisp, proportionally-scaled TikTok/Reels/Shorts-style captions into any output resolution
 * (1080x1920, 1440x2560, 2160x3840, 720x1280) with 2-4 word viral pacing and #FFE500 highlights.
 */
@UnstableApi
class CaptionBitmapOverlay(
    private val captions: List<YouTubeStreamDownloader.CaptionSegment>,
    private val clipStartMs: Long,
    private val fallbackTitle: String = "",
    private val outWidth: Int = 1080,
    private val outHeight: Int = 1920,
    private val isSplitScreen: Boolean = false
) : BitmapOverlay() {

    private val width = (outWidth * 0.92f).toInt().coerceAtLeast(640)
    private val height = (outHeight * 0.22f).toInt().coerceAtLeast(220)
    private var lastText: String? = null
    private var cachedBitmap: Bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)

    private val chunkedCaptions: List<YouTubeStreamDownloader.CaptionSegment> = buildViralChunks(captions)

    private val scaledTextSize = (outWidth * 0.068f).coerceIn(48f, 160f)
    private val boldTypeface = Typeface.create("sans-serif-black", Typeface.BOLD)
    private val strokePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
        textSize = scaledTextSize
        typeface = boldTypeface
        style = Paint.Style.STROKE
        strokeWidth = (scaledTextSize * 0.24f).coerceAtLeast(12f)
        strokeJoin = Paint.Join.ROUND
        setShadowLayer(scaledTextSize * 0.16f, 0f, scaledTextSize * 0.08f, Color.argb(235, 0, 0, 0))
    }
    private val fillPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = scaledTextSize
        typeface = boldTypeface
        style = Paint.Style.FILL
    }

    private fun buildViralChunks(src: List<YouTubeStreamDownloader.CaptionSegment>): List<YouTubeStreamDownloader.CaptionSegment> {
        if (src.isEmpty()) return emptyList()
        val out = mutableListOf<YouTubeStreamDownloader.CaptionSegment>()
        for (seg in src) {
            val words = seg.text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (words.size <= 4) {
                out.add(seg)
                continue
            }
            val groups = words.chunked(3)
            val totalDur = (seg.endMs - seg.startMs).coerceAtLeast(600L)
            val perGroup = (totalDur / groups.size).coerceAtLeast(350L)
            groups.forEachIndexed { idx, grp ->
                val s = seg.startMs + idx * perGroup
                val e = if (idx == groups.lastIndex) seg.endMs.coerceAtLeast(s + 400L) else (s + perGroup)
                out.add(YouTubeStreamDownloader.CaptionSegment(s, e, grp.joinToString(" ")))
            }
        }
        return out
    }

    override fun getOverlaySettings(presentationTimeUs: Long): OverlaySettings {
        val yAnchor = if (isSplitScreen) -0.02f else -0.50f
        return OverlaySettings.Builder()
            .setOverlayFrameAnchor(0f, 0f)
            .setBackgroundFrameAnchor(0f, yAnchor)
            .build()
    }

    override fun getBitmap(presentationTimeUs: Long): Bitmap {
        val absMs = clipStartMs + (presentationTimeUs / 1000L)
        val activeSeg = chunkedCaptions.firstOrNull { absMs in it.startMs..it.endMs }
        val textToDraw = activeSeg?.text?.takeIf { it.isNotBlank() }
            ?: if ((presentationTimeUs / 1_000_000L) < 3L && fallbackTitle.isNotBlank()) fallbackTitle else ""

        if (textToDraw == lastText) {
            return cachedBitmap
        }
        lastText = textToDraw

        cachedBitmap.eraseColor(Color.TRANSPARENT)
        if (textToDraw.isEmpty()) {
            return cachedBitmap
        }

        val canvas = Canvas(cachedBitmap)
        val displayTxt = textToDraw.take(64).uppercase()
        val textWidth = (width - 48).coerceAtLeast(320)
        val yellowColor = Color.parseColor("#FFE500")
        val styledText = SpannableString(displayTxt)
        val wordRegex = Regex("\\S+")
        val matches = wordRegex.findAll(displayTxt).toList()
        matches.forEachIndexed { idx, m ->
            if (idx == matches.lastIndex || (matches.size >= 3 && idx % 3 == 1)) {
                styledText.setSpan(
                    ForegroundColorSpan(yellowColor),
                    m.range.first,
                    m.range.last + 1,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
        }
        val strokeLayout = StaticLayout.Builder.obtain(displayTxt, 0, displayTxt.length, strokePaint, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setMaxLines(2)
            .build()
        val fillLayout = StaticLayout.Builder.obtain(styledText, 0, styledText.length, fillPaint, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setMaxLines(2)
            .build()

        val boxH = (fillLayout.height + 24f).coerceAtMost(height.toFloat() - 8f)
        val topY = (height - boxH) / 2f

        canvas.save()
        canvas.translate(24f, topY + 12f)
        strokeLayout.draw(canvas)
        fillLayout.draw(canvas)
        canvas.restore()

        return cachedBitmap
    }
}

