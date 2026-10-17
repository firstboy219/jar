package online.cosger.jarvis

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
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
import online.cosger.jarvis.ui.screens.ChatScreen
import online.cosger.jarvis.ui.screens.SettingsScreen
import online.cosger.jarvis.ui.screens.TalkScreen
import online.cosger.jarvis.ui.theme.JarvisColors
import online.cosger.jarvis.ui.theme.JarvisTheme

private enum class Tab(val route: String, val label: String, val icon: ImageVector) {
    Talk("talk", "Bicara", Icons.Filled.GraphicEq),
    Chat("chat", "Chat", Icons.AutoMirrored.Filled.Chat),
    Settings("settings", "Pengaturan", Icons.Filled.Settings),
}

class MainActivity : ComponentActivity() {
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

                Scaffold(
                    containerColor = JarvisColors.Background,
                    snackbarHost = { SnackbarHost(snackbar) },
                    bottomBar = {
                        NavigationBar(containerColor = JarvisColors.Surface) {
                            Tab.entries.forEach { tab ->
                                NavigationBarItem(
                                    selected = current?.destination?.route == tab.route,
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
                        startDestination = if (settings.isConfigured) Tab.Talk.route else Tab.Settings.route,
                        modifier = Modifier.padding(padding),
                    ) {
                        composable(Tab.Talk.route) { TalkScreen(vm) }
                        composable(Tab.Chat.route) { ChatScreen(vm) }
                        composable(Tab.Settings.route) {
                            SettingsScreen(vm, onSaved = { nav.navigate(Tab.Talk.route) { launchSingleTop = true } })
                        }
                    }
                }
            }
        }
    }
}
