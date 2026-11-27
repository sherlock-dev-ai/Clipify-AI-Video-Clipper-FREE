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
 * Burns crisp TikTok/Reels-style captions into the lower third of the 720x1280 Short.
 * Caches the rendered Bitmap and only redraws when the active caption text changes.
 */
@UnstableApi
class CaptionBitmapOverlay(
    private val captions: List<YouTubeStreamDownloader.CaptionSegment>,
    private val clipStartMs: Long,
    private val fallbackTitle: String = ""
) : BitmapOverlay() {

    private val width = 680
    private val height = 230
    private var lastText: String? = null
    private var cachedBitmap: Bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)

    private val boldTypeface = Typeface.create("sans-serif-black", Typeface.BOLD)
    private val strokePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
        textSize = 54f
        typeface = boldTypeface
        style = Paint.Style.STROKE
        strokeWidth = 14f
        strokeJoin = Paint.Join.ROUND
        setShadowLayer(8f, 0f, 4f, Color.BLACK)
    }
    private val fillPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 54f
        typeface = boldTypeface
        style = Paint.Style.FILL
    }

    override fun getOverlaySettings(presentationTimeUs: Long): OverlaySettings {
        return OverlaySettings.Builder()
            .setOverlayFrameAnchor(0f, 0f)
            .setBackgroundFrameAnchor(0f, -0.68f)
            .build()
    }

    override fun getBitmap(presentationTimeUs: Long): Bitmap {
        val absMs = clipStartMs + (presentationTimeUs / 1000L)
        val activeSeg = captions.firstOrNull { absMs in it.startMs..it.endMs }
        val textToDraw = activeSeg?.text?.takeIf { it.isNotBlank() }
            ?: if ((presentationTimeUs / 1_000_000L) < 4L && fallbackTitle.isNotBlank()) fallbackTitle else ""

        if (textToDraw == lastText) {
            return cachedBitmap
        }
        lastText = textToDraw

        cachedBitmap.eraseColor(Color.TRANSPARENT)
        if (textToDraw.isEmpty()) {
            return cachedBitmap
        }

        val canvas = Canvas(cachedBitmap)
        val displayTxt = textToDraw.take(88).uppercase()
        val textWidth = width - 40
        // White & Yellow default viral caption styling: highlight key/alternating words in #FFE500
        val yellowColor = Color.parseColor("#FFE500")
        val styledText = SpannableString(displayTxt)
        val wordRegex = Regex("\\S+")
        val matches = wordRegex.findAll(displayTxt).toList()
        matches.forEachIndexed { idx, m ->
            if (idx % 3 == 1 || (matches.size == 1 && idx == 0)) {
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
            .setMaxLines(3)
            .build()
        val fillLayout = StaticLayout.Builder.obtain(styledText, 0, styledText.length, fillPaint, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setMaxLines(3)
            .build()

        val boxH = (fillLayout.height + 16f).coerceAtMost(height.toFloat() - 8f)
        val topY = (height - boxH) / 2f

        canvas.save()
        canvas.translate(20f, topY + 8f)
        strokeLayout.draw(canvas)
        fillLayout.draw(canvas)
        canvas.restore()

        return cachedBitmap
    }
}

