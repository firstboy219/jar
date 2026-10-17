package online.cosger.jarvis

import android.app.Application
import online.cosger.jarvis.data.LocationProvider
import online.cosger.jarvis.data.SecureSettings

class JarvisApp : Application() {
    lateinit var settings: SecureSettings
        private set
    lateinit var location: LocationProvider
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SecureSettings(this)
        location = LocationProvider(this)
    }
}
