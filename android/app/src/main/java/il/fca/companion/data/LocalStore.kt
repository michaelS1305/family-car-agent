package il.fca.companion.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.time.Instant
import java.util.UUID

data class Installation(val request: String, val device: String?, val next: Long)
data class Association(val vehicle: String, val address: String, val companionId: Int, val connected: Boolean)
data class PendingTake(val id: String, val owner: String, val device: String, val vehicle: String,
                       val sequence: Long, val occurredAt: String, val type: String = "take",
                       val evidence: String? = null)
data class ReturnCandidate(val owner: String, val vehicle: String, val take: String, val due: Long, val elapsedDue: Long)

class LocalStore(context: Context) : SQLiteOpenHelper(context, "fca.db", null, 2) {
    companion object { const val RETURN_GRACE_MS = 60_000L }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE installations(owner TEXT PRIMARY KEY, request TEXT NOT NULL, device TEXT, next_seq INTEGER NOT NULL DEFAULT 1)")
        db.execSQL("CREATE TABLE associations(owner TEXT NOT NULL, vehicle TEXT NOT NULL, address TEXT NOT NULL, companion_id INTEGER NOT NULL, connected INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,vehicle), UNIQUE(owner,address))")
        db.execSQL("CREATE TABLE outbox(id TEXT PRIMARY KEY, owner TEXT NOT NULL, device TEXT NOT NULL, vehicle TEXT NOT NULL, seq INTEGER NOT NULL, occurred TEXT NOT NULL, result TEXT, UNIQUE(device,seq))")
        db.execSQL("CREATE TABLE diagnostics(id INTEGER PRIMARY KEY, message TEXT NOT NULL)")
        db.execSQL("CREATE TABLE active_account(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL)")
        db.execSQL("CREATE TABLE boot_state(id INTEGER PRIMARY KEY CHECK(id=1), boot INTEGER NOT NULL)")
        upgradeReturn(db)
    }
    private fun upgradeReturn(db: SQLiteDatabase) {
        db.execSQL("ALTER TABLE outbox ADD COLUMN type TEXT NOT NULL DEFAULT 'take'")
        db.execSQL("ALTER TABLE outbox ADD COLUMN evidence TEXT")
        db.execSQL("ALTER TABLE associations ADD COLUMN take_id TEXT")
        db.execSQL("ALTER TABLE associations ADD COLUMN return_due INTEGER")
        db.execSQL("ALTER TABLE associations ADD COLUMN return_elapsed INTEGER")
        db.execSQL("CREATE TABLE return_home(owner TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL, saved INTEGER NOT NULL)")
        // Older installations have no proven acquisition link. Never guess one
        // from a receipt; a real reconnect creates a safe TAKE alias on server.
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        check(oldVersion == 1 && newVersion == 2)
        upgradeReturn(db)
    }
    private fun <T> transaction(action: (SQLiteDatabase) -> T): T {
        val db = writableDatabase
        db.beginTransaction()
        try { val value = action(db); db.setTransactionSuccessful(); return value }
        finally { db.endTransaction() }
    }
    fun activeOwner(): String? = readableDatabase.rawQuery("SELECT owner FROM active_account WHERE id=1", null).use {
        if (it.moveToFirst()) it.getString(0) else null
    }
    fun observeBoot(boot: Int) = transaction { db ->
        val previous = db.rawQuery("SELECT boot FROM boot_state WHERE id=1", null).use {
            if (it.moveToFirst()) it.getInt(0) else null
        }
        if (previous != boot) {
            // A reboot breaks physical connections, unlike an app-process restart.
            // Pending immutable events and sequence counters must remain untouched.
            db.execSQL("UPDATE associations SET connected=0,take_id=NULL,return_due=NULL")
            db.execSQL("INSERT OR REPLACE INTO boot_state VALUES(1,?)", arrayOf(boot))
        }
    }
    fun activate(owner: String?) = transaction { db ->
        db.execSQL("DELETE FROM active_account")
        // A fresh login requires a new physical connection; never synthesize TAKE.
        db.execSQL("UPDATE associations SET connected=0,take_id=NULL,return_due=NULL")
        db.execSQL("DELETE FROM return_home")
        if (owner != null) db.execSQL("INSERT INTO active_account VALUES(1,?)", arrayOf(owner))
    }
    fun installation(owner: String): Installation = transaction { db ->
        db.execSQL("INSERT OR IGNORE INTO installations(owner,request) VALUES(?,?)", arrayOf(owner, UUID.randomUUID().toString()))
        db.rawQuery("SELECT request,device,next_seq FROM installations WHERE owner=?", arrayOf(owner)).use {
            check(it.moveToFirst()); Installation(it.getString(0), it.getString(1), it.getLong(2))
        }
    }
    fun registered(owner: String, ref: String) {
        UUID.fromString(ref)
        writableDatabase.execSQL("UPDATE installations SET device=? WHERE owner=? AND (device IS NULL OR device=?)", arrayOf(ref, owner, ref))
    }
    fun associate(owner: String, vehicle: String, address: String, id: Int) = transaction { db ->
        // Never silently repurpose Bluetooth identity from one vehicle to another.
        db.execSQL("INSERT INTO associations(owner,vehicle,address,companion_id) VALUES(?,?,?,?) " +
            "ON CONFLICT(owner,vehicle) DO UPDATE SET address=excluded.address,companion_id=excluded.companion_id," +
            "take_id=CASE WHEN associations.companion_id=excluded.companion_id THEN associations.take_id ELSE NULL END," +
            "return_due=CASE WHEN associations.companion_id=excluded.companion_id THEN associations.return_due ELSE NULL END," +
            "connected=CASE WHEN associations.companion_id=excluded.companion_id THEN associations.connected ELSE 0 END",
            arrayOf(owner, vehicle, address, id))
    }
    fun remove(owner: String, vehicle: String) {
        writableDatabase.delete("associations", "owner=? AND vehicle=?", arrayOf(owner, vehicle))
    }
    fun associations(owner: String): List<Association> = readableDatabase.rawQuery(
        "SELECT vehicle,address,companion_id,connected FROM associations WHERE owner=? ORDER BY vehicle", arrayOf(owner)).use {
        buildList { while (it.moveToNext()) add(Association(it.getString(0), it.getString(1), it.getInt(2), it.getInt(3) != 0)) }
    }
    fun observe(companionId: Int, connected: Boolean, now: Long = System.currentTimeMillis(),
                elapsed: Long = android.os.SystemClock.elapsedRealtime()): Boolean = transaction { db ->
        val owner = activeOwner() ?: return@transaction false
        val installation = db.rawQuery("SELECT device,next_seq FROM installations WHERE owner=?", arrayOf(owner)).use {
            if (!it.moveToFirst() || it.isNull(0)) return@transaction false
            it.getString(0) to it.getLong(1)
        }
        val association = db.rawQuery("SELECT vehicle,connected FROM associations WHERE owner=? AND companion_id=?",
            arrayOf(owner, companionId.toString())).use {
            if (!it.moveToFirst()) return@transaction false
            it.getString(0) to (it.getInt(1) != 0)
        }
        if (association.second == connected) return@transaction false
        db.execSQL("UPDATE associations SET connected=? WHERE owner=? AND companion_id=?",
            arrayOf(if (connected) 1 else 0, owner, companionId))
        if (!connected) {
            db.execSQL("UPDATE associations SET return_due=?,return_elapsed=? WHERE owner=? AND vehicle=? AND take_id IS NOT NULL",
                arrayOf(now + RETURN_GRACE_MS, elapsed + RETURN_GRACE_MS, owner, association.first))
            diagnostic(if (candidates(owner).any { it.vehicle == association.first }) "return_grace_started" else "return_missing_take")
            return@transaction false
        }
        if (candidates(owner).any { it.vehicle == association.first }) diagnostic("return_cancelled_reconnected")
        check(installation.second < Long.MAX_VALUE)
        val takeId = UUID.randomUUID().toString()
        db.execSQL("INSERT INTO outbox(id,owner,device,vehicle,seq,occurred) VALUES(?,?,?,?,?,?)",
            arrayOf(takeId, owner, installation.first, association.first,
                installation.second, Instant.now().toString()))
        db.execSQL("UPDATE associations SET take_id=?,return_due=NULL WHERE owner=? AND vehicle=?",
            arrayOf(takeId, owner, association.first))
        db.execSQL("UPDATE installations SET next_seq=next_seq+1 WHERE owner=?", arrayOf(owner))
        true
    }
    fun next(owner: String): PendingTake? = readableDatabase.rawQuery(
        "SELECT id,owner,device,vehicle,seq,occurred,type,evidence FROM outbox WHERE owner=? AND result IS NULL ORDER BY seq LIMIT 1", arrayOf(owner)).use {
        if (!it.moveToFirst()) null else PendingTake(it.getString(0), it.getString(1), it.getString(2),
            it.getString(3), it.getLong(4), it.getString(5), it.getString(6), it.getString(7))
    }
    fun finish(id: String, result: String) = transaction { db ->
        db.execSQL("UPDATE outbox SET result=?,evidence=NULL WHERE id=?", arrayOf(result, id))
        db.execSQL("DELETE FROM outbox WHERE result IS NOT NULL AND id NOT IN (SELECT id FROM outbox WHERE result IS NOT NULL ORDER BY rowid DESC LIMIT 30)")
    }
    fun saveHome(owner: String, latitude: Double, longitude: Double) {
        check(latitude.isFinite() && longitude.isFinite() && latitude in -90.0..90.0 && longitude in -180.0..180.0)
        writableDatabase.execSQL("INSERT OR REPLACE INTO return_home VALUES(?,?,?,?)",
            arrayOf(owner, latitude, longitude, System.currentTimeMillis()))
    }
    fun clearHome(owner: String) { writableDatabase.delete("return_home", "owner=?", arrayOf(owner)) }
    fun home(owner: String, now: Long = System.currentTimeMillis()): Pair<Double, Double>? = readableDatabase.rawQuery(
        "SELECT latitude,longitude,saved FROM return_home WHERE owner=?", arrayOf(owner)).use {
        if (!it.moveToFirst() || now - it.getLong(2) !in 0..86_400_000L) null else it.getDouble(0) to it.getDouble(1)
    }
    fun candidates(owner: String): List<ReturnCandidate> = readableDatabase.rawQuery(
        "SELECT vehicle,take_id,return_due,return_elapsed FROM associations WHERE owner=? AND return_due IS NOT NULL AND take_id IS NOT NULL",
        arrayOf(owner)).use { buildList { while (it.moveToNext()) add(ReturnCandidate(owner, it.getString(0), it.getString(1), it.getLong(2), it.getLong(3))) } }
    fun abandon(candidate: ReturnCandidate) {
        writableDatabase.execSQL("UPDATE associations SET return_due=NULL WHERE owner=? AND vehicle=? AND take_id=? AND return_due=?",
            arrayOf(candidate.owner, candidate.vehicle, candidate.take, candidate.due))
    }
    fun queueReturn(candidate: ReturnCandidate, evidence: String, now: Long = System.currentTimeMillis(),
                    elapsed: Long = android.os.SystemClock.elapsedRealtime()): Boolean = transaction { db ->
        if (activeOwner() != candidate.owner || now < candidate.due || elapsed < candidate.elapsedDue) return@transaction false
        val valid = db.rawQuery("SELECT 1 FROM associations WHERE owner=? AND vehicle=? AND take_id=? AND return_due=? AND connected=0",
            arrayOf(candidate.owner, candidate.vehicle, candidate.take, candidate.due.toString())).use { it.moveToFirst() }
        if (!valid) return@transaction false
        val installation = installation(candidate.owner)
        val device = installation.device ?: return@transaction false
        check(installation.next < Long.MAX_VALUE)
        db.execSQL("INSERT INTO outbox(id,owner,device,vehicle,seq,occurred,type,evidence) VALUES(?,?,?,?,?,?,'return',?)",
            arrayOf(UUID.randomUUID().toString(), candidate.owner, device, candidate.vehicle, installation.next,
                Instant.ofEpochMilli(now).toString(), evidence))
        db.execSQL("UPDATE installations SET next_seq=next_seq+1 WHERE owner=?", arrayOf(candidate.owner))
        db.execSQL("UPDATE associations SET take_id=NULL,return_due=NULL WHERE owner=? AND vehicle=?", arrayOf(candidate.owner, candidate.vehicle))
        true
    }
    fun pending(owner: String): Long = readableDatabase.rawQuery(
        "SELECT count(*) FROM outbox WHERE owner=? AND result IS NULL", arrayOf(owner)).use { it.moveToFirst(); it.getLong(0) }
    // Callers supply only fixed categories/status numbers, never exceptions/HTTP payloads.
    fun diagnostic(category: String) = transaction { db ->
        db.execSQL("INSERT INTO diagnostics(message) VALUES(?)", arrayOf(Instant.now().toString() + " " + category))
        db.execSQL("DELETE FROM diagnostics WHERE id NOT IN (SELECT id FROM diagnostics ORDER BY id DESC LIMIT 30)")
    }
    fun diagnostics(): String = readableDatabase.rawQuery("SELECT message FROM diagnostics ORDER BY id DESC LIMIT 15", null).use {
        buildList { while (it.moveToNext()) add(it.getString(0)) }.joinToString("\n")
    }
}
