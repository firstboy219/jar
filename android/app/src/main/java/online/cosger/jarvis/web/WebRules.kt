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

    /** A bot check still on screen (Cloudflare "Just a moment…", an access-restricted page): the read waits, then says so. */
    fun challenged(title: String, text: String): Boolean {
        val t = "$title ${text.take(600)}".lowercase()
        return listOf("just a moment", "performing security verification", "checking your browser", "verify you are human", "access restricted",
            "attention required").any { it in t }
    }
}
