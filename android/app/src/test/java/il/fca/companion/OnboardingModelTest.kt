package il.fca.companion

import android.app.Application
import il.fca.companion.net.OnboardingFailure
import il.fca.companion.ui.*
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class OnboardingModelTest {
    @Test fun joinConfirmationWithoutUsableCoordinatesStillRequiresExplicitConfirmation() = runBlocking {
        for (coordinates in listOf("{}", "{\"latitude\":null,\"longitude\":null}",
            "{\"latitude\":\"invalid\",\"longitude\":35}")) {
            val gateway = Gateway().apply { response = { JSONObject(coordinates)
                .put("step", "address_confirmed").put("resolved_address", "כתובת מאומתת") } }
            val model = OnboardingModel(gateway)
            model.authenticated(LoginRoute.JOIN_FAMILY)
            assertEquals(3, model.step)
            assertNull(model.addressLocation)
            assertNull(model.error)
            assertEquals("כתובת מאומתת", model.resolvedAddress)
            assertFalse(gateway.activated)
            assertEquals(listOf("/api/onboarding/join-family/start"), gateway.calls.map { it.first })
            gateway.response = { JSONObject().put("step", "family_code") }
            model.next()
            assertEquals(4, model.step)
            assertTrue(gateway.calls.last().third!!.getBoolean("confirmed"))
        }
    }
    @Test fun cancelledAddressRequestDoesNotBecomeUserErrorAndCanRetry() = runBlocking {
        val gateway = Gateway()
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.CREATE_FAMILY)
        model.familyName = "לוי"; model.next(); model.address = "כתובת לבדיקה"
        gateway.response = { throw kotlinx.coroutines.CancellationException("cancelled") }
        val result = runCatching { model.next() }
        assertTrue(result.exceptionOrNull() is kotlinx.coroutines.CancellationException)
        assertFalse(model.busy)
        assertNull(model.error)
        assertEquals(2, model.step)
        gateway.response = { JSONObject().put("normalized_address", "כתובת").put("display_address", "כתובת")
            .put("resolution_token", "opaque") }
        model.next()
        assertEquals(3, model.step)
    }
    @Test fun authenticatedNameUsesExistingMeAndLogoutReusesGatewayCleanup() = runBlocking {
        val gateway = Gateway().apply { response = { JSONObject().put("family_id", 1).put("name", "דנה לוי") } }
        val model = OnboardingModel(gateway)
        model.bootstrap { true }
        assertEquals("דנה לוי", model.authenticatedName)
        assertEquals(1L, model.authenticatedFamilyId)
        assertEquals(listOf("/api/me"), gateway.calls.map { it.first })
        model.logout()
        assertTrue(gateway.cleared)
        assertEquals("", model.authenticatedName)
        assertNull(model.authenticatedFamilyId)
        assertEquals(EntryScreen.INTRO, model.screen)
        assertEquals(1, gateway.calls.size)
    }
    @Test fun existingLoginPreservesNameAndOwnerLossClearsIt() = runBlocking {
        val gateway = Gateway().apply { response = { JSONObject().put("family_id", 1).put("name", "נועה") } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.EXISTING_ACCOUNT)
        assertEquals("נועה", model.authenticatedName)
        assertEquals(1L, model.authenticatedFamilyId)
        model.leaveAuthenticatedApp()
        assertEquals("", model.authenticatedName)
        assertNull(model.authenticatedFamilyId)
    }
    @Test fun createFamilyNameAdvancesLocallyForHebrewAndUnicodeWhitespace() = runBlocking {
        for (name in listOf("כהן", "כהן\u00a0לוי", "כהן\u2003לוי", "כהן\tלוי")) {
            val gateway = Gateway().apply { response = { error("Step one must not request the server") } }
            val model = OnboardingModel(gateway)
            model.select(LoginRoute.CREATE_FAMILY)
            model.authenticated(LoginRoute.CREATE_FAMILY)
            model.familyName = name
            model.next()
            assertEquals(2, model.step)
            assertNull(model.error)
            assertFalse(model.busy)
            assertTrue(gateway.calls.isEmpty())
        }
    }
    @Test fun candidateCoordinatesClearOnChangeAndCannotCrossIdentity() = runBlocking {
        var owner = "A"
        val gateway = Gateway().apply { response = { JSONObject().put("normalized_address", "typed")
            .put("display_address", "proposal").put("resolution_token", "opaque")
            .put("latitude", 31.0).put("longitude", 35.0) } }
        val model = OnboardingModel(gateway) { owner }
        model.authenticated(LoginRoute.CREATE_FAMILY)
        model.familyName = "כהן"; model.next()
        model.address = "רחוב רב מילים 12 עיר"; model.next()
        assertEquals(31.0, model.addressLocation!!.latitude, 0.0)
        owner = "B"; assertNull(model.addressLocation)
        model.changeAddress(); assertNull(model.addressLocation)
    }
    @Test fun joinUsesOnlySubmittedCandidateCoordinates() = runBlocking {
        val gateway = Gateway().apply { response = { path ->
            JSONObject().put("step", if(path.endsWith("address")) "address_confirmed" else if(path.endsWith("family-name")) "address" else "family_name")
                .put("latitude", 31.5).put("longitude", 35.5)
        } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.JOIN_FAMILY)
        model.familyName = "כהן"; model.next()
        model.address = "רחוב 12 עיר"; model.next()
        assertEquals(31.5, model.addressLocation!!.latitude, 0.0)
        model.back(); assertNull(model.addressLocation)
    }
    private class Gateway : OnboardingGateway {
        val calls = mutableListOf<Triple<String, String, JSONObject?>>()
        var activated = false
        var cleared = false
        var response: (String) -> JSONObject = { JSONObject() }
        override suspend fun request(path: String, method: String, body: JSONObject?): JSONObject {
            calls += Triple(path, method, body)
            return response(path)
        }
        override suspend fun activate() { activated = true }
        override suspend fun clearSession() { cleared = true }
    }
    @Test fun localBootstrapValidatesWithoutReactivatingAndRetriesWithoutClearing() = runBlocking {
        val gateway = Gateway().apply { response = { error("offline") } }
        val model = OnboardingModel(gateway)
        model.bootstrap { true }
        assertEquals(EntryScreen.BOOTSTRAP, model.screen)
        assertFalse(gateway.cleared); assertFalse(gateway.activated)
        gateway.response = { JSONObject().put("family_id", 1) }
        model.bootstrap { true }
        assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
        assertFalse(gateway.activated)
        assertEquals(listOf("/api/me", "/api/me"), gateway.calls.map { it.first })
    }
    @Test fun localBootstrapOnlyExactMissingAccountClears() = runBlocking {
        for (detail in listOf("Authenticated user is not registered in the application",
            "Authenticated user is not assigned to a family", "Forbidden")) {
            val gateway = Gateway().apply { response = {
                throw OnboardingFailure.parse(403, "/api/me", JSONObject().put("detail", detail).toString())
            } }
            val model = OnboardingModel(gateway)
            model.bootstrap { true }
            assertEquals(detail != "Forbidden", gateway.cleared)
            assertEquals(if (detail == "Forbidden") EntryScreen.BOOTSTRAP else EntryScreen.INTRO, model.screen)
            assertFalse(gateway.activated)
        }
    }
    @Test fun localBootstrapCannotEnterForChangedOwner() = runBlocking {
        var current = true
        val gateway = Gateway().apply { response = { current = false; JSONObject().put("family_id", 1) } }
        val model = OnboardingModel(gateway)
        model.bootstrap { current }
        assertEquals(EntryScreen.INTRO, model.screen)
        assertFalse(gateway.activated); assertFalse(gateway.cleared)
    }
    @Test fun bootstrapShowsLoadingUntilValidationFinishes() = runBlocking {
        val release = CompletableDeferred<Unit>()
        val model = OnboardingModel(object : OnboardingGateway {
            override suspend fun request(path: String, method: String, body: JSONObject?): JSONObject {
                release.await(); return JSONObject().put("family_id", 1)
            }
            override suspend fun activate() = error("Must not reactivate")
            override suspend fun clearSession() = error("Must not clear")
        })
        val job = launch { model.bootstrap { true } }; yield()
        assertEquals(EntryScreen.BOOTSTRAP, model.screen); assertTrue(model.busy)
        release.complete(Unit); job.join()
        assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
        model.leaveAuthenticatedApp(); assertEquals(EntryScreen.INTRO, model.screen)
    }
    @Test fun allIntroChoicesUseSharedLoginAndRouteSurvivesBrowserProcessRecreation() {
        for (route in LoginRoute.entries) {
            val model = OnboardingModel(Gateway())
            model.select(route)
            assertEquals(EntryScreen.LOGIN, model.screen)
            assertEquals(route, model.route)
            val context = RuntimeEnvironment.getApplication()
            PendingLoginRoute(context).save(route, 1000)
            assertEquals(route, PendingLoginRoute(context).take(2000))
            assertNull(PendingLoginRoute(context).take(2001))
            PendingLoginRoute(context).save(route, 1000)
            assertNull(PendingLoginRoute(context).take(601001))
        }
    }
    @Test fun existingAccountActivatesOnlyAfterValidMe() = runBlocking {
        val gateway = Gateway().apply { response = { JSONObject().put("family_id", 1) } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.EXISTING_ACCOUNT)
        assertEquals("/api/me", gateway.calls.single().first)
        assertTrue(gateway.activated)
        assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
    }
    @Test fun missingAccountReturnsToIntroButUnrelated403DoesNot() = runBlocking {
        for (detail in listOf("Authenticated user is not registered in the application",
            "Authenticated user is not assigned to a family", "Forbidden")) {
            val gateway = Gateway().apply { response = {
                throw OnboardingFailure.parse(403, "/api/me", JSONObject().put("detail", detail).toString())
            } }
            val model = OnboardingModel(gateway)
            model.select(LoginRoute.EXISTING_ACCOUNT)
            model.authenticated(LoginRoute.EXISTING_ACCOUNT)
            assertFalse(gateway.activated)
            assertEquals(detail != "Forbidden", gateway.cleared)
            assertEquals(if (detail == "Forbidden") EntryScreen.LOGIN else EntryScreen.INTRO, model.screen)
            assertNotNull(model.error)
        }
    }
    @Test fun createHasFourStepsAndUsesOnlyServerResolutionToken() = runBlocking {
        val gateway = Gateway().apply { response = { path -> when(path) {
            "/api/onboarding/create-family/address" -> JSONObject().put("resolution_token", "fixture-resolution")
                .put("display_address", "כתובת לבדיקה").put("normalized_address", "כתובת לבדיקה")
            "/api/me" -> JSONObject().put("family_id", 1).put("name", "שם מהשרת")
            "/api/family" -> JSONObject().put("family_code", "abc123")
            else -> JSONObject().put("created", true)
        } } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.CREATE_FAMILY)
        assertEquals(4, model.totalSteps)
        model.familyName = "משפחה"
        model.next(); assertEquals(2, model.step)
        model.address = "כתובת לבדיקה"
        model.next(); assertEquals(3, model.step)
        model.back(); assertEquals(2, model.step); assertEquals("כתובת לבדיקה", model.address)
        model.next(); model.next(); assertEquals(4, model.step)
        model.userName = "שם"
        model.next(); assertNotNull(model.error)
        assertFalse(gateway.calls.any { it.first == "/api/onboarding/create-family" })
        model.consent = true; model.next()
        val payload = gateway.calls.single { it.first == "/api/onboarding/create-family" }.third!!
        assertEquals(setOf("family_name", "user_name", "address_resolution_token"), payload.keys().asSequence().toSet())
        assertEquals("fixture-resolution", payload.getString("address_resolution_token"))
        assertEquals(EntryScreen.SUCCESS, model.screen); assertEquals("abc123", model.createdCode)
        assertTrue(gateway.activated)
        model.next(); assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
        assertEquals("שם מהשרת", model.authenticatedName)
        assertEquals(1L, model.authenticatedFamilyId)
        model.back(); assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
        assertEquals("", model.createdCode)
    }
    @Test fun joinUsesServerStepsAndExactEndpoints() = runBlocking {
        val stages = mapOf("start" to "family_name", "family-name" to "address",
            "address" to "address_confirmed", "address-confirmation" to "family_code", "code" to "user_name")
        val gateway = Gateway().apply { response = { path ->
            if (path == "/api/me") JSONObject().put("family_id", 1).put("name", "שם מהשרת")
            else JSONObject().put("step", stages[path.substringAfterLast('/')] ?: "user_name")
                .put("resolved_address", "בית")
        } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.JOIN_FAMILY)
        model.familyName = "משפחה"; model.next(); assertEquals(2, model.step)
        model.address = "בית"; model.next(); assertEquals(3, model.step)
        model.next(); assertEquals(4, model.step)
        model.joinCode = "ab12cd"; model.next(); assertEquals(5, model.step)
        model.userName = "שם"; model.consent = true; model.next()
        assertEquals(EntryScreen.SUCCESS, model.screen)
        assertEquals(listOf("start", "family-name", "address", "address-confirmation", "code", "complete", "me"),
            gateway.calls.map { it.first.substringAfterLast('/') })
        assertEquals("ab12cd", gateway.calls[4].third!!.getString("family_code"))
        model.next(); assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
        assertEquals("שם מהשרת", model.authenticatedName)
        model.back(); assertEquals(EntryScreen.AUTHENTICATED_APP, model.screen)
    }
    @Test fun joinResumesAuthoritativeStepAndKeepsServerAttemptMetadata() = runBlocking {
        val gateway = Gateway().apply { response = { path ->
            if (path.endsWith("start")) JSONObject().put("step", "family_code")
            else throw OnboardingFailure.parse(400, path,
                """{"detail":{"code":"INVALID_FAMILY_CODE","message":"קוד שגוי","attempts_remaining":2}}""")
        } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.JOIN_FAMILY); assertEquals(4, model.step)
        model.joinCode = "bad"; model.next()
        assertEquals("bad", gateway.calls.last().third!!.getString("family_code"))
        assertEquals("קוד שגוי", model.error)
        assertEquals(2, model.failure!!.attemptsRemaining)
        assertEquals(4, model.step)
    }
    @Test fun partialCompletionRetriesReadsNotCreation() = runBlocking {
        val gateway = Gateway()
        var readFails = true
        gateway.response = { path -> when {
            path.endsWith("start") -> JSONObject().put("step", "user_name")
            path == "/api/me" && readFails -> error("fixture")
            path == "/api/me" -> JSONObject().put("family_id", 1)
            else -> JSONObject()
        } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.JOIN_FAMILY)
        model.userName = "שם"; model.consent = true; model.next()
        assertNotNull(model.error)
        readFails = false; model.next()
        assertEquals(1, gateway.calls.count { it.first.endsWith("complete") })
        assertEquals(EntryScreen.SUCCESS, model.screen)
    }
    @Test fun unicodeNameValidationMatchesOnboardingSeparatorsAndBounds() {
        for (name in listOf("כהן", "ז׳אנה", "Jean–Luc", "O'Neil", "כהן לוי", "李".repeat(100))) {
            assertTrue(name, OnboardingModel.validName(name))
        }
        for (name in listOf("", "123", "שם 1", "-שם", "שם--שם", "א".repeat(101))) {
            assertFalse(name, OnboardingModel.validName(name))
        }
    }
    @Test fun serverConflictResynchronizesWithoutLocalReset() = runBlocking {
        var starts = 0
        val gateway = Gateway().apply { response = { path ->
            if (path.endsWith("start")) {
                starts++
                JSONObject().put("step", "user_name")
            } else throw OnboardingFailure.parse(409, path,
                """{"detail":{"code":"INVALID_JOIN_STEP","message":"יש להשלים את השלב הנוכחי"}}""")
        } }
        val model = OnboardingModel(gateway)
        model.authenticated(LoginRoute.JOIN_FAMILY)
        model.back(); model.back(); assertEquals(3, model.step)
        model.next()
        assertEquals(5, model.step)
        assertEquals(2, starts)
        assertNotNull(model.error)
    }
    @Test fun inFlightRequestPreventsDoubleSubmitAndBackNavigation() = runBlocking {
        val release = CompletableDeferred<Unit>()
        var calls = 0
        val gateway = object : OnboardingGateway {
            override suspend fun request(path: String, method: String, body: JSONObject?): JSONObject {
                calls++; release.await()
                return JSONObject().put("step", "family_name")
            }
            override suspend fun activate() = Unit
            override suspend fun clearSession() = Unit
        }
        val model = OnboardingModel(gateway)
        model.select(LoginRoute.JOIN_FAMILY)
        val first = launch { model.authenticated(LoginRoute.JOIN_FAMILY) }
        yield(); assertTrue(model.busy)
        model.authenticated(LoginRoute.JOIN_FAMILY); model.back()
        assertEquals(EntryScreen.LOGIN, model.screen)
        assertEquals(1, calls)
        release.complete(Unit); first.join()
        assertFalse(model.busy)
        assertEquals(EntryScreen.ONBOARDING, model.screen)
    }
}
