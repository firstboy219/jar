plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("app.cash.paparazzi")
}

// Set by infra/scripts/build-apk.sh: -PversionName=0.1.0 -PversionCode=1
val appVersionName = (findProperty("versionName") as String?) ?: "0.0.0-dev"
val appVersionCode = (findProperty("versionCode") as String?)?.toInt() ?: 1

android {
    namespace = "online.cosger.jarvis"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "online.cosger.jarvis"
        minSdk = 26
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
        buildConfigField("String", "DEFAULT_SERVER", "\"https://vis1.cosger.online\"")
        // Native libs (onnxruntime for the on-phone VAD, MapLibre): 64-bit ARM phones only (the owner's
        // Infinix HOT 11S is arm64); a second ABI would add ~40 MB.
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    signingConfigs {
        create("release") {
            // Keystore lives on the server (infra/data/android), never in git.
            System.getenv("JARVIS_KEYSTORE_FILE")?.let { storeFile = file(it) }
            storePassword = System.getenv("JARVIS_KEYSTORE_PASSWORD")
            keyAlias = "jarvis"
            keyPassword = System.getenv("JARVIS_KEYSTORE_PASSWORD")
            // v1 (JAR) + v2 + v3: some OEM package installers (e.g. Transsion XOS) are stricter than AOSP.
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("io.coil-kt.coil3:coil-compose:3.0.4")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.0.4")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    // v0.7: on-phone voice activity detection (Silero VAD) — only speech is sent to the server
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.30.0")
    // v0.7 "Panggung": music/video player, map with route options, reading screen text for reply drafts
    implementation("androidx.media3:media3-exoplayer:1.5.1")
    implementation("androidx.media3:media3-datasource-okhttp:1.5.1")
    implementation("androidx.media3:media3-ui:1.5.1")
    implementation("androidx.media3:media3-session:1.5.1")
    implementation("org.maplibre.gl:android-sdk:11.13.5")
    // Text recognition through Google Play services: the model is downloaded once by Play, not bundled (−11 MB)
    implementation("com.google.android.gms:play-services-mlkit-text-recognition:19.0.1")
    // Owner console: fingerprint/face before sensitive screens
    implementation("androidx.biometric:biometric:1.1.0")
    // ADR-087 (Kamera ukur): the AR ruler; ARCore is optional — phones without it measure from a photo in the app instead
    implementation("com.google.ar:core:1.51.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
