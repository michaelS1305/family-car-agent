package il.fca.companion

import android.app.Application
import il.fca.companion.data.LocalStore
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class LocalStoreTest {
    private fun setup(): LocalStore {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        return LocalStore(context).apply {
            installation("mother"); registered("mother", UUID.randomUUID().toString())
            activate("mother"); associate("mother", "Hyundai", "address-one", 1)
        }
    }
    @Test fun duplicateConnectAndDisconnectDoNotCreateExtraTake() {
        val store = setup()
        assertTrue(store.observe(1, true))
        val first = store.next("mother")!!
        assertFalse(store.observe(1, true))
        assertEquals(first, store.next("mother"))
        assertFalse(store.observe(1, false))
        assertEquals(1L, store.pending("mother"))
        assertTrue(store.observe(1, true))
        assertEquals(2L, store.pending("mother"))
    }
    @Test fun processReopenPreservesIdentitySequenceAndPendingPayload() {
        val store = setup(); store.observe(1, true)
        val first = store.next("mother")!!; store.close()
        val reopened = LocalStore(RuntimeEnvironment.getApplication())
        assertEquals(first, reopened.next("mother"))
        assertEquals(2L, reopened.installation("mother").next)
        assertFalse(reopened.observe(1, true))
        reopened.finish(first.id, "retry")
        assertNull(reopened.next("mother"))
    }
    @Test fun multipleVehiclesAndDifferentAccountIsolation() {
        val store = setup()
        store.associate("mother", "Toyota", "address-two", 2)
        assertTrue(store.observe(1, true)); assertTrue(store.observe(2, true))
        store.activate("other")
        assertFalse(store.observe(1, true))
        assertNull(store.next("other")); assertEquals(2L, store.pending("mother"))
    }
    @Test fun ambiguousBluetoothCannotMapToTwoVehicles() {
        val store = setup()
        assertThrows(android.database.sqlite.SQLiteConstraintException::class.java) {
            store.associate("mother", "Toyota", "address-one", 2)
        }
        assertEquals(1, store.associations("mother").size)
        assertFalse(store.observe(999, true))
    }
    @Test fun rebootRearmsButDoesNotErasePendingOrResetSequence() {
        val store = setup()
        store.observeBoot(1); store.observe(1, true)
        val first = store.next("mother")!!
        store.observeBoot(1)
        assertFalse(store.observe(1, true))
        store.observeBoot(2)
        assertTrue(store.observe(1, true))
        assertEquals(first, store.next("mother"))
        assertEquals(3L, store.installation("mother").next)
    }
    @Test fun disconnectGraceOfflineCausalityAndDuplicateProtection() {
        val store = setup(); store.observe(1, true)
        val take = store.next("mother")!!
        store.observe(1, false, 1_000, 1_000)
        val candidate = store.candidates("mother").single()
        assertEquals(take.id, candidate.take)
        assertEquals(30_000L, LocalStore.RETURN_GRACE_MS)
        assertEquals(31_000L, candidate.due)
        assertFalse(store.queueReturn(candidate, "{}", 30_999, 30_999))
        assertFalse(store.queueReturn(candidate, "{}", 31_000, 30_999))
        assertFalse(store.observe(1, false, 2_000))
        assertEquals(candidate, store.candidates("mother").single())
        val evidence = org.json.JSONObject().put("take_event_id", candidate.take).toString()
        assertTrue(store.queueReturn(candidate, evidence, 31_000, 31_000))
        assertFalse(store.queueReturn(candidate, evidence, 31_000, 31_000))
        assertEquals(2L, store.pending("mother"))
        assertEquals(take, store.next("mother"))
        store.finish(take.id, "accepted")
        val returned = store.next("mother")!!
        assertEquals("return", returned.type)
        assertEquals(2L, returned.sequence)
        assertEquals(take.id, org.json.JSONObject(returned.evidence!!).getString("take_event_id"))
    }
    @Test fun reconnectAndAccountChangeFenceInFlightHomeCheck() {
        val store = setup(); store.observe(1, true); store.observe(1, false, 1_000)
        val candidate = store.candidates("mother").single()
        store.observe(1, true, 30_999)
        assertTrue(store.candidates("mother").isEmpty())
        assertFalse(store.queueReturn(candidate, "{}", 31_000))
        store.observe(1, false, 2_000)
        val other = store.candidates("mother").single()
        store.activate("other")
        assertFalse(store.queueReturn(other, "{}", 62_000))
    }
    @Test fun candidateSurvivesReopenAndFailedLocationDoesNotCreateReturn() {
        val store = setup(); store.observe(1, true); store.observe(1, false, 1_000)
        val candidate = store.candidates("mother").single(); store.close()
        val reopened = LocalStore(RuntimeEnvironment.getApplication())
        assertEquals(candidate, reopened.candidates("mother").single())
        reopened.abandon(candidate)
        assertEquals(1L, reopened.pending("mother"))
        assertTrue(reopened.candidates("mother").isEmpty())
    }
    @Test fun homeBoundaryUsesAccuracyAndCacheIsAccountScoped() {
        val store = setup(); store.saveHome("mother", 32.0, 34.0)
        assertEquals(32.0 to 34.0, store.home("mother"))
        assertNull(store.home("other"))
        assertNull(store.home("mother", System.currentTimeMillis() + 86_400_001))
        val fix = android.location.Location("gps").apply { latitude = 32.0; longitude = 34.0; accuracy = 10f }
        assertTrue(il.fca.companion.detector.ReturnWorker.insideHome(fix, 32.0 to 34.0))
        assertFalse(il.fca.companion.detector.ReturnWorker.insideHome(fix, 33.0 to 34.0))
        store.activate(null); assertNull(store.home("mother"))
    }
    @Test fun missingStaleInaccurateAndOutsideFixesDoNotEnqueueReturn() {
        val store = setup(); store.observe(1, true); store.observe(1, false, 1_000, 1_000)
        val candidate = store.candidates("mother").single()
        val fix = android.location.Location("gps").apply {
            latitude = 32.0; longitude = 34.0; accuracy = 10f; time = 61_000; elapsedRealtimeNanos = 61_000_000_000
        }
        val policy = il.fca.companion.detector.ReturnWorker
        assertFalse(policy.usableFix(null, 61_000, 61_000_000_000))
        assertTrue(policy.usableFix(fix, 61_000, 61_000_000_000))
        assertFalse(policy.usableFix(fix, 92_000, 92_000_000_000))
        fix.accuracy = 101f
        assertFalse(policy.usableFix(fix, 61_000, 61_000_000_000))
        fix.accuracy = 10f
        assertFalse(policy.insideHome(fix, 33.0 to 34.0))
        store.abandon(candidate)
        assertEquals(1L, store.pending("mother"))
        assertEquals("take", store.next("mother")!!.type)
    }
    @Test fun sqliteVersionOneUpgradePreservesExistingQueueButDoesNotGuessAcquisition() {
        val store = setup(); store.close()
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        val db = context.openOrCreateDatabase("fca.db", 0, null)
        db.execSQL("CREATE TABLE installations(owner TEXT PRIMARY KEY, request TEXT, device TEXT, next_seq INTEGER)")
        db.execSQL("CREATE TABLE associations(owner TEXT, vehicle TEXT, address TEXT, companion_id INTEGER, connected INTEGER)")
        db.execSQL("CREATE TABLE outbox(id TEXT PRIMARY KEY, owner TEXT, device TEXT, vehicle TEXT, seq INTEGER, occurred TEXT, result TEXT)")
        db.execSQL("INSERT INTO outbox VALUES('old','mother','device','Hyundai',1,'2026-09-28T12:00:00Z',NULL)")
        db.execSQL("INSERT INTO associations VALUES('mother','Hyundai','address',1,1)")
        db.version = 1; db.close()
        val upgraded = LocalStore(context)
        assertEquals("old", upgraded.next("mother")!!.id)
        assertEquals("take", upgraded.next("mother")!!.type)
        assertTrue(upgraded.candidates("mother").isEmpty())
        assertEquals(3, upgraded.readableDatabase.version)
    }

    @Test fun versionTwoUpgradePreservesCandidateHomeIdentityAndOutbox() {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        context.openOrCreateDatabase("fca.db", 0, null).use { db ->
            db.execSQL("CREATE TABLE installations(owner TEXT PRIMARY KEY,request TEXT,device TEXT,next_seq INTEGER)")
            db.execSQL("CREATE TABLE associations(owner TEXT,vehicle TEXT,address TEXT,companion_id INTEGER,connected INTEGER,take_id TEXT,return_due INTEGER,return_elapsed INTEGER)")
            db.execSQL("CREATE TABLE outbox(id TEXT PRIMARY KEY,owner TEXT,device TEXT,vehicle TEXT,seq INTEGER,occurred TEXT,result TEXT,type TEXT,evidence TEXT)")
            db.execSQL("CREATE TABLE active_account(id INTEGER PRIMARY KEY,owner TEXT)")
            db.execSQL("CREATE TABLE return_home(owner TEXT PRIMARY KEY,latitude REAL,longitude REAL,saved INTEGER)")
            db.execSQL("INSERT INTO installations VALUES('mother','registration','device',3)")
            db.execSQL("INSERT INTO active_account VALUES(1,'mother')")
            db.execSQL("INSERT INTO associations VALUES('mother','Hyundai','local',1,0,'take',31000,31000)")
            db.execSQL("INSERT INTO return_home VALUES('mother',32,34,1000)")
            db.execSQL("INSERT INTO outbox VALUES('take','mother','device','Hyundai',1,'original',NULL,'take',NULL)")
            db.execSQL("INSERT INTO outbox VALUES('return','mother','device','Hyundai',2,'later',NULL,'return','immutable')")
            db.version = 2
        }
        LocalStore(context).use { upgraded ->
            assertEquals(3, upgraded.readableDatabase.version)
            assertEquals("registration", upgraded.installation("mother").request)
            assertEquals(3L, upgraded.installation("mother").next)
            assertEquals(32.0 to 34.0, upgraded.home("mother", 32_000))
            val candidate = upgraded.candidates("mother").single()
            assertEquals("take", candidate.take)
            assertEquals(0, upgraded.returnRetry(candidate)!!.attempts)
            assertEquals(0L, upgraded.returnRetry(candidate)!!.waitMs(31_000, 31_000))
            assertEquals(2L, upgraded.pending("mother"))
            upgraded.finish("take", "accepted")
            assertEquals("immutable", upgraded.next("mother")!!.evidence)
            assertEquals("later", upgraded.next("mother")!!.occurredAt)
        }
    }

    @Test fun retryClaimIsDurableAndTtlCannotBeExtendedByClockOrRetries() {
        val store = setup(); store.observeBoot(1)
        store.observe(1, true, 100_000, 100_000); store.observe(1, false, 100_000, 100_000)
        val candidate = store.candidates("mother").single()
        val take = store.next("mother")!!
        assertTrue(store.claimReturn(candidate, 130_000, 130_000))
        assertFalse(store.claimReturn(candidate, 130_000, 130_000))
        store.close()
        LocalStore(RuntimeEnvironment.getApplication()).use { reopened ->
            assertEquals(90_000L, reopened.returnRetry(candidate)!!.waitMs(130_000, 130_000))
            assertEquals(candidate, reopened.candidates("mother").single())
            assertEquals(take, reopened.next("mother"))
            assertEquals(0L, LocalStore.returnLifetime(candidate, 99_999, 130_000))
            assertEquals(0L, LocalStore.returnLifetime(candidate, 130_000, 99_999))
            assertEquals(0L, LocalStore.returnLifetime(candidate, 1_900_000, 130_000))
            assertEquals(0L, LocalStore.returnLifetime(candidate, 130_000, 1_900_000))
            assertFalse(reopened.queueReturn(candidate, "{}", 1_900_000, 1_900_000))
            assertFalse(reopened.deferReturn(candidate, 1_900_000, 1_900_000))
            reopened.observeBoot(2)
            assertTrue(reopened.candidates("mother").isEmpty())
            assertEquals(take, reopened.next("mother"))
        }
        assertEquals(listOf(60_000L,120_000L,240_000L,480_000L,480_000L), (1..5).map(LocalStore::returnBackoff))
    }

    @Test fun staleCandidateCannotDeleteDeferOrQueueForDifferentMonotonicGeneration() {
        setup().use { store ->
            store.observe(1, true, 100_000, 100_000); store.observe(1, false, 100_000, 100_000)
            val candidate = store.candidates("mother").single()
            val stale = candidate.copy(elapsedDue = candidate.elapsedDue - 1)
            store.abandon(stale)
            assertEquals(candidate, store.candidates("mother").single())
            assertFalse(store.deferReturn(stale, 130_000, 130_000))
            assertFalse(store.queueReturn(stale, "{}", 130_000, 130_000))
            store.remove("mother", "Hyundai")
            assertFalse(store.queueReturn(candidate, "{}", 130_000, 130_000))
        }
    }
}
