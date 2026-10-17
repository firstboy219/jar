# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class online.cosger.jarvis.** { *** Companion; }
-keepclasseswithmembers class online.cosger.jarvis.** { kotlinx.serialization.KSerializer serializer(...); }
# OkHttp
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
# Tink (EncryptedSharedPreferences) references compile-time-only annotations
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
