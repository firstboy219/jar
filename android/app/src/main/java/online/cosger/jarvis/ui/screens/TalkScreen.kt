package online.cosger.jarvis.ui.screens

import android.Manifest
import android.content.pm.PackageManager
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
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
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
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.SpokenReport
import online.cosger.jarvis.ui.ToolActivity
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.Worker
import online.cosger.jarvis.ui.theme.JarvisColors
import online.cosger.jarvis.voice.MicState

val LOCATION_PERMISSIONS = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)

@Composable
fun TalkScreen(vm: JarvisViewModel) {
    val turn by vm.turn.collectAsStateWithLifecycle()
    val interim by vm.interim.collectAsStateWithLifecycle()
    val level by vm.micLevel.collectAsStateWithLifecycle()
    val mic by vm.mic.collectAsStateWithLifecycle()
    val speaking by vm.speaking.collectAsStateWithLifecycle()
    val board by vm.board.collectAsStateWithLifecycle()
    val connection by vm.connection.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var hasMic by remember {
        mutableStateOf(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    val askPerms = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        hasMic = it[Manifest.permission.RECORD_AUDIO] == true || hasMic
        if (hasMic) vm.toggleMute()
    }
    LaunchedEffect(Unit) { vm.prefetchVoice() } // token ready before the first unmute

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
    )
}

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
) {
    val workers = board.workers.filter { it.active }
    val phase = orbPhase(turn, mic, speaking, workers.isNotEmpty())
    Column(
        Modifier.fillMaxSize().background(JarvisColors.Background).padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Header(connected, workers.size)

        Box(Modifier.fillMaxWidth().height(210.dp), contentAlignment = Alignment.Center) {
            ReadinessRing(mic, Modifier.size(206.dp))
            ThoughtOrb(phase, if (mic == MicState.Hearing) micLevel else 0f, if (workers.isNotEmpty()) 0.5f else 0f, Modifier.size(180.dp))
        }
        ReadinessLabel(mic, connected)

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

            board.openReports.forEach { ReportCard(it, onAck, onRepeat) }
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

@Composable
private fun Header(connected: Boolean, workers: Int) {
    Row(Modifier.fillMaxWidth().padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(if (connected) JarvisColors.Green else JarvisColors.Amber))
        Spacer(Modifier.width(8.dp))
        Text("JARVIS", color = JarvisColors.Text, fontWeight = FontWeight.Bold, letterSpacing = 3.sp)
        Spacer(Modifier.weight(1f))
        Text(
            if (!connected) "Menghubungkan…" else if (workers > 0) "$workers tugas berjalan" else "Terhubung",
            color = JarvisColors.Muted, fontSize = 12.sp,
        )
    }
}

private fun micColor(mic: MicState): Color = when (mic) {
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
private fun ReadinessLabel(mic: MicState, connected: Boolean) {
    val (text, sub) = when {
        !connected && mic != MicState.Muted -> "Menghubungkan ke JARVIS…" to "Ucapanmu ditahan dulu, tidak hilang"
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
