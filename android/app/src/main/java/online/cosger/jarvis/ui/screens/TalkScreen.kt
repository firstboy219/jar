package online.cosger.jarvis.ui.screens

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cameraswitch
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.NoPhotography
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.ScreenShare
import androidx.compose.material.icons.filled.StopScreenShare
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import online.cosger.jarvis.camera.CameraPreview
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.screen.ScreenShareService
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.ServerUsage
import online.cosger.jarvis.ui.SpokenReport
import online.cosger.jarvis.ui.ToolActivity
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.Worker
import online.cosger.jarvis.ui.console.MemoryCardDialog
import online.cosger.jarvis.ui.stage.BrainView
import online.cosger.jarvis.ui.stage.StageActions
import online.cosger.jarvis.ui.stage.StageHost
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.theme.JarvisColors
import online.cosger.jarvis.voice.MicState
import kotlin.math.roundToInt

val LOCATION_PERMISSIONS = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)

@Composable
fun TalkScreen(vm: JarvisViewModel, onOpenServer: () -> Unit = {}, onOpenBackground: () -> Unit = {}, compact: Boolean = false) {
    val turn by vm.turn.collectAsStateWithLifecycle()
    val interim by vm.interim.collectAsStateWithLifecycle()
    val level by vm.micLevel.collectAsStateWithLifecycle()
    val mic by vm.mic.collectAsStateWithLifecycle()
    val speaking by vm.speaking.collectAsStateWithLifecycle()
    val board by vm.board.collectAsStateWithLifecycle()
    val connection by vm.connection.collectAsStateWithLifecycle()
    val sharing by vm.screenSharing.collectAsStateWithLifecycle()
    val cameraOn by vm.cameraOn.collectAsStateWithLifecycle()
    val stage by vm.stage.collectAsStateWithLifecycle()
    val wakeListening by vm.wakeListening.collectAsStateWithLifecycle()
    val brain by vm.brain.collectAsStateWithLifecycle()
    var card by remember { mutableStateOf<String?>(null) }
    var frontCamera by remember { mutableStateOf(false) }
    val askCamera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) vm.setCamera(true)
    }
    val context = LocalContext.current
    val askScreen = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            ScreenShareService.start(context, result.resultCode, result.data!!)
        }
    }
    var hasMic by remember {
        mutableStateOf(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    val askPerms = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        hasMic = it[Manifest.permission.RECORD_AUDIO] == true || hasMic
        if (hasMic) vm.toggleMute()
    }
    LaunchedEffect(Unit) { vm.prefetchVoice() } // token ready before the first unmute
    // Server usage on the home screen: refreshed while this screen is shown (owner devices only)
    var server by remember { mutableStateOf<ServerUsage?>(null) }
    var askRelieve by remember { mutableStateOf(false) }
    LaunchedEffect(connection) {
        while (connection == Connection.Connected) {
            server = runCatching { ServerUsage.parse(vm.console.get("/api/v1/console/server-usage").obj()) }.getOrNull()
            delay(15_000)
        }
    }

    TalkContent(
        turn = turn, mic = mic, micLevel = level, interim = interim, speaking = speaking, board = board,
        connected = connection == Connection.Connected,
        onToggleMute = {
            if (hasMic) vm.toggleMute()
            else askPerms.launch(buildList {
                add(Manifest.permission.RECORD_AUDIO)
                if (vm.locationPermissionMissing()) addAll(LOCATION_PERMISSIONS)
                if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
            }.toTypedArray())
        },
        onAck = vm::acknowledge, onRepeat = vm::repeatReport, onCancelTask = vm::cancelTask,
        sharing = sharing,
        onToggleShare = {
            if (sharing) vm.stopScreenShare()
            else askScreen.launch(context.getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent())
        },
        onDismissMedia = vm::dismissMedia,
        cameraOn = cameraOn,
        onToggleCamera = {
            when {
                cameraOn -> vm.setCamera(false)
                context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED -> vm.setCamera(true)
                else -> askCamera.launch(Manifest.permission.CAMERA)
            }
        },
        camera = { CameraPreview(frontCamera, vm::setCameraFrameSource, Modifier.fillMaxSize()) },
        onFlipCamera = { frontCamera = !frontCamera },
        panelOpen = stage.panel != null,
        stageContent = {
            val workersBusy = board.workers.any { it.active }
            StageHost(stage, brain, orbPhase(turn, mic, speaking, workersBusy) != Phase.Idle,
                StageActions(vm.console, vm::stageEvent, vm::notify, mic == MicState.Hearing), Modifier.fillMaxSize(),
                onNode = { card = it })
        },
        compact = compact,
        background = if (compact) null else ({
            // JARVIS' brain fills the whole home screen, behind everything; nodes light up as memories are used
            val workersBusy = board.workers.any { it.active }
            BrainView(brain, stage.pulses, orbPhase(turn, mic, speaking, workersBusy) != Phase.Idle, Modifier.fillMaxSize(),
                onNode = { card = it }, captionAlignment = Alignment.TopCenter, captionPadding = PaddingValues(top = 46.dp),
                dim = if (stage.panel != null || cameraOn) 0.45f else 1f, centerY = BRAIN_CENTER_Y, zoom = BRAIN_ZOOM)
        }),
        involved = stage.involved.map { it.label },
        server = server,
        onServerTap = onOpenServer,
        onBackgroundTap = onOpenBackground,
        onRelieve = { askRelieve = true },
        onRetryTask = vm::retryTask,
        onCloseTask = vm::closeTask,
        onReply = { vm.askReplyDraft() },
        wakeListening = wakeListening,
    )
    card?.let { id -> MemoryCardDialog(vm, id) { card = null } }
    if (askRelieve) RelieveDialog({ askRelieve = false }) { askRelieve = false; vm.relieve() }
}

