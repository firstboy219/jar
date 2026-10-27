package online.cosger.jarvis.ui.console

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The desk's full-screen area (ADR-062): when the owner opens an area full screen on the desk page, the app gets out of the way —
 * no bottom tabs, no strip of native buttons, no status/navigation bars — so the area really fills the phone. The page says so through
 * its JavaScript bridge; Back (or the page's Keluar) ends it.
 */
object DeskChrome {
    private val full = MutableStateFlow(false)
    val fullscreen: StateFlow<Boolean> = full.asStateFlow()
    fun setFullscreen(on: Boolean) { full.value = on }
}
