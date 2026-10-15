package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
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
class FamilyTest {
    @Test fun initialVisibleReadObservesCompletionWithoutUnrelatedRecomposition() = runBlocking {
        for (fails in listOf(false, true)) {
            val api = Gateway().apply { if (fails) read = { error("unavailable") } }
            val model = vm(api, this)
            var invalidations = 0
            val observer = androidx.compose.runtime.snapshots.SnapshotStateObserver { it() }
            observer.start()
            try {
                // Composition reads visibleState BEFORE DisposableEffect starts the model.
                observer.observeReads(Any(), { _: Any -> invalidations++ }) {
                    assertTrue(model.visibleState.loading)
                }
                model.start(); model.start(); settle()
                androidx.compose.runtime.snapshots.Snapshot.sendApplyNotifications()
                assertTrue("Initial composition must be invalidated", invalidations > 0)
                assertFalse(model.visibleState.loading)
                assertEquals(fails, model.visibleState.loadError)
                assertEquals(1, api.calls.size)
            } finally { observer.stop(); observer.clear(); model.stop() }
        }
    }
    private val member = FamilyMember("00000000-0000-0000-0000-000000000001", "אב גד", FamilyRole.NONE, true)
    private fun profile(admin: Boolean = true) = FamilyProfile("משפחה", "confirmed", "abc123", admin, listOf(member))
    private inner class Gateway : FamilyGateway {
        var data = profile()
        val calls = mutableListOf<String>()
        var read: suspend () -> FamilyProfile = { data }
        var roleAction: suspend (FamilyRole) -> FamilyMember = { member.copy(role = it) }
        var save: suspend () -> String = { "server canonical" }
        var code: suspend () -> String = { "new123" }
        override suspend fun profile(owner: String): FamilyProfile { calls += "read:$owner"; return read() }
        override suspend fun role(owner: String, ref: String, role: FamilyRole): FamilyMember {
            calls += "role:$owner:$ref"; return roleAction(role)
        }
        override suspend fun resolve(owner: String, draft: String): ResolvedAddress {
            calls += "resolve:$owner:$draft"; return ResolvedAddress("normalized", "display", "test-token")
        }
        override suspend fun address(owner: String, candidate: ResolvedAddress): String {
            calls += "save:$owner:${candidate.token}"; return save()
        }
        override suspend fun regenerate(owner: String): String { calls += "code:$owner"; return code() }
    }
    private suspend fun settle() { repeat(8) { yield() } }
    private fun vm(api: Gateway, scope: CoroutineScope, identity: () -> FamilyIdentity? = { FamilyIdentity("A", 1) }) =
        FamilyViewModel(api, identity, scope)

