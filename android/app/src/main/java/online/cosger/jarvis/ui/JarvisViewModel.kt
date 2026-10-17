package online.cosger.jarvis.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import online.cosger.jarvis.JarvisApp

data class ChatMessage(val fromUser: Boolean, val text: String, val route: String? = null)

/** Screen-facing view of [online.cosger.jarvis.JarvisEngine], which lives for the whole process. */
class JarvisViewModel(app: Application) : AndroidViewModel(app) {
    private val engine = (app as JarvisApp).engine

    val settings = engine.settings
    val connection = engine.connection
    val mic = engine.mic
    val micLevel = engine.micLevel
    val interim = engine.interim
    val speaking = engine.speaking
    val turn = engine.turn
    val history = engine.history
    val board = engine.board
    val notice = engine.notice

    fun saveSettings(serverUrl: String, token: String, speak: Boolean) = engine.saveSettings(serverUrl, token, speak)
    fun setShareLocation(enabled: Boolean) = engine.setShareLocation(enabled)
    fun locationPermissionMissing() = engine.locationPermissionMissing()
    fun newConversation() = engine.newConversation()
    fun dismissNotice() = engine.dismissNotice()
    fun prefetchVoice() = engine.prefetchVoice()
    fun toggleMute() = engine.toggleMute()
    fun sendText(text: String) = engine.sendText(text)
    fun acknowledge(reportId: Long) = engine.acknowledge(reportId)
    fun repeatReport(reportId: Long) = engine.repeatReport(reportId)
    fun cancelTask(taskId: Long) = engine.cancelTask(taskId)
}
