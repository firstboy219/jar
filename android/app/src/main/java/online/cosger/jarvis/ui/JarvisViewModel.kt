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
    val screenSharing = engine.screenSharing
    val cameraOn = engine.cameraOn
    val stage = engine.stage
    val brain = engine.brain
    val sttEngine = engine.sttEngine
    val console = engine.console
    val meetings = engine.meetings

    fun saveSettings(serverUrl: String, token: String, speak: Boolean) = engine.saveSettings(serverUrl, token, speak)
    fun setShareLocation(enabled: Boolean) = engine.setShareLocation(enabled)
    fun setReadNotifications(enabled: Boolean) = engine.setReadNotifications(enabled)
    fun locationPermissionMissing() = engine.locationPermissionMissing()
    fun newConversation() = engine.newConversation()
    fun dismissNotice() = engine.dismissNotice()
    fun prefetchVoice() = engine.prefetchVoice()
    fun toggleMute() = engine.toggleMute()
    fun sendText(text: String) = engine.sendText(text)
    fun acknowledge(reportId: Long) = engine.acknowledge(reportId)
    fun repeatReport(reportId: Long) = engine.repeatReport(reportId)
    fun cancelTask(taskId: Long) = engine.cancelTask(taskId)
    fun stopScreenShare() = engine.stopScreenShare()
    fun dismissMedia(seq: Long) = engine.dismissMedia(seq)
    fun setCamera(on: Boolean) = engine.setCamera(on)
    fun setCameraFrameSource(source: (() -> String?)?) { engine.cameraFrame = source }
    fun setUseCalendar(enabled: Boolean) = engine.setUseCalendar(enabled)
    fun stageEvent(event: String, detail: Map<String, Int>) = engine.stageEvent(event, detail)
    fun prepareMeeting() = engine.prepareMeeting()
    fun notify(text: String) = engine.notify(text)
    fun askReplyDraft() = engine.askReplyDraft()
    suspend fun refreshComposition() = engine.refreshComposition()
    suspend fun refreshBrain() = engine.refreshBrain()
}
