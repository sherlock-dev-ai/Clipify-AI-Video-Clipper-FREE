package dev.sherlock.clipifyai.media

import android.content.Context
import android.opengl.GLES20
import androidx.media3.common.VideoFrameProcessingException
import androidx.media3.common.util.GlProgram
import androidx.media3.common.util.GlUtil
import androidx.media3.common.util.Size
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.BaseGlShaderProgram
import androidx.media3.effect.GlEffect
import androidx.media3.effect.GlShaderProgram

/**
 * Renders a crisp 2-panel 9:16 (up to 4K 2160x3840 / 2K / 1080x1920) split-screen composition
 * with unsharp-mask sharpening on both the top gameplay panel and bottom facecam panel.
 */
@UnstableApi
class SplitScreenGlEffect(
    private val camCenterX: Float = 0.5f,
    private val camCenterY: Float = 0.5f,
    private val camZoom: Float = 0.55f,
    private val outWidth: Int = 1080,
    private val outHeight: Int = 1920
) : GlEffect {

    override fun toGlShaderProgram(context: Context, useHdr: Boolean): GlShaderProgram {
        return SplitScreenShaderProgram(useHdr, camCenterX, camCenterY, camZoom.coerceIn(0.25f, 0.75f), outWidth, outHeight)
    }

    private class SplitScreenShaderProgram(
        useHdr: Boolean,
        private val camCenterX: Float,
        private val camCenterY: Float,
        private val camZoom: Float,
        private val outWidth: Int,
        private val outHeight: Int
    ) : BaseGlShaderProgram(useHdr, 1) {

        private var glProgram: GlProgram? = null
        private var srcWidth = 1280
        private var srcHeight = 720

        override fun configure(inputWidth: Int, inputHeight: Int): Size {
            srcWidth = inputWidth.coerceAtLeast(1)
            srcHeight = inputHeight.coerceAtLeast(1)
            if (glProgram == null) {
                try {
                    glProgram = GlProgram(VERTEX_SHADER, FRAGMENT_SHADER).apply {
                        setBufferAttribute(
                            "aFramePosition",
                            GlUtil.getNormalizedCoordinateBounds(),
                            GlUtil.HOMOGENEOUS_COORDINATE_VECTOR_SIZE
                        )
                    }
                } catch (e: Exception) {
                    throw VideoFrameProcessingException(e)
                }
            }
            return Size(outWidth, outHeight)
        }

        override fun drawFrame(inputTexId: Int, presentationTimeUs: Long) {
            val program = glProgram ?: return
            try {
                program.use()
                program.setSamplerTexIdUniform("uTexSampler", inputTexId, 0)
                program.setFloatUniform("uSrcAspect", srcWidth.toFloat() / srcHeight.toFloat())
                program.setFloatUniform("uCamX", camCenterX)
                program.setFloatUniform("uCamY", camCenterY)
                program.setFloatUniform("uCamZoom", camZoom)
                program.setFloatUniform("uTexelX", 1.0f / srcWidth.toFloat())
                program.setFloatUniform("uTexelY", 1.0f / srcHeight.toFloat())
                program.bindAttributesAndUniforms()
                GLES20.glClearColor(0.04f, 0.04f, 0.07f, 1.0f)
                GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT)
                GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
            } catch (e: Exception) {
                throw VideoFrameProcessingException(e)
            }
        }

        override fun release() {
            super.release()
            try {
                glProgram?.delete()
            } catch (_: Exception) {}
            glProgram = null
        }

        companion object {
            private const val VERTEX_SHADER = """
                attribute vec4 aFramePosition;
                varying vec2 vTexCoords;
                void main() {
                    gl_Position = aFramePosition;
                    vTexCoords = vec2(aFramePosition.x * 0.5 + 0.5, aFramePosition.y * 0.5 + 0.5);
                }
            """

            private const val FRAGMENT_SHADER = """
                precision mediump float;
                uniform sampler2D uTexSampler;
                uniform float uSrcAspect;
                uniform float uCamX;
                uniform float uCamY;
                uniform float uCamZoom;
                uniform float uTexelX;
                uniform float uTexelY;
                varying vec2 vTexCoords;

                vec4 sampleSharpened(vec2 uv, float amount) {
                    vec2 c = clamp(uv, 0.0, 1.0);
                    vec4 center = texture2D(uTexSampler, c);
                    vec4 blur = (
                        texture2D(uTexSampler, clamp(c + vec2(uTexelX, 0.0), 0.0, 1.0)) +
                        texture2D(uTexSampler, clamp(c - vec2(uTexelX, 0.0), 0.0, 1.0)) +
                        texture2D(uTexSampler, clamp(c + vec2(0.0, uTexelY), 0.0, 1.0)) +
                        texture2D(uTexSampler, clamp(c - vec2(0.0, uTexelY), 0.0, 1.0))
                    ) * 0.25;
                    return clamp(center + (center - blur) * amount, 0.0, 1.0);
                }

                void main() {
                    float panelAspect = 1.125; // 9:8 half-frame panel

                    if (vTexCoords.y >= 0.5) {
                        // TOP PANEL: Edge-to-edge cover-crop gameplay (avoid duplicating corner webcam)
                        float localY = (vTexCoords.y - 0.5) * 2.0;
                        float localX = vTexCoords.x;
                        float sx;
                        float sy;
                        if (uSrcAspect >= panelAspect) {
                            float spanX = panelAspect / uSrcAspect;
                            float gameCenterX = 0.5;
                            if (uCamX < 0.28) {
                                gameCenterX = 0.56;
                            } else if (uCamX > 0.72) {
                                gameCenterX = 0.44;
                            }
                            gameCenterX = clamp(gameCenterX, spanX * 0.5, 1.0 - spanX * 0.5);
                            sx = gameCenterX + (localX - 0.5) * spanX;
                            sy = localY;
                        } else {
                            float spanY = uSrcAspect / panelAspect;
                            sx = localX;
                            sy = 0.5 + (localY - 0.5) * spanY;
                        }
                        gl_FragColor = sampleSharpened(vec2(sx, sy), 0.55);
                    } else {
                        // BOTTOM PANEL: Edge-to-edge facecam / reaction focus
                        float localY = vTexCoords.y * 2.0;
                        float localX = vTexCoords.x;
                        float spanY = min(uCamZoom, 1.0);
                        float spanX = spanY * (panelAspect / uSrcAspect);
                        if (spanX > 1.0) {
                            spanX = 1.0;
                            spanY = min(1.0, uSrcAspect / panelAspect);
                        }
                        float cx = clamp(uCamX, spanX * 0.5, 1.0 - spanX * 0.5);
                        float cy = clamp(uCamY, spanY * 0.5, 1.0 - spanY * 0.5);
                        float sx = cx + (localX - 0.5) * spanX;
                        float sy = cy + (localY - 0.5) * spanY;
                        gl_FragColor = sampleSharpened(vec2(sx, sy), 0.75);
                    }
                }
            """
        }
    }
}