    @Test fun canonicalAdminAndNullRoleParsing() {
        val row = JSONObject().put("member_ref", member.ref).put("name", member.name)
            .put("role", JSONObject.NULL).put("is_family_admin", true)
        assertEquals(member, FamilyApi.parseMember(row))
        row.put("role", "parent").put("is_family_admin", false)
        assertFalse(FamilyApi.parseMember(row).admin)
        assertEquals("ללא תפקיד", FamilyRole.NONE.label)
        row.put("role", "unknown")
        assertThrows(Exception::class.java) { FamilyApi.parseMember(row) }
        assertEquals("אג", familyInitials("אב גד"))
    }
    @Test fun completeFamilyResponseMatchesBackendContract() {
        val row = JSONObject().put("member_ref", member.ref).put("name", member.name)
            .put("role", JSONObject.NULL).put("is_family_admin", true)
        val response = JSONObject().put("name", "משפחה").put("home_address", "confirmed")
            .put("family_code", "abc123").put("can_edit_roles", true)
            .put("members", org.json.JSONArray().put(row))
        assertEquals(profile(), FamilyApi.parseProfile(response))
    }
    @Test fun nonAdminCannotMutateEvenWithParentRole() = runBlocking {
        val api = Gateway().apply { data = profile(false).copy(members = listOf(member.copy(role = FamilyRole.PARENT))) }
        val model = vm(api, this)
        try {
            model.start(); settle()
            model.role(member.ref, FamilyRole.CHILD); model.editAddress(); model.askRegenerate(); model.regenerate()
            settle(); assertEquals(listOf("read:A"), api.calls)
            assertEquals(AddressStage.VIEW, model.state.addressStage); assertFalse(model.state.codeConfirmation)
        } finally { model.stop() }
    }
    @Test fun roleIsConfirmedOnlyAndDuplicateIsPrevented() = runBlocking {
        val gate = CompletableDeferred<Unit>(); val api = Gateway()
        api.roleAction = { gate.await(); error("failure") }
        val model = vm(api, this)
        try {
            model.start(); settle(); model.role(member.ref, FamilyRole.CHILD); model.role(member.ref, FamilyRole.CHILD); settle()
            assertEquals(FamilyRole.NONE, model.state.profile!!.members.single().role)
            assertEquals(1, api.calls.count { it.startsWith("role:") }); assertFalse(model.state.loading)
            gate.complete(Unit); settle(); assertTrue(member.ref in model.state.roleErrors)
            api.roleAction = { member.copy(role = it) }
            model.role(member.ref, FamilyRole.PARENT); settle()
            assertEquals(FamilyRole.PARENT, model.state.profile!!.members.single().role)
            assertTrue(model.state.roleErrors.isEmpty())
        } finally { model.stop() }
    }
    @Test fun addressRequiresVerificationAndExplicitConfirmationAndRetainsFailedDraft() = runBlocking {
        val api = Gateway(); val model = vm(api, this)
        try {
            model.start(); settle(); model.editAddress(); assertEquals("confirmed", model.state.draft)
            model.draft("discard"); model.cancelAddress(); assertEquals(1, api.calls.size)
            model.editAddress(); model.draft("typed"); model.confirmAddress(); assertEquals(1, api.calls.size)
            model.verifyAddress(); model.verifyAddress(); settle()
            assertEquals(AddressStage.CONFIRM, model.state.addressStage)
            assertEquals("confirmed", model.state.profile!!.address)
            assertFalse(api.calls.any { it.startsWith("save:") })
            api.save = { error("failure") }; model.confirmAddress(); settle()
            assertEquals("typed", model.state.draft); assertNotNull(model.state.candidate)
            assertEquals("confirmed", model.state.profile!!.address)
            api.save = { "server canonical" }; model.confirmAddress(); settle()
            assertEquals("server canonical", model.state.profile!!.address)
            assertEquals(AddressStage.VIEW, model.state.addressStage)
            assertTrue(api.calls.contains("save:A:test-token")); assertEquals("", model.state.draft)
        } finally { model.stop() }
    }
    @Test fun regenerationRequiresConfirmationPreservesOldOnFailureAndUsesServerOnSuccess() = runBlocking {
        val api = Gateway(); val model = vm(api, this)
        try {
            model.start(); settle(); model.regenerate(); model.askRegenerate(); model.cancelRegenerate(); model.regenerate()
            assertEquals(1, api.calls.size)
            val gate = CompletableDeferred<Unit>(); api.code = { gate.await(); error("failure") }
            model.askRegenerate(); model.regenerate(); model.regenerate(); settle()
            assertEquals("abc123", model.state.profile!!.code); assertEquals(1, api.calls.count { it == "code:A" })
            gate.complete(Unit); settle(); assertTrue(model.state.codeError); assertEquals("abc123", model.state.profile!!.code)
            api.code = { "new123" }; model.regenerate(); settle()
            assertEquals("new123", model.state.profile!!.code); assertFalse(model.state.codeConfirmation)
        } finally { model.stop() }
    }
    @Test fun staleOwnerAndGenerationCannotRevealOrApplyData() = runBlocking {
        var identity = FamilyIdentity("A", 1)
        val gate = CompletableDeferred<Unit>(); val api = Gateway()
        api.read = { withContext(NonCancellable) { gate.await() }; profile() }
        val model = vm(api, this) { identity }
        try {
            model.start(); settle(); assertTrue(model.state.loading); assertFalse(model.state.loadError); assertNull(model.state.profile)
            identity = FamilyIdentity("B", 2); assertNull(model.visibleState.profile)
            api.read = { profile(false).copy(code = "bbb123") }; model.start(); settle()
            gate.complete(Unit); settle(); assertEquals("bbb123", model.visibleState.profile!!.code)
            model.stop(); assertNull(model.visibleState.profile)
        } finally { gate.complete(Unit); model.stop() }
    }
    @Test fun sharedAddressResolverKeepsPurposeSpecificContracts() = runBlocking {
        for (create in listOf(true, false)) {
            val result = AddressVerification.resolve("draft", create) { path, body ->
                assertEquals(if (create) "/api/onboarding/create-family/address" else "/api/family/address/resolve", path)
                assertEquals("draft", body.getString("home_address"))
                JSONObject().put("normalized_address", "normalized").put("display_address", "display")
                    .put("resolution_token", "token").apply { if (create) { put("latitude", 0); put("longitude", 0) } }
            }
            assertEquals("token", result.token); assertEquals("display", result.display)
        }
    }
    @Test fun dashboardFamilyUsesExistingBackStack() {
        val shell = AppShellState(); shell.select(AppMode.DASHBOARD); shell.openCategory(DashboardCategory.FAMILY)
        assertEquals(DashboardCategory.FAMILY, shell.category); shell.back(); assertNull(shell.category)
        assertEquals(AppMode.DASHBOARD, shell.mode)
    }
    @Test fun failedInitialLoadIsRetryableWithoutInventedProfile() = runBlocking {
        val api = Gateway().apply { read = { error("unavailable") } }; val model = vm(api, this)
        try {
            assertFalse(model.state.loadError); model.start(); settle()
            assertTrue(model.state.loadError); assertNull(model.state.profile)
            api.read = { profile() }; model.retry(); assertFalse(model.state.loadError)
            settle(); assertEquals(profile(), model.state.profile)
        } finally { model.stop() }
    }
    @Test fun screenWiresExactAssetsInertAddAndCopyFeedback() {
        val source = java.io.File("src/main/java/il/fca/companion/ui/FamilyScreen.kt").readText()
        for (asset in listOf("family_icon", "ic_add", "ic_edit", "ic_copy"))
            assertTrue(source.contains("R.drawable.$asset"))
        assertTrue(source.contains("VehicleProductHeader(back)"))
        assertTrue(source.contains("BackHandler(onBack = back)"))
        assertTrue(source.contains("FamilyIconAction(R.drawable.ic_add, \"הוספה\", {})"))
        assertTrue(source.contains("הקוד הועתק"))
        assertTrue(source.contains("ClipDescription.EXTRA_IS_SENSITIVE"))
    }
}
