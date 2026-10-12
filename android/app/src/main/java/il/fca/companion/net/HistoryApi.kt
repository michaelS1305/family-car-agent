package il.fca.companion.net

import java.net.URLEncoder
import java.time.OffsetDateTime
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** Shared vehicle response; no History-specific category or guessed illustration metadata. */
data class FamilyVehicle(val ref: String, val name: String, val inUse: Boolean,
    val driver: String?, val startedAt: Instant?)
data class HistoryMember(val ref: String, val name: String)
data class HistoryUsage(val sessionRef: String, val vehicleRef: String, val memberRef: String,
    val vehicleName: String, val name: String, val startedAt: Instant, val endedAt: Instant)
data class HistoryPage(val rows: List<HistoryUsage>, val hasMore: Boolean, val nextCursor: String?)
data class HistoryFilters(val vehicleRef: String? = null, val memberRef: String? = null,
    val from: OffsetDateTime? = null, val to: OffsetDateTime? = null) {
    val valid get() = from == null || to == null || !from.toInstant().isAfter(to.toInstant())
    val empty get() = this == HistoryFilters()
}
interface HistoryGateway {
    suspend fun page(owner: String, filters: HistoryFilters, cursor: String?): HistoryPage
    suspend fun vehicles(owner: String): List<FamilyVehicle>
    suspend fun members(owner: String): List<HistoryMember>
}

class HistoryApi(private val api: FcaApi) : HistoryGateway {
    override suspend fun page(owner: String, filters: HistoryFilters, cursor: String?) = withContext(Dispatchers.IO) {
        parsePage(api.call(owner, path(filters, cursor)))
    }
    override suspend fun vehicles(owner: String) = withContext(Dispatchers.IO) {
        parseVehicles(api.call(owner, "/api/vehicles"))
    }
    override suspend fun members(owner: String) = withContext(Dispatchers.IO) {
        parseMembers(api.call(owner, "/api/family"))
    }
    companion object {
        const val PAGE_SIZE = 50
        internal fun path(filters: HistoryFilters, cursor: String?): String {
            require(filters.valid)
            val args = linkedMapOf("limit" to PAGE_SIZE.toString())
            cursor?.let { args["cursor"] = uuid(it) }
            filters.vehicleRef?.let { args["vehicle_ref"] = uuid(it) }
            filters.memberRef?.let { args["member_ref"] = uuid(it) }
            filters.from?.let { args["from_datetime"] = it.toString() }
            filters.to?.let { args["to_datetime"] = it.toString() }
            return "/api/car/history?" + args.entries.joinToString("&") {
                it.key + "=" + URLEncoder.encode(it.value, "UTF-8")
            }
        }
        private fun uuid(value: String) = value.also { require(UUID.fromString(it).toString() == it) }
        private fun text(obj: JSONObject, key: String) = obj.get(key) as? String ?: error("Invalid response")
        private fun nullableText(obj: JSONObject, key: String): String? {
            require(obj.has(key))
            return if (obj.isNull(key)) null else text(obj, key)
        }
        private fun bool(obj: JSONObject, key: String) = obj.get(key) as? Boolean ?: error("Invalid response")
        private fun time(value: String) = OffsetDateTime.parse(value).toInstant()
        internal fun parseVehicles(body: String): List<FamilyVehicle> {
            val array = JSONArray(body)
            return (0 until array.length()).map { index ->
                val obj = array.getJSONObject(index)
                require(obj.has("retired_at") && obj.isNull("retired_at"))
                val used = bool(obj, "in_use")
                val start = nullableText(obj, "started_at")?.let(::time)
                val driver = nullableText(obj, "current_driver")
                require(if (used) start != null && driver != null else start == null && driver == null)
                FamilyVehicle(uuid(text(obj, "vehicle_ref")), text(obj, "display_name"), used, driver, start)
            }.also { require(it.map(FamilyVehicle::ref).distinct().size == it.size) }
        }
        internal fun parseMembers(body: String): List<HistoryMember> {
            val array = JSONObject(body).getJSONArray("members")
            return (0 until array.length()).map { index ->
                val obj = array.getJSONObject(index)
                HistoryMember(uuid(text(obj, "member_ref")), text(obj, "name"))
            }
        }
        internal fun parsePage(body: String): HistoryPage {
            val obj = JSONObject(body)
            val array = obj.getJSONArray("recent_usage")
            require(array.length() <= PAGE_SIZE)
            val rows = (0 until array.length()).map { index ->
                val row = array.getJSONObject(index)
                val start = time(text(row, "started_at"))
                val end = time(text(row, "ended_at"))
                require(!end.isBefore(start))
                HistoryUsage(uuid(text(row, "session_ref")), uuid(text(row, "vehicle_ref")),
                    uuid(text(row, "member_ref")), text(row, "vehicle_name"), text(row, "name"), start, end)
            }
            val more = bool(obj, "has_more")
            val cursor = nullableText(obj, "next_cursor")?.let(::uuid)
            require(if (more) rows.isNotEmpty() && cursor == rows.last().sessionRef else cursor == null)
            return HistoryPage(rows, more, cursor)
        }
    }
}
