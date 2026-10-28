package online.cosger.jarvis.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.attach.AttachmentUploader
import online.cosger.jarvis.attach.PendingAttachment
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.obj

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
    val updater = engine.updater
    val phoneApprovals = engine.phoneApprovals
    suspend fun approvePhoneRun(id: Long, password: String) = engine.approvePhoneRun(id, password)
    fun rejectPhoneRun(id: Long) = engine.rejectPhoneRun(id)
    fun refreshPhoneApprovals() = engine.refreshPhoneApprovals()

    fun saveSettings(serverUrl: String, token: String, speak: Boolean) = engine.saveSettings(serverUrl, token, speak)
    suspend fun signIn(serverUrl: String, password: String, speak: Boolean) = engine.signIn(serverUrl, password, speak)
    fun setShareLocation(enabled: Boolean) = engine.setShareLocation(enabled)
    fun setReadNotifications(enabled: Boolean) = engine.setReadNotifications(enabled)
    fun locationPermissionMissing() = engine.locationPermissionMissing()
    fun newConversation() = engine.newConversation()
    fun dismissNotice() = engine.dismissNotice()
    fun prefetchVoice() = engine.prefetchVoice()
    fun toggleMute() = engine.toggleMute()
    fun sendText(text: String) = engine.sendText(text)
    fun sendMessage(text: String, files: List<PendingAttachment>) = engine.sendMessage(text, files)
    fun describeAttachment(uri: android.net.Uri) = AttachmentUploader(getApplication(), console).describe(uri)
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
    fun setWakeWord(enabled: Boolean, sensitive: Boolean) = engine.setWakeWord(enabled, sensitive)
    fun setBargeIn(enabled: Boolean) = engine.setBargeIn(enabled)
    val wakeListening = engine.wakeListening
    fun notify(text: String) = engine.notify(text)
    fun askReplyDraft() = engine.askReplyDraft()
    suspend fun refreshComposition() = engine.refreshComposition()
    suspend fun refreshBrain() = engine.refreshBrain()
    suspend fun refreshVoice() = engine.refreshVoice()
    suspend fun previewVoice(model: String, voice: String) = engine.previewVoice(model, voice)

    /** Netralkan: stop (and keep) all work and free CPU/memory on the server. */
    fun relieve() = viewModelScope.launch {
        runCatching { console.post("/api/v1/console/relieve").obj() }
            .onSuccess { r -> notify("Server dinetralkan: ${r["stopped"].arr().size} tugas dihentikan & disimpan. Hasilnya dilaporkan sebentar lagi.") }
            .onFailure { notify(it.message ?: "Gagal menetralkan server") }
    }

    /** A stopped task: run it again (it continues from what it had done) or close it. */
    fun retryTask(taskId: Long) = viewModelScope.launch {
        runCatching { console.post("/api/v1/console/tasks/$taskId/retry") }
            .onSuccess { notify("Tugas #$taskId dilanjutkan.") }.onFailure { notify(it.message ?: "Gagal") }
    }

    fun closeTask(taskId: Long) = viewModelScope.launch {
        runCatching { console.post("/api/v1/console/tasks/$taskId/close") }
            .onSuccess { engine.forgetTask(taskId) }.onFailure { notify(it.message ?: "Gagal") }
    }
}
