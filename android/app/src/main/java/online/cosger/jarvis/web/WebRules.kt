package online.cosger.jarvis.web

import java.net.URI

/** ADR-087 (batch H): which pages JARVIS may open on the phone — https only, and only the sites the server named for this visit. */
object WebRules {
    fun host(url: String): String? = runCatching { URI(url.trim()).takeIf { it.scheme.equals("https", true) }?.host?.lowercase() }.getOrNull()

    fun allowed(url: String, domains: Collection<String>): Boolean {
        val h = host(url) ?: return false
        return domains.map { it.trim().lowercase().removePrefix("www.") }.filter { it.isNotEmpty() }
            .any { d -> h == d || h.endsWith(".$d") }
    }

    private val FINANCIAL = Regex("""(^|\.)(klikbca|bca\.co\.id|bri\.co\.id|bankmandiri|livin|bni\.co\.id|cimbniaga|permatabank|danamon|btn\.co\.id|""" +
        """jenius|bankjago|blubybcadigital|seabank|ovo\.id|dana\.id|gopay|shopeepay|linkaja|indodax|tokocrypto|pintu\.co\.id|kredivo|akulaku|""" +
        """paypal|wise\.com)""")

    /** Bank, e-wallet, pay-later and crypto sites: a JARVIS web session never opens them (money moves there). */
    fun financial(url: String): Boolean = host(url)?.let { FINANCIAL.containsMatchIn(it) } ?: false

    /** A bot check still on screen (Cloudflare "Just a moment…", an access-restricted page): the read waits, then says so. */
    fun challenged(title: String, text: String): Boolean {
        val t = "$title ${text.take(600)}".lowercase()
        return listOf("just a moment", "performing security verification", "checking your browser", "verify you are human", "access restricted",
            "attention required").any { it in t }
    }
}