/** The home brain sits behind the readiness ring and reaches well past it (fractions of the screen). */
const val BRAIN_CENTER_Y = 0.33f
const val BRAIN_ZOOM = 1.45f

/** What the orb shows: the owner speaking, JARVIS speaking, the main agent thinking, or workers busy. */
fun orbPhase(turn: TurnState, mic: MicState, speaking: Boolean, workersBusy: Boolean): Phase = when {
    speaking -> Phase.Answering
    mic == MicState.Hearing -> Phase.Listening
    turn.phase == Phase.Thinking || turn.phase == Phase.Acting || turn.phase == Phase.Answering -> Phase.Thinking
    turn.phase == Phase.Failed -> Phase.Failed
    workersBusy -> Phase.Acting
    else -> Phase.Idle
}

/** Stateless so it can be screenshotted with any state. */
@Composable
fun TalkContent(
    turn: TurnState,
    mic: MicState,
    micLevel: Float,
    interim: String,
    speaking: Boolean,
    board: Board,
    connected: Boolean,
    onToggleMute: () -> Unit,
    onAck: (Long) -> Unit,
    onRepeat: (Long) -> Unit,
    onCancelTask: (Long) -> Unit,
    sharing: Boolean = false,
    onToggleShare: () -> Unit = {},
    onDismissMedia: (Long) -> Unit = {},
    cameraOn: Boolean = false,
    onToggleCamera: () -> Unit = {},
    camera: @Composable () -> Unit = {},
    onFlipCamera: () -> Unit = {},
    panelOpen: Boolean = false,
    stageContent: (@Composable () -> Unit)? = null,
    onReply: () -> Unit = {},
    wakeListening: Boolean = false,
    background: (@Composable () -> Unit)? = null,
    involved: List<String> = emptyList(),
    server: ServerUsage? = null,
    onServerTap: () -> Unit = {},
    onBackgroundTap: () -> Unit = {},
    onRelieve: () -> Unit = {},
    onRetryTask: (Long) -> Unit = {},
    onCloseTask: (Long) -> Unit = {},
    /** On the desk (Meja) the conversation is a sheet over the 3D canvas: no brain of its own, a small readiness ring instead. */
    compact: Boolean = false,
) {
    val workers = board.workers.filter { it.active }
    val phase = orbPhase(turn, mic, speaking, workers.isNotEmpty())
    Box(Modifier.fillMaxSize().then(if (compact) Modifier else Modifier.background(JarvisColors.Background))) {
        background?.let {
            Box(Modifier.fillMaxSize()) { it() }
            // keep the conversation readable over the brain: darker towards the bottom
            Box(Modifier.fillMaxSize().background(Brush.verticalGradient(
                0f to Color.Transparent, 0.42f to Color.Transparent, 0.62f to JarvisColors.Background.copy(alpha = 0.75f),
                1f to JarvisColors.Background.copy(alpha = 0.92f))))
        }
        Column(
            Modifier.fillMaxSize().padding(horizontal = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Header(connected, workers.size, sharing, onToggleShare, cameraOn, onToggleCamera, top = if (compact) 4.dp else 14.dp)
            server?.let { ServerStrip(it, onServerTap, onBackgroundTap, onRelieve) }
            if (sharing) ShareBanner(onToggleShare, onReply)

            if (cameraOn) {
                // Point the camera at something and talk: JARVIS sees the frame with each utterance.
                Box(
                    Modifier.fillMaxWidth().height(260.dp).padding(top = 8.dp).clip(RoundedCornerShape(18.dp))
                        .border(3.dp, micColor(mic), RoundedCornerShape(18.dp)),
                ) {
                    camera()
                    Row(Modifier.align(Alignment.BottomEnd).padding(8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.size(40.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.5f)).clickable(onClick = onFlipCamera),
                            contentAlignment = Alignment.Center) { Icon(Icons.Filled.Cameraswitch, "Ganti kamera", tint = Color.White) }
                    }
                    Text("JARVIS melihat ini saat kamu bicara", color = Color.White, fontSize = 11.sp,
                        modifier = Modifier.align(Alignment.TopStart).padding(10.dp).clip(RoundedCornerShape(8.dp))
                            .background(Color.Black.copy(alpha = 0.5f)).padding(horizontal = 8.dp, vertical = 4.dp))
                }
                Spacer(Modifier.height(8.dp))
            } else if (panelOpen && stageContent != null) {
                // JARVIS opened something for this conversation: music, video, map, web, document, drafts
                Box(Modifier.fillMaxWidth().height(if (compact) 300.dp else 400.dp).padding(top = 8.dp)) { stageContent() }
                Spacer(Modifier.height(6.dp))
            } else if (compact) {
                Box(Modifier.fillMaxWidth().height(92.dp), contentAlignment = Alignment.Center) {
                    ReadinessRing(mic, Modifier.size(84.dp))
                    ThoughtOrb(phase, if (mic == MicState.Hearing) micLevel else 0f, if (workers.isNotEmpty()) 0.5f else 0f, Modifier.size(52.dp))
                }
            } else {
                Box(Modifier.fillMaxWidth().height(250.dp), contentAlignment = Alignment.Center) {
                    // Default: JARVIS' brain — its memories in 3D (full-screen background, or here when there is none);
                    // the orb shows on top while it listens/thinks/talks.
                    if (background == null) stageContent?.let { Box(Modifier.fillMaxSize()) { it() } }
                    ReadinessRing(mic, Modifier.size(226.dp))
                    val brainShown = stageContent != null || background != null
                    if (!brainShown || phase != Phase.Idle) {
                        ThoughtOrb(phase, if (mic == MicState.Hearing) micLevel else 0f, if (workers.isNotEmpty()) 0.5f else 0f,
                            Modifier.size(if (brainShown) 110.dp else 180.dp))
                    }
                }
            }
            ReadinessLabel(mic, connected, wakeListening)
            if (involved.isNotEmpty()) InvolvedMemories(involved)

            Column(
                Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).animateContentSize(),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Spacer(Modifier.height(4.dp))
                val heard = if (mic == MicState.Hearing && interim.isNotBlank()) interim else turn.userText
                if (heard.isNotBlank()) {
                    Text("“$heard”", color = JarvisColors.Text, fontSize = 15.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
                if (turn.answer.isNotBlank()) {
                    Text(turn.answer, color = JarvisColors.Ice, fontSize = 15.sp, lineHeight = 21.sp)
                }
                turn.error?.let { Text(it, color = JarvisColors.Red, fontSize = 13.sp) }

                board.media.take(2).forEach { MediaCard(it, onDismissMedia) }
                board.openReports.forEach { ReportCard(it, onAck, onRepeat) }
                if (board.stoppedWorkers.isNotEmpty()) {
                    Text("DIHENTIKAN · ${board.stoppedWorkers.size} — lanjutkan atau tutup", color = JarvisColors.Violet,
                        fontSize = 10.sp, letterSpacing = 2.sp)
                    board.stoppedWorkers.forEach { StoppedCard(it, onRetryTask, onCloseTask) }
                }
                if (workers.isNotEmpty()) {
                    Text("SEDANG DIKERJAKAN · ${workers.size}", color = JarvisColors.Amber, fontSize = 10.sp, letterSpacing = 2.sp)
                    workers.forEach { WorkerCard(it, onCancelTask) }
                }
                Spacer(Modifier.height(8.dp))
            }

            MuteButton(mic, onToggleMute)
            Spacer(Modifier.height(14.dp))
        }
    }
}

/**
 * CPU, memory, disk and AI spend of the JARVIS server, always visible — and WHO uses them (which service,
 * for whose work, who waits for a turn). Tap for the dashboard; "Netralkan" frees the server.
 */
@Composable
private fun ServerStrip(u: ServerUsage, onTap: () -> Unit, onBackground: () -> Unit, onRelieve: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(top = 8.dp).clip(RoundedCornerShape(12.dp))
            .background(JarvisColors.Surface.copy(alpha = 0.78f)).border(1.dp, JarvisColors.Border, RoundedCornerShape(12.dp))
            .clickable(onClick = onTap).padding(horizontal = 10.dp, vertical = 7.dp),
    ) {
        MeterRow(u)
        Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f).clickable(onClick = onBackground)) {  // → "Di balik layar"
                if (u.busiest().isNotBlank()) {
                    Text("Dipakai: ${u.busiest()}", color = JarvisColors.Text, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text("untuk ${u.purpose()} ›", color = JarvisColors.Muted, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.width(8.dp))
            Text("Netralkan", color = if (u.cpuPct >= 85 || u.ramPct >= 85) JarvisColors.Red else JarvisColors.Cyan, fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(14.dp))
                    .border(1.dp, (if (u.cpuPct >= 85 || u.ramPct >= 85) JarvisColors.Red else JarvisColors.Cyan).copy(alpha = 0.6f), RoundedCornerShape(14.dp))
                    .clickable(onClick = onRelieve).padding(horizontal = 10.dp, vertical = 4.dp))
        }
    }
}

