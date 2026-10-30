package online.cosger.jarvis.ui.console

import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import online.cosger.jarvis.ui.theme.JarvisColors

/** Result of loading one console screen's data. */
class Load<T>(val data: T?, val error: String?, val loading: Boolean, val reload: () -> Unit)

/** Run [fetch] now and whenever reload() is called; errors become a message, never a crash. */
@Composable
fun <T> rememberLoad(vararg keys: Any?, fetch: suspend () -> T): Load<T> {
    var data by remember(*keys) { mutableStateOf<T?>(null) }
    var error by remember(*keys) { mutableStateOf<String?>(null) }
    var loading by remember(*keys) { mutableStateOf(true) }
    var tick by remember(*keys) { mutableIntStateOf(0) }
    LaunchedEffect(tick, *keys) {
        loading = true
        runCatching { fetch() }.onSuccess { data = it; error = null }.onFailure { error = it.message ?: it.javaClass.simpleName }
        loading = false
    }
    return Load(data, error, loading) { tick++ }
}

@Composable
fun ConsolePage(title: String, onBack: (() -> Unit)?, onRefresh: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize().background(JarvisColors.Background)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            if (onBack != null) {
                Box(Modifier.size(40.dp).clickable(onClick = onBack), contentAlignment = Alignment.Center) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, "Kembali", tint = JarvisColors.Text)
                }
            } else Spacer(Modifier.width(8.dp))
            Text(title, color = JarvisColors.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            if (onRefresh != null) Box(Modifier.size(40.dp).clickable(onClick = onRefresh), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Refresh, "Muat ulang", tint = JarvisColors.Muted)
            }
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
    }
}

@Composable
fun <T> LoadState(load: Load<T>, content: @Composable (T) -> Unit) {
    when {
        load.data != null -> content(load.data)
        load.loading -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = JarvisColors.Cyan)
        }
        else -> Text(load.error ?: "Gagal memuat", color = JarvisColors.Red, fontSize = 13.sp)
    }
}

@Composable
fun Card(modifier: Modifier = Modifier, border: Color = JarvisColors.Border, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(JarvisColors.Surface)
        .border(1.dp, border, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
        content = content)
}

@Composable
fun Label(text: String, color: Color = JarvisColors.Cyan) = Text(text.uppercase(), color = color, fontSize = 10.sp, letterSpacing = 2.sp)

@Composable
fun Body(text: String, color: Color = JarvisColors.Text, size: Int = 14) = Text(text, color = color, fontSize = size.sp)

@Composable
fun Small(text: String, color: Color = JarvisColors.Muted) = Text(text, color = color, fontSize = 12.sp)

@Composable
fun Action(text: String, color: Color = JarvisColors.Cyan, enabled: Boolean = true, onClick: () -> Unit) {
    Text(text, color = if (enabled) color else JarvisColors.Muted, fontSize = 13.sp,
        modifier = Modifier.clip(RoundedCornerShape(20.dp)).border(1.dp, color.copy(alpha = if (enabled) 0.6f else 0.2f), RoundedCornerShape(20.dp))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 12.dp, vertical = 6.dp))
}

fun Context.fragmentActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> baseContext.fragmentActivity()
    else -> null
}

/**
 * Fingerprint/face (or the phone's PIN) before sensitive console actions: settings, devices, AI
 * composition changes, high-risk approvals. If the phone has no screen lock at all, it cannot protect
 * anything, so the action proceeds.
 */
fun requireOwner(context: Context, reason: String, onOk: () -> Unit) {
    val activity = context.fragmentActivity() ?: return onOk()
    val authenticators = if (Build.VERSION.SDK_INT >= 30)
        BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    else BiometricManager.Authenticators.BIOMETRIC_WEAK
    if (BiometricManager.from(context).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) return onOk()
    val info = BiometricPrompt.PromptInfo.Builder().setTitle("Konfirmasi pemilik").setSubtitle(reason).apply {
        if (Build.VERSION.SDK_INT >= 30) setAllowedAuthenticators(authenticators) else setNegativeButtonText("Batal")
    }.build()
    BiometricPrompt(activity, ContextCompat.getMainExecutor(context), object : BiometricPrompt.AuthenticationCallback() {
        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = onOk()
    }).authenticate(info)
}

/** The kept admin password, released only after a strong biometric or the phone's own credential — never without (unlike requireOwner). */
fun unlockSecret(context: Context, reason: String, secret: String?, done: (String) -> Unit) {
    val activity = context.fragmentActivity()
    val authenticators = if (Build.VERSION.SDK_INT >= 30)
        BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    else BiometricManager.Authenticators.BIOMETRIC_STRONG
    if (secret == null || activity == null || BiometricManager.from(context).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) return done("")
    val info = BiometricPrompt.PromptInfo.Builder().setTitle("Setujui operasi HP").setSubtitle(reason).apply {
        if (Build.VERSION.SDK_INT >= 30) setAllowedAuthenticators(authenticators) else setNegativeButtonText("Ketik password")
    }.build()
    BiometricPrompt(activity, ContextCompat.getMainExecutor(context), object : BiometricPrompt.AuthenticationCallback() {
        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = done(secret)
        override fun onAuthenticationError(errorCode: Int, errString: CharSequence) = done("")
    }).authenticate(info)
}

@Composable
fun rememberOwnerGate(): (String, () -> Unit) -> Unit {
    val context = LocalContext.current
    return { reason, action -> requireOwner(context, reason, action) }
}

