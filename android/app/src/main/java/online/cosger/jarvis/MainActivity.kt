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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.automirrored.filled.FactCheck
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Public
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.console.AppUpdateScreen
import online.cosger.jarvis.ui.console.AuditScreen
import online.cosger.jarvis.ui.console.CompositionScreen
import online.cosger.jarvis.ui.console.DeskChrome
import online.cosger.jarvis.ui.console.GalaxyScreen
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

private enum class Tab(val route: String, val label: String, val icon: ImageVector) {
    Desk("desk", "Meja", Icons.Filled.Public),
    Notes("notes", "Catatan", Icons.Filled.EditNote),   // ADR-060: notes & to-dos; the conversation is on the desk
    Tasks("tasks", "Tugas", Icons.AutoMirrored.Filled.FactCheck),
    Meetings("meetings", "Rapat", Icons.Filled.Groups),
    More("more", "Lainnya", Icons.Filled.Apps),
}

// FragmentActivity (not ComponentActivity): the owner console asks for fingerprint/face via BiometricPrompt.
class MainActivity : FragmentActivity() {
    override fun onResume() {
        super.onResume()
        // Every time JARVIS is opened: is there a newer version? (dialog: Update sekarang / Tunda)
        (application as JarvisApp).engine.checkUpdateSoon()
        (application as JarvisApp).engine.refreshPhoneApprovals()   // ADR-077: an approval asked while the app was closed
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
                // Location sharing is on by default: ask once at start; denying turns the setting off.
                val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { g ->
                    if (g.values.none { it }) vm.setShareLocation(false)
                }
                LaunchedEffect(settings.isConfigured) {
                    if (settings.isConfigured && vm.locationPermissionMissing()) askLocation.launch(LOCATION_PERMISSIONS)
                }

                val areaFull by DeskChrome.fullscreen.collectAsState()   // an area open full screen on the desk (ADR-062)
                Scaffold(
                    containerColor = JarvisColors.Background,
                    snackbarHost = { SnackbarHost(snackbar) },
                    bottomBar = {
                        if (!areaFull) NavigationBar(containerColor = JarvisColors.Surface) {
                            Tab.entries.forEach { tab ->
                                NavigationBarItem(
                                    selected = current?.destination?.route == tab.route ||
                                        (tab == Tab.More && current?.destination?.route?.startsWith("console/") == true) ||
                                        (tab == Tab.Meetings && current?.destination?.route?.startsWith("meeting/") == true),
                                    onClick = {
                                        nav.navigate(tab.route) {
                                            popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                            launchSingleTop = true
                                            restoreState = true
                                        }
                                    },
                                    icon = { Icon(tab.icon, tab.label) },
                                    label = { Text(tab.label) },
                                    colors = NavigationBarItemDefaults.colors(indicatorColor = JarvisColors.SurfaceHigh),
                                )
                            }
                        }
                    },
                ) { padding ->
                    NavHost(
                        nav,
                        startDestination = if (settings.isConfigured) Tab.Desk.route else "console/app",
                        // edge-to-edge: Android no longer shrinks the window for the keyboard, so every tab makes room for it itself — the desk's
                        // chat box and the notes editor stay above the keyboard instead of under it
                        modifier = Modifier.padding(padding).consumeWindowInsets(padding).imePadding(),
                    ) {
                        val back: () -> Unit = { nav.popBackStack() }
                        composable(Tab.Desk.route) {
                            GalaxyScreen(vm, back, asTab = true,
                                onOpenServer = { nav.navigate("console/${ConsoleRoute.Dashboard.path}") },
                                onOpenBackground = { nav.navigate("console/${ConsoleRoute.Background.path}") })
                        }
                        composable(Tab.Notes.route) { NotesScreen(vm, back) }
                        composable(Tab.Tasks.route) { TasksScreen(vm, null) }
                        composable(Tab.Meetings.route) { MeetingsScreen(vm, null) { id -> nav.navigate("meeting/$id") } }
                        composable("meeting/{id}") { e -> MeetingDetailScreen(vm, e.arguments?.getString("id").orEmpty(), back) }
                        composable(Tab.More.route) { MoreScreen { r -> nav.navigate("console/${r.path}") } }
                        ConsoleRoute.entries.forEach { r ->
                            composable("console/${r.path}") {
                                when (r) {
                                    ConsoleRoute.Dashboard -> DashboardScreen(vm, back)
                                    ConsoleRoute.Memory -> MemoryScreen(vm, back)
                                    ConsoleRoute.Composition -> CompositionScreen(vm, back)
                                    ConsoleRoute.JarvisVoice -> JarvisVoiceScreen(vm, back)
                                    ConsoleRoute.Galaxy -> GalaxyScreen(vm, back)
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
                                    ConsoleRoute.App -> SettingsScreen(vm, onSaved = { nav.navigate(Tab.Desk.route) { launchSingleTop = true } })
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
