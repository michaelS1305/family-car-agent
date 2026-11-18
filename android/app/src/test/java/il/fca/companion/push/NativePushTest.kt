package il.fca.companion.push

import android.app.Application
import il.fca.companion.net.HttpFailure
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.Instant
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class NativePushTest {
    private fun ref() = UUID.randomUUID().toString()
    private class Fixture {
        var now = 1_800_000_000_000L
        var owner: String? = "account-a"
        var saved = JSONObject()
        var token = "offline-fcm-token-one"
        var expected = 1L
        var deleted = 0
        var cleared = 0
        var allowed = true
        var early = true
        val challenge = UUID.randomUUID().toString()
        val shown = mutableListOf<PushEvent>()
        val requests = mutableListOf<Triple<String, String, JSONObject?>>()
        var override: ((String, String, JSONObject?) -> JSONObject?)? = null
        lateinit var engine: PushEngine
        init { restart(); engine.activate(owner!!, 1) }
        fun signal() = mapOf("kind" to "registration_challenge", "challenge_ref" to challenge,
            "installation_ref" to saved.getString("ref"), "nonce" to "n".repeat(43), "generation" to expected.toString())
        fun restart() {
            engine = PushEngine(JSONObject(saved.toString()), { saved = JSONObject(it.toString()) }, { owner }, { owner },
                { who, path, _, body ->
                    requests.add(Triple(who, path, body))
                    override?.invoke(who, path, body) ?: when {
                        path.endsWith("/registrations") -> {
                            if (early) assertTrue(engine.receive(signal()))
                            JSONObject().put("code", "CHALLENGE_PENDING").put("challenge_ref", challenge)
                                .put("expected_generation", expected).put("expires_at", Instant.ofEpochMilli(now + 120_000).toString())
                        }
                        path.endsWith("/confirm") -> JSONObject().put("code", "ACTIVE").put("generation", expected + 1)
                        path.endsWith("/revoke") -> JSONObject().put("code", "REVOKED")
                        else -> page()
                    }
                }, { token }, { deleted++ }, { event -> if (allowed) shown.add(event); allowed }, { cleared++ }, { now })
        }
        fun page(vararg events: JSONObject) = JSONObject().put("items", JSONArray(events.toList())).put("has_more", false)
        fun event(type: String = "vehicle_taken", expiry: Long = now + 60_000) = JSONObject()
            .put("event_ref", UUID.randomUUID().toString()).put("type", type)
            .put("occurred_at", Instant.ofEpochMilli(expiry - 300_000).toString())
            .put("expires_at", Instant.ofEpochMilli(expiry).toString())
            .put("actor_name", "דניאל").put("vehicle_ref", UUID.randomUUID().toString()).put("vehicle_name", "היונדאי")
    }
    @Test fun exactRegistrationSchema() {
        val body = registrationBody(ref(), ref(), "fixture-token")
        assertEquals(setOf("installation_ref", "request_id", "platform", "token"), body.keys().asSequence().toSet())
        assertEquals("android", body.getString("platform"))
    }
    @Test fun reminderRequiresAuthorizedScheduleAndKeepsShortExpiry() {
        val f = Fixture()
        for (type in listOf("reservation_reminder", "maintenance_reminder")) {
            val body = f.event(type)
            assertNull(PushEvent.parse(body, f.now))
            body.put("scheduled_for", Instant.ofEpochMilli(f.now + 3_600_000).toString())
            val parsed = PushEvent.parse(body, f.now)
            assertNotNull(parsed)
            assertTrue(parsed!!.text().contains("תזכורת"))
            assertTrue(parsed.text().contains("היונדאי"))
            body.put("scheduled_for", Instant.ofEpochMilli(f.now - 1).toString())
            assertNull(PushEvent.parse(body, f.now))
        }
    }
    @Test fun opaqueProtocolRejectsExtraFieldsAndVersions() {
        assertTrue(refreshSignal(mapOf("kind" to "refresh", "version" to "1")))
        assertFalse(refreshSignal(mapOf("kind" to "refresh", "version" to "2")))
        assertFalse(refreshSignal(mapOf("kind" to "refresh", "version" to "1", "actor" to "private")))
    }
    @Test fun eventPathHasOnlyGenerationLimitAndValidatedCursor() {
        val installation = ref(); val cursor = ref()
        assertEquals("$PUSH_ROOT/installations/$installation/events?expected_generation=2&limit=20&cursor=$cursor",
            eventsPath(installation, 2, cursor))
        assertTrue(runCatching { eventsPath(installation, 2, "other&owner=x") }.isFailure)
    }
    @Test fun earlyChallengeConfirmedAndGenerationPersisted() {
        val f = Fixture(); assertTrue(f.engine.run())
        assertTrue(f.saved.getBoolean("registered")); assertEquals(2, f.saved.getLong("generation"))
        assertFalse(f.saved.has("pending"))
        val body = f.requests.single { it.second.endsWith("/confirm") }.third!!
        assertEquals(setOf("challenge_ref", "nonce"), body.keys().asSequence().toSet())
        assertFalse(f.engine.receive(f.signal()))
    }
    @Test fun restartReusesInstallationAndDoesNotRegisterAgain() {
        val f = Fixture(); f.engine.run(); val ref = f.saved.getString("ref")
        f.restart(); f.engine.activate(f.owner!!, 1); f.engine.run()
        assertEquals(ref, f.saved.getString("ref"))
        assertEquals(1, f.requests.count { it.second.endsWith("/registrations") })
    }
    @Test fun tokenRotationUsesSameInstallationAndNewRequestGeneration() {
        val f = Fixture(); f.engine.run(); val ref = f.saved.getString("ref")
        f.expected = 2; f.token = "rotated-offline-token"; f.engine.run()
        assertEquals(ref, f.saved.getString("ref")); assertEquals(3, f.saved.getLong("generation"))
        assertEquals(2, f.requests.filter { it.second.endsWith("/registrations") }.map { it.third!!.getString("request_id") }.distinct().size)
    }
    @Test fun interruptedBeginRetriesSameRequestId() {
        val f = Fixture(); var first = true
        f.override = { _, path, _ -> if (path.endsWith("/registrations") && first) { first = false; throw java.io.IOException() }; null }
        assertFalse(f.engine.run()); f.restart(); assertTrue(f.engine.run())
        assertEquals(1, f.requests.filter { it.second.endsWith("/registrations") }.map { it.third!!.getString("request_id") }.distinct().size)
    }
    @Test fun idempotentChallengeExistsUsesMatchingReceivedGeneration() {
        val f = Fixture()
        f.override = { _, path, _ -> if (path.endsWith("/registrations")) {
            f.engine.receive(f.signal()); JSONObject().put("code", "CHALLENGE_EXISTS").put("status", "pending").put("challenge_ref", f.challenge)
        } else null }
        assertTrue(f.engine.run()); assertEquals(2, f.saved.getLong("generation"))
    }
    @Test fun malformedAndWrongInstallationChallengesIgnored() {
        val f = Fixture(); f.early = false; f.engine.run()
        assertFalse(f.engine.receive(f.signal() + ("nonce" to "bad")))
        assertFalse(f.engine.receive(f.signal() + ("installation_ref" to ref())))
        assertFalse(f.engine.receive(f.signal() + ("challenge_ref" to ref())))
        assertFalse(f.engine.receive(f.signal() + ("generation" to "9")))
    }
    @Test fun expiredChallengeNeverConfirmed() {
        val f = Fixture(); f.early = false; f.engine.run(); f.now += 120_001
        assertFalse(f.engine.receive(f.signal())); f.engine.run()
        assertEquals(0, f.requests.count { it.second.endsWith("/confirm") })
    }
    @Test fun unexpectedConfirmedGenerationFailsClosed() {
        val f = Fixture(); f.override = { _, path, _ -> if (path.endsWith("/confirm")) JSONObject().put("code", "ACTIVE").put("generation", 200) else null }
        f.engine.run(); assertFalse(f.saved.optBoolean("registered"))
        assertEquals(0, f.requests.count { it.second.contains("/events?") })
    }
    @Test fun logoutFencesPendingConfirmationAndPreservesReconciliation() {
        val f = Fixture(); f.override = { _, path, _ -> if (path.endsWith("/confirm")) { f.engine.invalidate(); f.owner = null }; null }
        f.engine.run()
        assertFalse(f.saved.optBoolean("registered")); assertFalse(f.saved.has("owner"))
        assertEquals(1, f.saved.getJSONArray("revocations").length())
        assertTrue(f.shown.isEmpty())
    }
    @Test fun accountSwitchCannotApplyOldFetchAndUsesNewInstallation() {
        val f = Fixture(); f.engine.run(); val old = f.saved.getString("ref")
        f.override = { _, path, _ -> if (path.contains("/events?")) {
            f.engine.invalidate(); f.owner = "account-b"; f.engine.activate("account-b", 1); f.page(f.event())
        } else null }
        f.engine.run()
        assertTrue(f.shown.isEmpty()); assertNotEquals(old, f.saved.getString("ref"))
        assertEquals("account-b", f.saved.getString("owner"))
    }
    @Test fun familyChangeFencesOldFetch() {
        val f = Fixture(); f.engine.run()
        f.override = { _, path, _ -> if (path.contains("/events?")) { f.engine.activate(f.owner!!, 2); f.page(f.event()) } else null }
        f.engine.run(); assertTrue(f.shown.isEmpty())
    }
    @Test fun revokeOnlyUsesMatchingCurrentAccount() {
        val f = Fixture(); f.engine.run(); f.engine.invalidate(); f.owner = "account-b"; f.engine.activate("account-b", 1)
        f.engine.run(); assertTrue(f.requests.none { it.second.endsWith("/revoke") })
        f.engine.invalidate(); f.owner = "account-a"; f.engine.activate("account-a", 1); f.engine.run()
        assertTrue(f.requests.any { it.first == "account-a" && it.second.endsWith("/revoke") })
    }
    @Test fun offlineRevocationRetainedAndLocalTokenReset() {
        val f = Fixture(); f.engine.run(); f.engine.invalidate()
        f.override = { _, path, _ -> if (path.endsWith("/revoke")) throw java.io.IOException(); null }
        f.engine.run(); assertTrue(f.saved.getJSONArray("revocations").length() > 0); assertEquals(1, f.deleted)
        assertTrue(f.cleared > 0)
    }
    @Test fun authDeniedClearsPresentationAndStopsFetch() {
        val f = Fixture(); f.engine.run()
        f.override = { _, path, _ -> if (path.contains("/events?")) throw HttpFailure(403); null }
        assertTrue(f.engine.run()); assertFalse(f.saved.getBoolean("registered")); assertTrue(f.cleared > 1)
    }
    @Test fun duplicateSuppressionSurvivesRestartWithoutNamesOrTokens() {
        val f = Fixture(); val item = f.event()
        f.override = { _, path, _ -> if (path.contains("/events?")) f.page(item, item) else null }
        f.engine.run(); f.restart(); f.engine.run()
        assertEquals(1, f.shown.size)
        assertFalse(f.saved.toString().contains("דניאל")); assertFalse(f.saved.toString().contains(f.token))
        assertFalse(f.saved.toString().contains("היונדאי")); assertFalse(f.saved.toString().contains("nonce"))
    }
    @Test fun expiredUnknownAndTooLongLifetimeEventsNeverDisplay() {
        val f = Fixture()
        f.override = { _, path, _ -> if (path.contains("/events?")) f.page(f.event(expiry = f.now), f.event("unknown"),
            f.event().put("occurred_at", Instant.ofEpochMilli(f.now - 400_000).toString())) else null }
        f.engine.run(); assertTrue(f.shown.isEmpty())
    }
    @Test fun paginationBoundedAndEachRefreshStartsAtPageOne() {
        val f = Fixture(); val cursor = ref()
        f.override = { _, path, _ -> if (path.contains("/events?")) {
            if (path.contains("cursor=")) f.page(f.event()) else f.page().put("has_more", true).put("next_cursor", cursor)
        } else null }
        f.engine.run(); f.engine.run()
        val paths = f.requests.filter { it.second.contains("/events?") }.map { it.second }
        assertEquals(4, paths.size); assertFalse(paths[0].contains("cursor=")); assertFalse(paths[2].contains("cursor="))
    }
    @Test fun repeatingCursorCannotLoop() {
        val f = Fixture(); val cursor = ref()
        f.override = { _, path, _ -> if (path.contains("/events?")) f.page().put("has_more", true).put("next_cursor", cursor) else null }
        assertFalse(f.engine.run()); assertEquals(2, f.requests.count { it.second.contains("/events?") })
    }
    @Test fun deniedNotificationsNotMarkedDisplayedAndCanCatchUp() {
        val f = Fixture(); val item = f.event(); f.allowed = false
        f.override = { _, path, _ -> if (path.contains("/events?")) f.page(item) else null }
        f.engine.run(); assertTrue(f.shown.isEmpty()); f.allowed = true; f.engine.run(); assertEquals(1, f.shown.size)
    }
    @Test fun hintDuringFetchRequestsBoundedFollowUp() {
        val f = Fixture(); f.engine.run()
        f.override = { _, path, _ -> if (path.contains("/events?")) f.engine.receive(mapOf("kind" to "refresh", "version" to "1")); null }
        assertFalse(f.engine.run())
    }
    @Test fun stoppedWorkerDoesNotFetchOrDisplay() {
        val f = Fixture(); f.engine.run { true }; assertTrue(f.requests.isEmpty()); assertTrue(f.shown.isEmpty())
    }
    @Test fun permissionAndChannelDecisions() {
        assertTrue(pushNotificationsAllowed(true, true, 3))
        assertFalse(pushNotificationsAllowed(false, true, 3))
        assertFalse(pushNotificationsAllowed(true, false, 3))
        assertFalse(pushNotificationsAllowed(true, true, 0))
        assertFalse(pushNotificationsAllowed(true, true, null))
    }
    @Test fun hebrewFormatting() {
        val f = Fixture()
        assertEquals("דניאל לקח את היונדאי", PushEvent.parse(f.event(), f.now)!!.text())
        assertEquals("דניאל החזיר את היונדאי", PushEvent.parse(f.event("vehicle_returned"), f.now)!!.text())
    }
    @Test fun registrationAttemptsAreCappedAndCooldownSurvivesRestart() {
        val f = Fixture()
        f.override = { _, path, _ -> if (path.endsWith("/registrations")) throw java.io.IOException(); null }
        repeat(6) { f.engine.run() }
        assertEquals(3, f.requests.size)
        f.now += 120_001; f.engine.run(); f.restart(); f.engine.run()
        assertEquals(3, f.requests.size)
    }
    @Test fun dedupMetadataPrunedEvenWhenInboxEmpty() {
        val f = Fixture(); val item = f.event()
        f.override = { _, path, _ -> if (path.contains("/events?")) f.page(item) else null }
        f.engine.run(); assertEquals(1, f.saved.getJSONObject("seen").length())
        f.now += 600_001; f.override = null; f.engine.run()
        assertEquals(0, f.saved.getJSONObject("seen").length())
    }
    @Test fun overlappingWorkersAreSerializedAndDisplayOnce() {
        val f = Fixture(); f.engine.run(); val item = f.event()
        val entered = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        f.override = { _, path, _ -> if (path.contains("/events?")) {
            entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)); f.page(item)
        } else null }
        val pool = java.util.concurrent.Executors.newFixedThreadPool(2)
        try {
            val first = pool.submit<Boolean> { f.engine.run() }
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
            val second = pool.submit<Boolean> { f.engine.run() }
            release.countDown()
            assertTrue(first.get(5, java.util.concurrent.TimeUnit.SECONDS)); assertTrue(second.get(5, java.util.concurrent.TimeUnit.SECONDS))
            assertEquals(1, f.shown.size)
        } finally { release.countDown(); pool.shutdownNow() }
    }
    @Test fun staleAuthorizationFailureCannotClearNewAccountNotifications() {
        val f = Fixture(); f.engine.run(); var clearsAfterSwitch = 0
        f.override = { _, path, _ -> if (path.contains("/events?")) {
            f.engine.invalidate(); f.owner = "account-b"; f.engine.activate("account-b", 2)
            clearsAfterSwitch = f.cleared; throw HttpFailure(403)
        }; null }
        f.engine.run(); assertEquals(clearsAfterSwitch, f.cleared)
    }
    @Test fun tokenRetrievalFailureNeverCreatesUnboundRegistration() {
        val f = Fixture()
        val engine = PushEngine(JSONObject(), {}, { "a" }, { "a" }, { _, _, _, _ -> error("No HTTP") },
            { throw java.io.IOException() }, {}, { false }, {}, { f.now })
        engine.activate("a", 1); assertFalse(engine.run())
    }
    @Test fun lostConfirmationRetainsPossibleGenerationAfterChallengeExpiry() {
        val f = Fixture()
        f.override = { _, path, _ -> if (path.endsWith("/confirm")) throw java.io.IOException(); null }
        assertFalse(f.engine.run()); f.now += 120_001; f.engine.run(); f.engine.invalidate()
        assertEquals(2, f.saved.getJSONArray("revocations").getJSONObject(0).getLong("generation"))
    }
}
