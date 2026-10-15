package il.fca.companion.net

import org.json.JSONObject

/** Memory-only confirmation from the existing server geocoder; never persist the draft as an address. */
class ResolvedAddress(val normalized: String, val display: String, val token: String)

object AddressVerification {
    suspend fun resolve(address: String, creatingFamily: Boolean,
                        request: suspend (String, JSONObject) -> JSONObject): ResolvedAddress {
        val path = if (creatingFamily) "/api/onboarding/create-family/address" else "/api/family/address/resolve"
        val result = request(path, JSONObject().put("home_address", address))
        check(result.getString("resolution_token").isNotBlank())
        val normalized = result.getString("normalized_address")
        // Preserve onboarding's existing response validation. The family-update contract omits coordinates.
        if (creatingFamily) { result.getDouble("latitude"); result.getDouble("longitude") }
        return ResolvedAddress(normalized, result.getString("display_address"), result.getString("resolution_token"))
    }
}
