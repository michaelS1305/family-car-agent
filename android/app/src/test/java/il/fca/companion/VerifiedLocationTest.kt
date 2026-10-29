package il.fca.companion

import android.app.Application
import il.fca.companion.net.AddressVerification
import il.fca.companion.net.VerifiedLocation
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class VerifiedLocationTest {
    @Test fun optionalCoordinatesNeverBlockTokenBasedConfirmation() = runBlocking {
        for (create in listOf(true, false)) {
            for (coordinates in listOf("{}", "{\"latitude\":null,\"longitude\":null}",
                "{\"latitude\":32}", "{\"latitude\":91,\"longitude\":35}",
                "{\"latitude\":\"32\",\"longitude\":35}")) {
                val result = AddressVerification.resolve("כתובת", create) { _, _ ->
                    JSONObject(coordinates).put("normalized_address", "normalized")
                        .put("display_address", "display").put("resolution_token", "opaque")
                }
                assertNull(result.location)
                assertEquals("opaque", result.token)
                assertEquals("display", result.display)
            }
        }
    }
    @Test fun requiredAddressFieldsRejectMissingNullBlankAndWrongTypes() = runBlocking {
        for (create in listOf(true, false)) for (field in listOf("normalized_address", "display_address", "resolution_token")) {
            for (value in listOf(null, JSONObject.NULL, "", "   ", 123, true)) {
                val body = JSONObject().put("normalized_address", "normalized")
                    .put("display_address", "display").put("resolution_token", "opaque")
                if (value == null) body.remove(field) else body.put(field, value)
                val result = runCatching { AddressVerification.resolve("כתובת", create) { _, _ -> body } }
                assertTrue("$field must reject missing/null/non-text/blank data", result.isFailure)
            }
        }
    }
    @Test fun invalidOrMissingCoordinatesCannotCreateMapLocation() {
        for (json in listOf("{}", "{\"latitude\":32}", "{\"latitude\":91,\"longitude\":35}", "{\"latitude\":32,\"longitude\":181}", "{\"latitude\":\"32\",\"longitude\":35}", "{\"latitude\":true,\"longitude\":35}"))
            assertNull(VerifiedLocation.from(JSONObject(json)))
    }
    @Test fun createAndEditUseOnlyReturnedCandidateCoordinatesAndPreserveToken() = runBlocking {
        for (create in listOf(true, false)) {
            val result = AddressVerification.resolve("המעפיל 1209 דימונה", create) { path, body ->
                assertEquals(if(create) "/api/onboarding/create-family/address" else "/api/family/address/resolve", path)
                assertFalse(body.has("latitude"))
                JSONObject().put("normalized_address", "המעפיל 1209 דימונה").put("display_address", "proposal")
                    .put("resolution_token", "opaque").put("latitude", 31.072207).put("longitude", 35.036462)
            }
            assertEquals("opaque", result.token)
            assertEquals(31.072207, result.location!!.latitude, 0.0)
            assertEquals(35.036462, result.location!!.longitude, 0.0)
        }
    }
}
