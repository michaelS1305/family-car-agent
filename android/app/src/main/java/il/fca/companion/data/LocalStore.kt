package il.fca.companion.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import java.time.Instant
import java.util.UUID

data class Installation(val request: String, val device: String?, val next: Long)
data class Association(val vehicle: String, val address: String, val companionId: Int, val connected: Boolean)
data class PendingTake(val id: String, val owner: String, val device: String, val vehicle: String,
                       val sequence: Long, val occurredAt: String)

class LocalStore(context: Context) : SQLiteOpenHelper(context, "fca.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE installations(owner TEXT PRIMARY KEY, request TEXT NOT NULL, device TEXT, next_seq INTEGER NOT NULL DEFAULT 1)")
        db.execSQL("CREATE TABLE associations(owner TEXT NOT NULL, vehicle TEXT NOT NULL, address TEXT NOT NULL, companion_id INTEGER NOT NULL, connected INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,vehicle), UNIQUE(owner,address))")
        db.execSQL("CREATE TABLE outbox(id TEXT PRIMARY KEY, owner TEXT NOT NULL, device TEXT NOT NULL, vehicle TEXT NOT NULL, seq INTEGER NOT NULL, occurred TEXT NOT NULL, result TEXT, UNIQUE(device,seq))")
        db.execSQL("CREATE TABLE diagnostics(id INTEGER PRIMARY KEY, message TEXT NOT NULL)")
        db.execSQL("CREATE TABLE active_account(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL)")
        db.execSQL("CREATE TABLE boot_state(id INTEGER PRIMARY KEY CHECK(id=1), boot INTEGER NOT NULL)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = error("Explicit migration required")
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
            db.execSQL("UPDATE associations SET connected=0")
            db.execSQL("INSERT OR REPLACE INTO boot_state VALUES(1,?)", arrayOf(boot))
        }
    }
    fun activate(owner: String?) = transaction { db ->
        db.execSQL("DELETE FROM active_account")
        // A fresh login requires a new physical connection; never synthesize TAKE.
        db.execSQL("UPDATE associations SET connected=0")
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
    fun observe(companionId: Int, connected: Boolean): Boolean = transaction { db ->
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
        if (!connected) return@transaction false // Diagnostic only; never RETURN.
        check(installation.second < Long.MAX_VALUE)
        db.execSQL("INSERT INTO outbox(id,owner,device,vehicle,seq,occurred) VALUES(?,?,?,?,?,?)",
            arrayOf(UUID.randomUUID().toString(), owner, installation.first, association.first,
                installation.second, Instant.now().toString()))
        db.execSQL("UPDATE installations SET next_seq=next_seq+1 WHERE owner=?", arrayOf(owner))
        true
    }
    fun next(owner: String): PendingTake? = readableDatabase.rawQuery(
        "SELECT id,owner,device,vehicle,seq,occurred FROM outbox WHERE owner=? AND result IS NULL ORDER BY seq LIMIT 1", arrayOf(owner)).use {
        if (!it.moveToFirst()) null else PendingTake(it.getString(0), it.getString(1), it.getString(2),
            it.getString(3), it.getLong(4), it.getString(5))
    }
    fun finish(id: String, result: String) = transaction { db ->
        db.execSQL("UPDATE outbox SET result=? WHERE id=?", arrayOf(result, id))
        db.execSQL("DELETE FROM outbox WHERE result IS NOT NULL AND id NOT IN (SELECT id FROM outbox WHERE result IS NOT NULL ORDER BY rowid DESC LIMIT 30)")
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