@Composable
private fun MeterRow(u: ServerUsage) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Meter("CPU", "${u.cpuPct.roundToInt()}%", u.cpuPct, Modifier.weight(1f))
        Meter("RAM", "${"%.1f".format(u.ramUsedGb)}/${u.ramTotalGb.roundToInt()} GB", u.ramPct, Modifier.weight(1.3f))
        Meter("DISK", "${u.diskPct.roundToInt()}%", u.diskPct, Modifier.weight(1f))
        val aiPct = if (u.aiBudgetUsd > 0) 100 * u.aiSpentUsd / u.aiBudgetUsd else 0.0
        Meter("AI", "$${"%.2f".format(u.aiSpentUsd)}", aiPct, Modifier.weight(1f))
    }
}

@Composable
private fun Meter(label: String, value: String, pct: Double, modifier: Modifier) {
    val color = when {
        pct >= 85 -> JarvisColors.Red
        pct >= 60 -> JarvisColors.Amber
        else -> JarvisColors.Green
    }
    Column(modifier) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(label, color = JarvisColors.Muted, fontSize = 9.sp, letterSpacing = 1.sp)
            Spacer(Modifier.width(4.dp))
            Text(value, color = JarvisColors.Text, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Clip)
        }
        Box(Modifier.padding(top = 3.dp).fillMaxWidth().height(3.dp).clip(RoundedCornerShape(2.dp)).background(JarvisColors.SurfaceHigh)) {
            Box(Modifier.fillMaxWidth((pct / 100).coerceIn(0.02, 1.0).toFloat()).height(3.dp).background(color))
        }
    }
}

