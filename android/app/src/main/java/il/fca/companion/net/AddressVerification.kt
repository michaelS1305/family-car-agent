package il.fca.companion.net

import org.json.JSONObject

/** Memory-only confirmation from the existing server geocoder; never persist the draft as an address. */
class VerifiedLocation private constructor(val latitude: Double, val longitude: Double) {
    companion object {
        fun from(result: JSONObject): VerifiedLocation? {
            val lat = result.opt("latitude") as? Number ?: return null
            val lng = result.opt("longitude") as? Number ?: return null
            val a = lat.toDouble(); val b = lng.toDouble()
            return if (a.isFinite() && b.isFinite() && a in -90.0..90.0 && b in -180.0..180.0)
                VerifiedLocation(a, b) else null
        }
    }
}
class ResolvedAddress(val normalized: String, val display: String, val token: String,
                      val location: VerifiedLocation? = null)

object AddressVerification {
    suspend fun resolve(address: String, creatingFamily: Boolean,
                        request: suspend (String, JSONObject) -> JSONObject): ResolvedAddress {
        val path = if (creatingFamily) "/api/onboarding/create-family/address" else "/api/family/address/resolve"
        val result = request(path, JSONObject().put("home_address", address))
        fun requiredText(key: String): String =
            (result.opt(key) as? String)?.takeIf { it.isNotBlank() } ?: error("Invalid address response")
        return ResolvedAddress(requiredText("normalized_address"), requiredText("display_address"),
            requiredText("resolution_token"), VerifiedLocation.from(result))
    }
}
