package il.fca.companion

import android.app.Application
import il.fca.companion.ui.*
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class AccountSettingsTest {
    @Test fun deletingAccountAfterProcessRestartClearsSessionButOtherErrorsDoNot() = runBlocking {
        for (code in listOf("ACCOUNT_UNAVAILABLE", "OTHER")) {
            var cleared = 0
            val failure = il.fca.companion.net.OnboardingFailure.parse(403, "/api/me",
                """{"detail":{"code":"$code","message":"untrusted"}}""")
            val model = OnboardingModel(object : OnboardingGateway {
                override suspend fun request(path: String, method: String, body: JSONObject?): JSONObject = throw failure
                override suspend fun activate() { error("must not activate") }
                override suspend fun clearSession() { cleared++ }
            })
            model.bootstrap { true }
            assertEquals(if (code == "ACCOUNT_UNAVAILABLE") 1 else 0, cleared)
            assertEquals(if (code == "ACCOUNT_UNAVAILABLE") EntryScreen.INTRO else EntryScreen.BOOTSTRAP, model.screen)
        }
    }
    private class Gateway : AccountSettingsGateway {
        val calls = mutableListOf<String>()
        var emailAction: suspend () -> String? = { "actual@example.test" }
        var action: suspend (String, Boolean) -> JSONObject = { method, preview ->
            JSONObject().put(if (preview) "consequence" else "status",
                if (preview) "personal" else if (method == "POST") "draining" else "not_requested")
        }
        override suspend fun email(owner: String) = emailAction()
        override suspend fun request(owner: String, method: String, preview: Boolean): JSONObject {
            calls += "$owner:$method:$preview"
            return action(method, preview)
        }
    }
    @Test fun explicitConfirmationOnlyAndAcceptedCannotDismissOrReplay() = runBlocking {
        val api = Gateway()
        val model = AccountSettingsModel(api, { AccountIdentity("A", 1) }, this)
        model.confirm(); assertTrue(api.calls.isEmpty())
        model.openDeletion(); yield()
        assertEquals("personal", model.state.consequence)
        assertFalse(api.calls.any { ":POST:" in it })
        model.confirm(); model.confirm(); yield()
        assertEquals("draining", model.state.phase)
        model.dismiss(); assertTrue(model.state.dialog)
        model.confirm(); yield()
        assertEquals(1, api.calls.count { ":POST:" in it })
    }
    @Test fun uncertainPostSurvivesNavigationAndEmptyStatusCannotUnlock() = runBlocking {
        val api = Gateway()
        val model = AccountSettingsModel(api, { AccountIdentity("A", 1) }, this)
        model.openDeletion(); yield()
        api.action = { method, _ ->
            if (method == "POST") error("private transport text")
            JSONObject().put("status", "not_requested")
        }
        model.confirm(); yield()
        assertTrue(model.state.uncertain)
        assertFalse(model.state.error!!.contains("private"))
        model.dismiss(); model.openDeletion(); yield()
        assertTrue(model.state.uncertain); assertNull(model.state.consequence)
        model.confirm(); yield()
        assertEquals(1, api.calls.count { ":POST:" in it })
        api.action = { _, _ -> JSONObject().put("status", "auth_pending") }
        model.checkStatus(); yield()
        assertFalse(model.state.uncertain); assertTrue(model.state.protected)
    }
    @Test fun accountAndFamilyChangesMaskAndRejectLateResponses() = runBlocking {
        for (replacement in listOf(AccountIdentity("B", 1), AccountIdentity("A", 2), null)) {
            var identity: AccountIdentity? = AccountIdentity("A", 1)
            val deferred = CompletableDeferred<JSONObject>()
            val email = CompletableDeferred<String?>()
            val api = Gateway().apply {
                action = { _, _ -> deferred.await() }
                emailAction = { email.await() }
            }
            val model = AccountSettingsModel(api, { identity }, this)
            model.openDeletion(); model.loadEmail(); yield()
            identity = replacement
            assertFalse(model.state.dialog); assertNull(model.state.email)
            model.reconcile()
            deferred.complete(JSONObject().put("status", "completed"))
            email.complete("old@example.test"); yield()
            assertNull(model.state.email); assertNull(model.state.phase)
        }
    }
    @Test fun emailUnavailableIsNotInventedAndLogoutClearsIt() = runBlocking {
        var identity: AccountIdentity? = AccountIdentity("A", 1)
        val api = Gateway()
        val model = AccountSettingsModel(api, { identity }, this)
        model.loadEmail(); yield(); assertEquals("actual@example.test", model.state.email)
        api.emailAction = { throw IllegalStateException("private") }
        model.loadEmail(); yield(); assertNull(model.state.email)
        identity = null; model.reconcile()
        assertEquals(AccountSettingsState(), model.state)
    }
    @Test fun allServerConsequencesAndInvalidResponsesFailClosed() = runBlocking {
        for (consequence in listOf("personal", "management_transferred", "family_deleted", "unknown")) {
            val api = Gateway().apply { action = { _, preview ->
                JSONObject().put(if (preview) "consequence" else "status",
                    if (preview) consequence else "not_requested")
            } }
            val model = AccountSettingsModel(api, { AccountIdentity("A", 1) }, this)
            model.openDeletion(); yield()
            if (consequence == "unknown") {
                assertNull(model.state.consequence); assertNotNull(model.state.error)
            } else assertEquals(consequence, model.state.consequence)
        }
    }
}