/** Netralkan asks first: what happens, and what is NOT touched. */
@Composable
fun RelieveDialog(onDismiss: () -> Unit, onConfirm: () -> Unit) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Netralkan server?") },
        text = {
            Text("Semua tugas yang sedang berjalan dihentikan dan DISIMPAN beserta kemajuannya — nanti bisa kamu ulangi " +
                "(melanjutkan dari situ) atau tutup. Hermes dimulai ulang untuk membebaskan memori, dan pekerjaan latar " +
                "belakang JARVIS istirahat 15 menit.\n\nMemori, obrolan, dokumen, password, dan pengaturan tidak disentuh.")
        },
        confirmButton = { androidx.compose.material3.TextButton(onConfirm) { Text("Netralkan") } },
        dismissButton = { androidx.compose.material3.TextButton(onDismiss) { Text("Batal") } },
    )
}

@Composable
private fun StoppedCard(w: Worker, onRetry: (Long) -> Unit, onClose: (Long) -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(JarvisColors.Surface)
            .border(1.dp, JarvisColors.Violet.copy(alpha = 0.5f), RoundedCornerShape(14.dp)).padding(12.dp),
    ) {
        Text(w.title, color = JarvisColors.Text, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text("Dihentikan — kemajuannya tersimpan", color = JarvisColors.Muted, fontSize = 11.sp)
        Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Pill("Ulangi", JarvisColors.Green) { onRetry(w.id) }
            Pill("Tutup", JarvisColors.Muted) { onClose(w.id) }
        }
    }
}

