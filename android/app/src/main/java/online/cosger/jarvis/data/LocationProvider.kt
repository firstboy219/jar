package online.cosger.jarvis.data

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Address
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.SystemClock
import androidx.core.location.LocationManagerCompat
import androidx.core.os.CancellationSignal
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import online.cosger.jarvis.net.DeviceLocation
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.coroutines.resume

/**
 * Current phone position for JARVIS, using the platform LocationManager (no Play services dependency).
 * A fresh fix is requested with a timeout; otherwise the newest last-known fix is used.
 * The address is reverse-geocoded on the phone.
 */
class LocationProvider(context: Context) {
    private val app = context.applicationContext
    private val lm = app.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val executor = Executors.newSingleThreadExecutor()
    @Volatile private var cached: DeviceLocation? = null
    @Volatile private var cachedAtMs = 0L

    fun hasPermission(): Boolean =
        app.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            app.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    /** The last fix this provider got (or the system's last known one), without waiting — for the page's "tandai di sini". */
    fun cachedOrNull(): DeviceLocation? {
        cached?.let { return it }
        if (!hasPermission()) return null
        val fix = lastKnown() ?: return null
        return DeviceLocation(fix.latitude, fix.longitude, if (fix.hasAccuracy()) fix.accuracy.toDouble() else null, 0, null)
    }

    /** Null when permission is missing, location is off, or nothing arrives in time. */
    suspend fun current(timeoutMs: Long = 4_000): DeviceLocation? {
        if (!hasPermission() || !LocationManagerCompat.isLocationEnabled(lm)) return null
        val now = SystemClock.elapsedRealtime()
        cached?.let { if (now - cachedAtMs < CACHE_MS) return it.copy(ageSeconds = it.ageSeconds + (now - cachedAtMs) / 1000) }
        val fix = withTimeoutOrNull(timeoutMs) { freshFix() } ?: lastKnown() ?: return null
        val loc = DeviceLocation(
            lat = fix.latitude, lon = fix.longitude,
            accuracyM = if (fix.hasAccuracy()) fix.accuracy.toDouble() else null,
            ageSeconds = ((now - fix.elapsedRealtimeNanos / 1_000_000) / 1000).coerceAtLeast(0),
            address = withTimeoutOrNull(2_500) { reverseGeocode(fix.latitude, fix.longitude) },
            speedMps = if (fix.hasSpeed()) fix.speed.toDouble() else null,
        )
        cached = loc
        cachedAtMs = now
        return loc
    }

    @SuppressLint("MissingPermission")
    private suspend fun freshFix(): Location? = suspendCancellableCoroutine { cont ->
        val provider = when {
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) && fine() -> LocationManager.GPS_PROVIDER
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            else -> LocationManager.PASSIVE_PROVIDER
        }
        val signal = CancellationSignal()
        cont.invokeOnCancellation { signal.cancel() }
        LocationManagerCompat.getCurrentLocation(lm, provider, signal, executor) { cont.resume(it) }
    }

    @SuppressLint("MissingPermission")
    private fun lastKnown(): Location? = lm.getProviders(true)
        .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
        .maxByOrNull { it.elapsedRealtimeNanos }

    private fun fine() = app.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private suspend fun reverseGeocode(lat: Double, lon: Double): String? = withContext(Dispatchers.IO) {
        if (!Geocoder.isPresent()) return@withContext null
        @Suppress("DEPRECATION") // the listener variant is API 33+; minSdk is 26
        val a = runCatching { Geocoder(app, Locale.forLanguageTag("id-ID")).getFromLocation(lat, lon, 1) }
            .getOrNull()?.firstOrNull() ?: return@withContext null
        formatAddress(a)
    }

    companion object {
        const val CACHE_MS = 60_000L

        private fun formatAddress(a: Address): String? = formatParts(
            street = a.thoroughfare, area = a.subLocality, district = a.locality,
            city = a.subAdminArea, province = a.adminArea,
        )

        /** "Jl. Boulevard, Kelapa Gading, Jakarta Utara, DKI Jakarta" — duplicates and blanks removed. */
        fun formatParts(street: String?, area: String?, district: String?, city: String?, province: String?): String? =
            listOf(street, area, district, city, province)
                .mapNotNull { it?.trim()?.takeIf(String::isNotEmpty) }
                .distinct()
                .joinToString(", ")
                .ifEmpty { null }
    }
}
