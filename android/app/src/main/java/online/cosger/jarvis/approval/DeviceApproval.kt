package online.cosger.jarvis.approval

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import online.cosger.jarvis.ui.console.fragmentActivity
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * Approvals with the phone's own lock (owner 2026-10-31: "Approval dibikin dari apps saja pakai pin/konfirmasi hp"): a signing key made in
 * the Android Keystore that never leaves the phone and can only be used after the phone's PIN / pattern / fingerprint. The server sends a
 * one-time code; the phone signs "jarvis-approve:<code>" with it; the server checks the signature with the public key the owner registered
 * once (with the admin password). Nothing secret is typed or kept in the app.
 */
object DeviceApproval {
    private const val ALIAS = "jarvis-approve"
    private val authenticators = if (Build.VERSION.SDK_INT >= 30)
        BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    else BiometricManager.Authenticators.BIOMETRIC_STRONG

    /** The message signed for one approval. Pure; the server builds the same. */
    fun message(nonce: String): ByteArray = "jarvis-approve:$nonce".toByteArray()

    private fun store(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    /** The public key (X.509 SubjectPublicKeyInfo, base64) — made the first time; null when the phone cannot keep such a key (no screen lock). */
    fun publicKey(context: Context): String? = runCatching {
        if (BiometricManager.from(context).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) return null
        val ks = store()
        if (!ks.containsAlias(ALIAS)) {
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .apply {
                    if (Build.VERSION.SDK_INT >= 30) setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
                    if (Build.VERSION.SDK_INT >= 24) setInvalidatedByBiometricEnrollment(false)
                }
                .build()
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(spec) }.generateKeyPair()
        }
        Base64.encodeToString(ks.getCertificate(ALIAS).publicKey.encoded, Base64.NO_WRAP)
    }.getOrNull()

    /** The phone's lock first (PIN / pattern / fingerprint), then the code signed; `done("")` when cancelled or impossible. */
    fun sign(context: Context, nonce: String, reason: String, done: (String) -> Unit) {
        val activity = context.fragmentActivity() ?: return done("")
        val key = runCatching { store().getKey(ALIAS, null) as? PrivateKey }.getOrNull() ?: return done("")
        val sig = runCatching { Signature.getInstance("SHA256withECDSA").apply { initSign(key) } }.getOrNull() ?: return done("")
        val info = BiometricPrompt.PromptInfo.Builder().setTitle("Setujui di JARVIS").setSubtitle(reason.take(120)).apply {
            if (Build.VERSION.SDK_INT >= 30) setAllowedAuthenticators(authenticators) else setNegativeButtonText("Batal")
        }.build()
        BiometricPrompt(activity, ContextCompat.getMainExecutor(context), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                val s = result.cryptoObject?.signature ?: return done("")
                done(runCatching { s.update(message(nonce)); Base64.encodeToString(s.sign(), Base64.NO_WRAP) }.getOrDefault(""))
            }
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) = done("")
        }).authenticate(info, BiometricPrompt.CryptoObject(sig))
    }

    /** Forget the key (a new one is registered next time). */
    fun reset() { runCatching { store().deleteEntry(ALIAS) } }
}