/** Which memories JARVIS is using right now (they also light up in the brain behind). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun InvolvedMemories(labels: List<String>) {
    Column(Modifier.fillMaxWidth().padding(bottom = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("MEMORI TERLIBAT", color = JarvisColors.Violet, fontSize = 9.sp, letterSpacing = 2.sp)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
            verticalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.padding(top = 4.dp)) {
            labels.take(4).forEach { label ->
                Text(label, color = JarvisColors.Text, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 220.dp).clip(RoundedCornerShape(12.dp))
                        .background(JarvisColors.Violet.copy(alpha = 0.18f))
                        .border(1.dp, JarvisColors.Violet.copy(alpha = 0.5f), RoundedCornerShape(12.dp))
                        .padding(horizontal = 8.dp, vertical = 3.dp))
            }
        }
    }
}

@Composable
private fun Header(connected: Boolean, workers: Int, sharing: Boolean, onToggleShare: () -> Unit,
                   cameraOn: Boolean, onToggleCamera: () -> Unit, top: androidx.compose.ui.unit.Dp = 14.dp) {
    Row(Modifier.fillMaxWidth().padding(top = top), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(if (connected) JarvisColors.Green else JarvisColors.Amber))
        Spacer(Modifier.width(8.dp))
        Text("JARVIS", color = JarvisColors.Text, fontWeight = FontWeight.Bold, letterSpacing = 3.sp)
        Spacer(Modifier.weight(1f))
        Text(
            if (!connected) "Menghubungkan…" else if (workers > 0) "$workers tugas berjalan" else "Terhubung",
            color = JarvisColors.Muted, fontSize = 12.sp,
        )
        Spacer(Modifier.width(10.dp))
        Icon(
            if (cameraOn) Icons.Filled.NoPhotography else Icons.Filled.PhotoCamera,
            if (cameraOn) "Matikan kamera" else "Tunjukkan sesuatu lewat kamera",
            Modifier.size(22.dp).clickable(onClick = onToggleCamera),
            tint = if (cameraOn) JarvisColors.Red else JarvisColors.Muted,
        )
        Spacer(Modifier.width(10.dp))
        Icon(
            if (sharing) Icons.Filled.StopScreenShare else Icons.Filled.ScreenShare,
            if (sharing) "Berhenti berbagi layar" else "Bagikan layar ke JARVIS",
            Modifier.size(22.dp).clickable(onClick = onToggleShare),
            tint = if (sharing) JarvisColors.Red else JarvisColors.Muted,
        )
    }
}

@Composable
private fun ShareBanner(onStop: () -> Unit, onReply: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp).clip(RoundedCornerShape(10.dp)).background(JarvisColors.Red.copy(alpha = 0.15f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(JarvisColors.Red))
        Spacer(Modifier.width(8.dp))
        Text("Layar dibagikan — JARVIS membaca layarmu setiap kamu bicara", color = JarvisColors.Text, fontSize = 12.sp,
            modifier = Modifier.weight(1f))
        Text("Balas", color = JarvisColors.Cyan, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.clickable(onClick = onReply).padding(horizontal = 8.dp))
        Text("Stop", color = JarvisColors.Red, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.clickable(onClick = onStop))
    }
}

fun micColor(mic: MicState): Color = when (mic) {
    MicState.Muted -> JarvisColors.Muted
    MicState.Preparing -> JarvisColors.Amber
    MicState.Ready, MicState.Hearing -> JarvisColors.Green
    MicState.Paused -> JarvisColors.Cyan
    MicState.Error -> JarvisColors.Red
}

/** The "can I talk now?" signal: a ring that only glows green (and breathes) when JARVIS is listening. */
@Composable
private fun ReadinessRing(mic: MicState, modifier: Modifier) {
    val color by animateColorAsState(micColor(mic), tween(300), label = "ringColor")
    val t = rememberInfiniteTransition(label = "ring")
    val pulse by t.animateFloat(0.35f, 1f, infiniteRepeatable(tween(1_100, easing = LinearEasing), RepeatMode.Reverse), label = "pulse")
    val alpha = when (mic) {
        MicState.Ready -> pulse
        MicState.Hearing -> 1f
        MicState.Muted -> 0.25f
        else -> 0.6f
    }
    Canvas(modifier) {
        drawCircle(color.copy(alpha = alpha), radius = size.minDimension / 2 - 4f, style = Stroke(width = if (mic == MicState.Hearing) 7f else 4f))
    }
}

