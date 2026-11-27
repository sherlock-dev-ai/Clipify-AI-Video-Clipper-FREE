package dev.sherlock.clipifyai.media

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
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

    private val width = 660
    private val height = 180
    private var lastText: String? = null
    private var cachedBitmap: Bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)

    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(185, 12, 12, 18)
        style = Paint.Style.FILL
    }
    private val strokePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
        textSize = 40f
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        style = Paint.Style.STROKE
        strokeWidth = 9f
        strokeJoin = Paint.Join.ROUND
    }
    private val fillPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 40f
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
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
        val displayTxt = textToDraw.take(88)
        val textWidth = width - 40
        val strokeLayout = StaticLayout.Builder.obtain(displayTxt, 0, displayTxt.length, strokePaint, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setMaxLines(3)
            .build()
        val fillLayout = StaticLayout.Builder.obtain(displayTxt, 0, displayTxt.length, fillPaint, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setMaxLines(3)
            .build()

        val boxH = (fillLayout.height + 28f).coerceAtMost(height.toFloat() - 8f)
        val topY = (height - boxH) / 2f
        canvas.drawRoundRect(RectF(12f, topY, width - 12f, topY + boxH), 22f, 22f, bgPaint)

        canvas.save()
        canvas.translate(20f, topY + 14f)
        strokeLayout.draw(canvas)
        fillLayout.draw(canvas)
        canvas.restore()

        return cachedBitmap
    }
}

