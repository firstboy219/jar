package online.cosger.jarvis

import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import kotlinx.coroutines.launch
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.fillMaxSize
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.console.AppUpdateScreen
import online.cosger.jarvis.ui.console.AuditScreen
import online.cosger.jarvis.ui.console.CompositionScreen
import online.cosger.jarvis.ui.console.DeskChrome
import online.cosger.jarvis.ui.console.NotesScreen
import online.cosger.jarvis.ui.console.JarvisVoiceScreen
import online.cosger.jarvis.ui.console.ConsoleRoute
import online.cosger.jarvis.ui.console.DashboardScreen
import online.cosger.jarvis.ui.console.DevicesScreen
import online.cosger.jarvis.ui.console.BackgroundScreen
import online.cosger.jarvis.ui.console.DocumentsScreen
import online.cosger.jarvis.ui.console.FlowScreen
import online.cosger.jarvis.ui.console.MeetingDetailScreen
import online.cosger.jarvis.ui.console.MeetingsScreen
import online.cosger.jarvis.ui.console.MemoryScreen
import online.cosger.jarvis.ui.console.MoreScreen
import online.cosger.jarvis.ui.console.PlaylistScreen
import online.cosger.jarvis.ui.console.LibraryScreen
import online.cosger.jarvis.ui.console.ModelStatsScreen
import online.cosger.jarvis.ui.console.NotificationsScreen
import online.cosger.jarvis.ui.console.PasswordsScreen
import online.cosger.jarvis.ui.console.PhoneSetupScreen
import online.cosger.jarvis.ui.console.SelfScreen
import online.cosger.jarvis.ui.console.ServerSettingsScreen
import online.cosger.jarvis.ui.console.StudioScreen
import online.cosger.jarvis.ui.console.TasksScreen
import online.cosger.jarvis.ui.console.VoiceprintScreen
import online.cosger.jarvis.ui.screens.LOCATION_PERMISSIONS
import online.cosger.jarvis.ui.screens.SettingsScreen
import online.cosger.jarvis.ui.theme.JarvisColors
import online.cosger.jarvis.ui.theme.JarvisTheme

// FragmentActivity (not ComponentActivity): the owner console asks for fingerprint/face via BiometricPrompt.
class MainActivity : FragmentActivity() {
    override fun onResume() {
        super.onResume()
        // Every time JARVIS is opened: is there a newer version? (dialog: Update sekarang / Tunda)
        (application as JarvisApp).engine.checkUpdateSoon()
        (application as JarvisApp).engine.refreshPhoneApprovals()   // ADR-077: an approval asked while the app was closed
        (application as JarvisApp).engine.refreshChoices()           // ADR-079: a pick asked while the app was closed
        (application as JarvisApp).engine.syncAlarm()                // ADR-087: the morning alarm set on the web reaches this phone
        if ((application as JarvisApp).settings.state.value.isConfigured) StandbyService.startIfWanted(this)   // ADR-086: stay connected in the background
    }