@Composable
private fun ReadinessLabel(mic: MicState, connected: Boolean, wakeListening: Boolean = false) {
    val (text, sub) = when {
        !connected && mic != MicState.Muted -> "Menghubungkan ke JARVIS…" to "Ucapanmu ditahan dulu, tidak hilang"
        mic == MicState.Muted && wakeListening -> "Ucapkan \"Hey Jarvis\"" to "HP menunggu kata panggil — tidak ada suara yang dikirim"
        else -> when (mic) {
            MicState.Muted -> "Mic mati" to "Ketuk tombol di bawah untuk bicara"
            MicState.Preparing -> "Menyiapkan… tunggu sebentar" to "Kalau langsung bicara, suaramu tetap direkam"
            MicState.Ready -> "Siap — silakan bicara" to "Bicara kapan saja, berhenti sejenak untuk mengirim"
            MicState.Hearing -> "Mendengarkan…" to "Diam sejenak untuk mengirim"
            MicState.Paused -> "JARVIS sedang bicara — tunggu" to "Mic dijeda supaya JARVIS tidak mendengar dirinya sendiri"
            MicState.Error -> "Mic bermasalah" to "Mencoba menyambung lagi…"
        }
    }
    Text(text, color = micColor(mic), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
    Text(sub, color = JarvisColors.Muted, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(bottom = 6.dp))
}

@Composable
private fun ReportCard(r: SpokenReport, onAck: (Long) -> Unit, onRepeat: (Long) -> Unit) {
    val unheard = r.state == SpokenReport.State.Unheard
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(JarvisColors.Surface)
            .border(1.dp, (if (unheard) JarvisColors.Red else JarvisColors.Cyan).copy(alpha = 0.6f), RoundedCornerShape(14.dp))
            .padding(12.dp),
    ) {
        Text(
            when {
                unheard -> "BELUM TERDENGAR"
                r.state == SpokenReport.State.Waiting -> "LAPORAN BARU"
                else -> "LAPORAN · disampaikan ${r.attempt}x"
            },
            color = if (unheard) JarvisColors.Red else JarvisColors.Cyan, fontSize = 10.sp, letterSpacing = 2.sp,
        )
        Text(r.text, color = JarvisColors.Text, fontSize = 14.sp, lineHeight = 20.sp, modifier = Modifier.padding(vertical = 6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Pill("Oke, sudah dengar", JarvisColors.Green) { onAck(r.id) }
            Pill("Ulangi", JarvisColors.Muted) { onRepeat(r.id) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun WorkerCard(w: Worker, onCancel: (Long) -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(JarvisColors.Surface)
            .border(1.dp, JarvisColors.Border, RoundedCornerShape(14.dp)).padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(12.dp), color = JarvisColors.Amber, strokeWidth = 1.5.dp)
            Spacer(Modifier.width(8.dp))
            Text(w.title, color = JarvisColors.Text, fontSize = 14.sp, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(if (w.status == "queued") "antre" else "bekerja", color = JarvisColors.Muted, fontSize = 11.sp)
            Icon(Icons.Filled.Close, "Batalkan", Modifier.padding(start = 6.dp).size(18.dp).clickable { onCancel(w.id) }, tint = JarvisColors.Muted)
        }
        if (w.live.tools.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(top = 8.dp)) { w.live.tools.takeLast(3).forEach { ToolChip(it) } }
        }
        if (w.live.thoughts.isNotBlank()) {
            Text(
                w.live.recentThoughts(160), color = JarvisColors.Muted, fontSize = 11.sp, fontFamily = FontFamily.Monospace,
                maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

@Composable
private fun ToolChip(tool: ToolActivity) {
    val tint = if (tool.running) JarvisColors.Amber else JarvisColors.Muted
    Row(
        Modifier.clip(RoundedCornerShape(20.dp)).background(JarvisColors.SurfaceHigh)
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(20.dp)).padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (tool.running) CircularProgressIndicator(Modifier.size(10.dp), color = tint, strokeWidth = 1.5.dp)
        else Icon(Icons.Filled.CheckCircle, null, Modifier.size(12.dp), tint = JarvisColors.Green)
        Spacer(Modifier.width(5.dp))
        Text(tool.title, color = JarvisColors.Text, fontSize = 11.sp)
        if (tool.label.isNotBlank()) {
            Text(" · ${tool.label}", color = JarvisColors.Muted, fontSize = 11.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 150.dp))
        }
    }
}

@Composable
private fun Pill(text: String, color: Color, onClick: () -> Unit) {
    Text(
        text, color = color, fontSize = 13.sp,
        modifier = Modifier.clip(RoundedCornerShape(20.dp)).border(1.dp, color.copy(alpha = 0.6f), RoundedCornerShape(20.dp))
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
private fun MuteButton(mic: MicState, onToggle: () -> Unit) {
    val muted = mic == MicState.Muted
    val color = micColor(mic)
    Box(
        Modifier.size(84.dp).clip(CircleShape)
            .background(Brush.radialGradient(listOf(color.copy(alpha = if (muted) 0.12f else 0.35f), JarvisColors.Surface)))
            .border(2.dp, color.copy(alpha = 0.9f), CircleShape)
            .clickable(onClick = onToggle),
        contentAlignment = Alignment.Center,
    ) {
        Icon(if (muted) Icons.Filled.MicOff else Icons.Filled.Mic, if (muted) "Nyalakan mic" else "Matikan mic",
            Modifier.size(36.dp), tint = color)
    }
    Text(if (muted) "Ketuk untuk bicara" else "Ketuk untuk mute", color = JarvisColors.Muted, fontSize = 12.sp,
        modifier = Modifier.padding(top = 6.dp))
}
