package online.cosger.jarvis.ui.stage

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import online.cosger.jarvis.ui.theme.JarvisColors
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.geojson.Feature
import org.maplibre.geojson.FeatureCollection
import org.maplibre.geojson.LineString
import org.maplibre.geojson.Point

/** OpenStreetMap vector tiles, free, no key (OpenFreeMap). */
private const val STYLE = "https://tiles.openfreemap.org/styles/liberty"

/** A route's [lat, lon] pairs from the payload. Pure; unit-tested. */
fun routePoints(route: kotlinx.serialization.json.JsonObject): List<Pair<Double, Double>> =
    (route["polyline"] as? JsonArray)?.mapNotNull { p ->
        val a = p as? JsonArray ?: return@mapNotNull null
        val lat = a.getOrNull(0)?.jsonPrimitive?.doubleOrNull
        val lon = a.getOrNull(1)?.jsonPrimitive?.doubleOrNull
        if (lat != null && lon != null) lat to lon else null
    } ?: emptyList()

/**
 * Distance talk → a map with the route options JARVIS found: the selected route bright, the others dim;
 * chips (or saying "pilih rute kedua") switch between them. Says so when times are without traffic data.
 */
@Composable
fun MapPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val routes = panel.list("routes")
    val selected = panel.int("selected") ?: 0
    val mapRef = remember { mutableStateOf<MapLibreMap?>(null) }
    val mapView = remember {
        MapLibre.getInstance(context)
        MapView(context).apply { onCreate(null) }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        mapView.onStart(); mapView.onResume()
        onDispose {
            lifecycle.removeObserver(observer)
            mapView.onPause(); mapView.onStop(); mapView.onDestroy()
        }
    }
    LaunchedEffect(panel.id) {
        mapView.getMapAsync { map ->
            map.uiSettings.isRotateGesturesEnabled = false
            map.setStyle(Style.Builder().fromUri(STYLE)) { style ->
                routes.forEachIndexed { i, r ->
                    val line = LineString.fromLngLats(routePoints(r).map { Point.fromLngLat(it.second, it.first) })
                    style.addSource(GeoJsonSource("route-$i", Feature.fromGeometry(line)))
                    style.addLayer(LineLayer("route-$i", "route-$i").withProperties(
                        PropertyFactory.lineColor(JarvisColors.Muted.toArgb()), PropertyFactory.lineWidth(4f),
                        PropertyFactory.lineOpacity(0.6f)))
                }
                val markers = panel.list("markers").mapNotNull { m ->
                    val lat = m.d("lat"); val lon = m.d("lon")
                    if (lat != null && lon != null) Feature.fromGeometry(Point.fromLngLat(lon, lat)) else null
                }
                style.addSource(GeoJsonSource("markers", FeatureCollection.fromFeatures(markers)))
                style.addLayer(CircleLayer("markers", "markers").withProperties(
                    PropertyFactory.circleColor(JarvisColors.Amber.toArgb()), PropertyFactory.circleRadius(7f),
                    PropertyFactory.circleStrokeColor(JarvisColors.Background.toArgb()), PropertyFactory.circleStrokeWidth(2f)))
                mapRef.value = map
                highlight(map, routes.size, selected)
                val all = routes.flatMap(::routePoints).ifEmpty {
                    panel.list("markers").mapNotNull { m -> m.d("lat")?.let { lat -> m.d("lon")?.let { lat to it } } }
                }
                if (all.size >= 2) {
                    val bounds = LatLngBounds.Builder().apply { all.forEach { include(LatLng(it.first, it.second)) } }.build()
                    map.moveCamera(CameraUpdateFactory.newLatLngBounds(bounds, 60))
                } else all.firstOrNull()?.let { map.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(it.first, it.second), 14.0)) }
            }
        }
    }
    LaunchedEffect(selected) { mapRef.value?.let { highlight(it, routes.size, selected) } }

    Column(Modifier.fillMaxSize()) {
        AndroidView({ mapView }, Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(12.dp)))
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            routes.forEachIndexed { i, r ->
                val on = i == selected
                Text(r.s("label"), fontSize = 12.sp, color = if (on) JarvisColors.Background else JarvisColors.Text,
                    modifier = Modifier.clip(RoundedCornerShape(16.dp))
                        .background(if (on) JarvisColors.Cyan else JarvisColors.SurfaceHigh)
                        .border(1.dp, JarvisColors.Cyan.copy(alpha = 0.6f), RoundedCornerShape(16.dp))
                        .clickable { actions.event("route_selected", mapOf("index" to i)) }
                        .padding(horizontal = 10.dp, vertical = 6.dp))
            }
        }
        val note = panel.str("traffic_note")
        Text((if (note.isNotEmpty()) "$note · " else "") + "sumber: ${panel.str("source")}",
            color = JarvisColors.Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
    }
}

private fun highlight(map: MapLibreMap, count: Int, selected: Int) {
    val style = map.style ?: return
    for (i in 0 until count) {
        (style.getLayer("route-$i") as? LineLayer)?.setProperties(
            PropertyFactory.lineColor((if (i == selected) JarvisColors.Cyan else JarvisColors.Muted).toArgb()),
            PropertyFactory.lineWidth(if (i == selected) 6f else 3.5f),
            PropertyFactory.lineOpacity(if (i == selected) 0.95f else 0.45f))
    }
    (style.getLayer("route-$selected"))?.let { layer -> style.removeLayer(layer); style.addLayerBelow(layer, "markers") }
}