    @OptIn(ExperimentalLayoutApi::class)   // consumeWindowInsets (stable in newer Compose; harmless when it already is)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            JarvisTheme {
                val vm: JarvisViewModel = viewModel()
                val settings by vm.settings.collectAsStateWithLifecycle()
                val notice by vm.notice.collectAsStateWithLifecycle()
                val nav = rememberNavController()
                val snackbar = remember { SnackbarHostState() }
                LaunchedEffect(notice) {
                    notice?.let { snackbar.showSnackbar(it); vm.dismissNotice() }
                }
                val current by nav.currentBackStackEntryAsState()
                val update by vm.updater.offer.collectAsStateWithLifecycle()
                val downloading by vm.updater.downloading.collectAsStateWithLifecycle()
                val updateScope = androidx.compose.runtime.rememberCoroutineScope()
                update?.let { offer ->
                    androidx.compose.material3.AlertDialog(
                        onDismissRequest = {},
                        title = { Text("JARVIS ${offer.version} tersedia") },
                        text = {
                            Text((offer.notes.ifBlank { "Versi baru JARVIS." }) +
                                "\n\nUkuran ${"%.1f".format(offer.sizeMb)} MB. Versi terpasang: ${BuildConfig.VERSION_NAME}.")
                        },
                        confirmButton = {
                            androidx.compose.material3.TextButton(enabled = !downloading, onClick = {
                                updateScope.launch {
                                    when (val err = vm.updater.install()) {
                                        null -> Unit
                                        "PERMISSION" -> {
                                            startActivity(android.content.Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                                android.net.Uri.parse("package:$packageName")))
                                            vm.notify("Izinkan JARVIS memasang aplikasi, lalu tekan Update sekarang lagi.")
                                        }
                                        else -> vm.notify(err)
                                    }
                                }
                            }) { Text(if (downloading) "Mengunduh…" else "Update sekarang") }
                        },
                        dismissButton = {
                            androidx.compose.material3.TextButton(enabled = !downloading, onClick = { vm.updater.postpone(24) }) {
                                Text("Tunda")
                            }
                        },
                    )
                }
                // ADR-077: JARVIS asks to operate an app on this phone — the admin password approves it
                val phoneAsks by vm.phoneApprovals.collectAsStateWithLifecycle()
                var later by remember { androidx.compose.runtime.mutableStateOf(setOf<Long>()) }
                phoneAsks.firstOrNull { it.id !in later }?.let { a ->
                    online.cosger.jarvis.ui.console.PhoneApprovalDialog(vm, a) { later = later + a.id }
                }
                // ADR-079: a project asks the owner to pick (which train): the popup the notification opens
                val picks by vm.choices.collectAsStateWithLifecycle()
                var laterPick by remember { androidx.compose.runtime.mutableStateOf(setOf<Long>()) }
                if (phoneAsks.none { it.id !in later }) {   // the admin-password dialog goes first when both are waiting
                    picks.firstOrNull { it.id !in laterPick }?.let { c ->
                        online.cosger.jarvis.ui.console.OwnerChoiceDialog(vm, c) { laterPick = laterPick + c.id }
                    }
                }
                // Location sharing is on by default: ask once at start; denying turns the setting off.
                val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { g ->
                    if (g.values.none { it }) vm.setShareLocation(false)
                }
                LaunchedEffect(settings.isConfigured) {
                    if (settings.isConfigured && vm.locationPermissionMissing()) askLocation.launch(LOCATION_PERMISSIONS)
                }

                val areaFull by DeskChrome.fullscreen.collectAsState()   // an area open full screen on the desk (ADR-062)
                // the native talk sheet over the app (ADR-087): opened by the page's mic button, a stage panel or an unheard report
                var talkOpen by remember { androidx.compose.runtime.mutableStateOf(false) }
                val stage by vm.stage.collectAsStateWithLifecycle()
                val board by vm.board.collectAsStateWithLifecycle()
                val onApp = current?.destination?.route == "app"
                LaunchedEffect(stage.panel?.id) { if (onApp && stage.panel != null) talkOpen = true }
                val unheard = board.reports.count { it.state == online.cosger.jarvis.ui.SpokenReport.State.Unheard }
                LaunchedEffect(unheard) { if (onApp && unheard > 0) talkOpen = true }
                // Bimbing layar (ADR-087): the page asks for the screen to be shared; Android asks the owner once per session
                val askShare = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
                    if (r.resultCode == android.app.Activity.RESULT_OK && r.data != null) {
                        online.cosger.jarvis.screen.ScreenShareService.start(this@MainActivity, r.resultCode, r.data!!)
                    }
                }
                val hostActions = remember(nav) {
                    object : online.cosger.jarvis.ui.console.AppHostActions {
                        override fun talk() { talkOpen = true }
                        override fun open(what: String) {
                            when {
                                what.startsWith("console:") -> ConsoleRoute.entries.firstOrNull { it.path == what.removePrefix("console:") }
                                    ?.let { nav.navigate("console/${it.path}") }
                                what == "desk" -> nav.navigate("app") { popUpTo("app") { inclusive = true } }   // the infinite canvas is gone
                                what in setOf("notes", "tasks", "meetings") -> nav.navigate(what)
                                what == "talk" -> talkOpen = true
                                what == "guide" -> if (!(application as JarvisApp).engine.screen.active.value) {
                                    askShare.launch(getSystemService(android.media.projection.MediaProjectionManager::class.java).createScreenCaptureIntent())
                                }
                                what == "measure" -> startActivity(android.content.Intent(this@MainActivity, online.cosger.jarvis.measure.MeasureActivity::class.java))
                                else -> vm.notify("Fitur ini hadir di versi aplikasi berikutnya.")
                            }
                        }
                    }
                }
                Scaffold(
                    containerColor = JarvisColors.Background,
                    snackbarHost = { SnackbarHost(snackbar) },
                ) { padding ->
                    NavHost(
                        nav,
                        startDestination = if (settings.isConfigured) "app" else "console/app",
                        // edge-to-edge: Android no longer shrinks the window for the keyboard, so every tab makes room for it itself — the desk's
                        // chat box and the notes editor stay above the keyboard instead of under it
                        modifier = Modifier.padding(padding).consumeWindowInsets(padding).imePadding(),
                    ) {
                        val back: () -> Unit = { nav.popBackStack() }
                        // the app v2 (ADR-087): the server's /app/ page is the main screen; the native screens below open from it
                        composable("app") { online.cosger.jarvis.ui.console.AppHostScreen(vm, hostActions) }
                        composable("notes") { NotesScreen(vm, back) }
                        composable("tasks") { TasksScreen(vm, back) }
                        composable("meetings") { MeetingsScreen(vm, back) { id -> nav.navigate("meeting/$id") } }
                        composable("meeting/{id}") { e -> MeetingDetailScreen(vm, e.arguments?.getString("id").orEmpty(), back) }
                        composable("more") { MoreScreen { r -> nav.navigate("console/${r.path}") } }
                        ConsoleRoute.entries.forEach { r ->
                            composable("console/${r.path}") {
                                when (r) {
                                    ConsoleRoute.Dashboard -> DashboardScreen(vm, back)
                                    ConsoleRoute.Memory -> MemoryScreen(vm, back)
                                    ConsoleRoute.Composition -> CompositionScreen(vm, back)
                                    ConsoleRoute.JarvisVoice -> JarvisVoiceScreen(vm, back)
                                    ConsoleRoute.Studio -> StudioScreen(vm, back)
                                    ConsoleRoute.Self -> SelfScreen(vm, back)
                                    ConsoleRoute.Flow -> FlowScreen(vm, back)
                                    ConsoleRoute.Background -> BackgroundScreen(vm, back)
                                    ConsoleRoute.Playlist -> PlaylistScreen(vm, back)
                                    ConsoleRoute.Library -> LibraryScreen(vm, back)
                                    ConsoleRoute.ModelStatsRoute -> ModelStatsScreen(vm, back)
                                    ConsoleRoute.Documents -> DocumentsScreen(vm, back)
                                    ConsoleRoute.Notifications -> NotificationsScreen(vm, back)
                                    ConsoleRoute.Devices -> DevicesScreen(vm, back)
                                    ConsoleRoute.Update -> AppUpdateScreen(vm, back)
                                    ConsoleRoute.Audit -> AuditScreen(vm, back)
                                    ConsoleRoute.Server -> ServerSettingsScreen(vm, back)
                                    ConsoleRoute.Voice -> VoiceprintScreen(vm, back)
                                    ConsoleRoute.Phone -> PhoneSetupScreen(back)
                                    ConsoleRoute.Passwords -> PasswordsScreen(vm, back)
                                    ConsoleRoute.App -> SettingsScreen(vm, onSaved = { nav.navigate("app") { launchSingleTop = true; popUpTo(0) } })
                                }
                            }
                        }
                    }
                    if (talkOpen && onApp && !areaFull) androidx.compose.foundation.layout.Box(Modifier.fillMaxSize()) {
                        online.cosger.jarvis.ui.console.DeskTalkSheet(vm, { talkOpen = false },
                            { nav.navigate("console/${ConsoleRoute.Dashboard.path}") }, { nav.navigate("console/${ConsoleRoute.Background.path}") },
                            Modifier.align(androidx.compose.ui.Alignment.BottomCenter))
                    }
                }
            }
        }
        routeFromIntent(intent)
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        routeFromIntent(intent)
    }

    private fun routeFromIntent(intent: android.content.Intent?) {
        online.cosger.jarvis.ui.console.AppRoute.open(intent?.getStringExtra(EXTRA_ROUTE))
    }

    companion object {
        const val EXTRA_ROUTE = "open_route"
    }
}
