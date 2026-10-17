package online.cosger.jarvis.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Mic
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.ui.ContextCard
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.ToolActivity
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.theme.JarvisColors

@Composable
fun TalkScreen(vm: JarvisViewModel) {
    val turn by vm.turn.collectAsStateWithLifecycle()
    val interim by vm.interim.collectAsStateWithLifecycle()
    val level by vm.micLevel.collectAsStateWithLifecycle()
    val connection by vm.connection.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var hasMic by remember {
        mutableStateOf(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { hasMic = it }

    TalkContent(
        turn = turn,
        interim = interim,
        micLevel = level,
        connected = connection == Connection.Connected,
        onPress = { if (hasMic) vm.onTalkPressed() else askMic.launch(Manifest.permission.RECORD_AUDIO) },
        onRelease = { if (hasMic) vm.onTalkReleased() },
    )
}

/** Stateless so it can be previewed/screenshotted with any TurnState. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TalkContent(
    turn: TurnState,
    interim: String,
    micLevel: Float,
    connected: Boolean,
    onPress: () -> Unit,
    onRelease: () -> Unit,
) {
    // Bursts of activity when new thought text arrives make the orb flare.
    var lastLen by remember { mutableStateOf(0) }
    var burst by remember { mutableStateOf(0f) }
    LaunchedEffect(turn.thoughts.length) {
        burst = if (turn.thoughts.length > lastLen) 1f else 0f
        lastLen = turn.thoughts.length
    }
    val activity by animateFloatAsState(burst, label = "burst")
    LaunchedEffect(burst) { if (burst > 0f) { kotlinx.coroutines.delay(250); burst = 0f } }

    Column(
        Modifier.fillMaxSize().background(JarvisColors.Background).padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        PhaseHeader(turn.phase, connected)

        Box(Modifier.fillMaxWidth().height(250.dp), contentAlignment = Alignment.Center) {
            ThoughtOrb(turn.phase, micLevel, activity, Modifier.size(250.dp))
        }

        // What the owner said / is saying
        val heard = if (turn.phase == Phase.Listening) interim else turn.userText
        AnimatedVisibility(heard.isNotBlank(), enter = fadeIn(), exit = fadeOut()) {
            Text(
                "“$heard”", color = JarvisColors.Text, fontSize = 16.sp, maxLines = 3,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        Column(Modifier.weight(1f).fillMaxWidth().animateContentSize()) {
            if (turn.tools.isNotEmpty()) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.padding(bottom = 8.dp),
                ) { turn.tools.forEach { ToolChip(it) } }
            }
            // Once the answer streams, context collapses to one line so the answer gets the room.
            val answering = turn.phase == Phase.Answering || turn.phase == Phase.Done
            if (turn.context.isNotEmpty()) ContextStrip(turn.context, compact = answering)
            ThoughtStream(turn, Modifier.weight(1f))
        }

        TalkButton(turn.phase, connected, onPress, onRelease)
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun PhaseHeader(phase: Phase, connected: Boolean) {
    val label = when {
        !connected -> "Menghubungkan ke JARVIS…"
        phase == Phase.Listening -> "Mendengarkan…"
        phase == Phase.Thinking -> "Sedang berpikir"
        phase == Phase.Acting -> "Sedang bertindak"
        phase == Phase.Answering -> "Menjawab"
        phase == Phase.Failed -> "Ada masalah"
        else -> "Tahan tombol untuk bicara"
    }
    Row(Modifier.fillMaxWidth().padding(top = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(8.dp).clip(CircleShape)
                .background(if (connected) JarvisColors.Green else JarvisColors.Amber),
        )
        Spacer(Modifier.width(8.dp))
        Text("JARVIS", color = JarvisColors.Text, fontWeight = FontWeight.Bold, letterSpacing = 3.sp)
        Spacer(Modifier.weight(1f))
        Text(label, color = JarvisColors.forPhase(phase), fontSize = 13.sp)
    }
}

@Composable
private fun ToolChip(tool: ToolActivity) {
    val tint = if (tool.running) JarvisColors.Amber else JarvisColors.Muted
    Row(
        Modifier.clip(RoundedCornerShape(20.dp)).background(JarvisColors.Surface)
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(20.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (tool.running) {
            CircularProgressIndicator(Modifier.size(12.dp), color = tint, strokeWidth = 1.5.dp)
        } else {
            Icon(Icons.Filled.CheckCircle, null, Modifier.size(14.dp), tint = JarvisColors.Green)
        }
        Spacer(Modifier.width(6.dp))
        Text(tool.title, color = JarvisColors.Text, fontSize = 12.sp)
        if (tool.label.isNotBlank()) {
            Text(
                " · ${tool.label}", color = JarvisColors.Muted, fontSize = 12.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 160.dp),
            )
        }
    }
}

@Composable
private fun ContextStrip(cards: List<ContextCard>, compact: Boolean) {
    val card = cards.last()
    Text(
        if (compact) "Konteks: ${card.items.size} memori · ${card.query}" else "Sedang mengingat: ${card.query}",
        color = JarvisColors.Cyan, fontSize = 12.sp,
        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(bottom = 6.dp),
    )
    if (compact) return
    if (card.items.isEmpty()) {
        Text("— belum ada memori yang cocok", color = JarvisColors.Muted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
        return
    }
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(bottom = 8.dp),
    ) {
        items(card.items) { item ->
            Column(
                Modifier.width(210.dp).heightIn(min = 72.dp).clip(RoundedCornerShape(12.dp))
                    .background(JarvisColors.Surface).border(1.dp, JarvisColors.Border, RoundedCornerShape(12.dp))
                    .padding(10.dp),
            ) {
                Row {
                    Text(item.category, color = JarvisColors.Cyan, fontSize = 11.sp)
                    Spacer(Modifier.weight(1f))
                    Text("${(item.score * 100).toInt()}%", color = JarvisColors.Muted, fontSize = 11.sp)
                }
                Text(item.text, color = JarvisColors.Text, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Live reasoning ("isi pikiran"), auto-scrolling, faded at the top; the answer streams below it. */
@Composable
private fun ThoughtStream(turn: TurnState, modifier: Modifier) {
    val scroll = rememberScrollState()
    LaunchedEffect(turn.thoughts.length, turn.answer.length) { scroll.animateScrollTo(scroll.maxValue) }
    Column(
        modifier.fillMaxWidth()
            .graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)
            .drawWithContent {
                drawContent()
                drawRect(
                    Brush.verticalGradient(0f to Color.Transparent, 0.25f to Color.Black),
                    blendMode = BlendMode.DstIn,
                )
            }
            .verticalScroll(scroll),
    ) {
        Spacer(Modifier.height(40.dp))
        if (turn.thoughts.isNotBlank()) {
            Text("ISI PIKIRAN", color = JarvisColors.Violet, fontSize = 10.sp, letterSpacing = 2.sp)
            val done = turn.phase == Phase.Answering || turn.phase == Phase.Done
            Text(
                turn.recentThoughts(if (done) 220 else 600), color = JarvisColors.Muted, fontSize = 12.sp,
                fontFamily = FontFamily.Monospace, lineHeight = 17.sp,
                modifier = Modifier.alpha(if (done) 0.55f else 1f),
            )
            Spacer(Modifier.height(10.dp))
        }
        if (turn.answer.isNotBlank()) {
            Text(turn.answer, color = JarvisColors.Text, fontSize = 15.sp, lineHeight = 21.sp)
        }
        turn.error?.let { Text(it, color = JarvisColors.Red, fontSize = 13.sp) }
    }
}

@Composable
private fun TalkButton(phase: Phase, enabled: Boolean, onPress: () -> Unit, onRelease: () -> Unit) {
    val listening = phase == Phase.Listening
    val scale by animateFloatAsState(if (listening) 1.12f else 1f, label = "pttScale")
    val color = if (listening) JarvisColors.Green else JarvisColors.Cyan
    Box(
        Modifier.size(96.dp).scale(scale).clip(CircleShape)
            .background(Brush.radialGradient(listOf(color.copy(alpha = 0.35f), JarvisColors.Surface)))
            .border(2.dp, color.copy(alpha = if (enabled) 0.9f else 0.3f), CircleShape)
            .pointerInput(enabled) {
                if (!enabled) return@pointerInput
                detectTapGestures(onPress = {
                    onPress()
                    tryAwaitRelease()
                    onRelease()
                })
            },
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Filled.Mic, "Tahan untuk bicara", Modifier.size(40.dp), tint = color.copy(alpha = if (enabled) 1f else 0.4f))
    }
    Text(
        if (listening) "Lepas untuk mengirim" else "Tahan untuk bicara",
        color = JarvisColors.Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp),
    )
}
