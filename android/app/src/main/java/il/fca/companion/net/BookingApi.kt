package il.fca.companion.net

import java.net.URLEncoder
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

internal data class BookingRange(val start: LocalDate, val endExclusive: LocalDate) {
    init { require(ChronoUnit.DAYS.between(start, endExclusive) in 1L..42L) }
    operator fun contains(date: LocalDate) = !date.isBefore(start) && date.isBefore(endExclusive)
}

internal data class BookingReservation(val ref: String, val ownerName: String, val memberRef: String,
    val start: LocalDateTime, val end: LocalDateTime, val isMine: Boolean,
    val vehicleRef: String?, val vehicleName: String?, val category: VehicleCategory?)

internal interface BookingGateway {
    suspend fun reservations(owner: String, range: BookingRange): List<BookingReservation>
    suspend fun reservations(owner: String, query: BookingQuery): List<BookingReservation> {
        // Compatibility for existing unfiltered test gateways; never silently discard filters.
        require(query.filters == BookingFilters())
        return reservations(owner, query.grid)
    }
    suspend fun create(owner: String, change: BookingChange): BookingReservation = error("Mutation unsupported")
    suspend fun update(owner: String, ref: String, change: BookingChange): BookingReservation = error("Mutation unsupported")
    suspend fun cancel(owner: String, ref: String): Unit = error("Mutation unsupported")
}

internal data class BookingChange(val start: LocalDateTime, val end: LocalDateTime,
    val vehicleRef: String? = null, val includeVehicle: Boolean = false) {
    fun json(): JSONObject {
        require(end > start)
        return JSONObject().put("start_time", start.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME))
            .put("end_time", end.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME)).also {
                if (includeVehicle) it.put("vehicle_ref", vehicleRef?.also { ref -> UUID.fromString(ref) } ?: JSONObject.NULL)
            }
    }
}

internal class BookingApi private constructor(
    private val read: (String, String) -> String,
    private val write: (String, String, String, JSONObject) -> String
) : BookingGateway {
    constructor(api: FcaApi) : this({ owner, path -> api.call(owner, path) }, api::booking)
    internal constructor(write: (String, String, String, JSONObject) -> String) : this(
        { _, _ -> error("Read unsupported") }, write)
    override suspend fun reservations(owner: String, range: BookingRange) = withContext(Dispatchers.IO) {
        parse(read(owner, path(range)))
    }
    override suspend fun reservations(owner: String, query: BookingQuery) = withContext(Dispatchers.IO) {
        parse(read(owner, path(query)))
    }
    override suspend fun create(owner: String, change: BookingChange) = withContext(Dispatchers.IO) {
        parseOne(JSONObject(write(owner, "/api/reservations", "POST", change.json()))).also { require(it.isMine) }
    }
    override suspend fun update(owner: String, ref: String, change: BookingChange) = withContext(Dispatchers.IO) {
        uuid(ref)
        parseOne(JSONObject(write(owner, "/api/reservations", "PATCH", change.json().put("reservation_ref", ref))))
            .also { require(it.ref == ref && it.isMine) }
    }
    override suspend fun cancel(owner: String, ref: String) = withContext(Dispatchers.IO) {
        uuid(ref)
        val result = JSONObject(write(owner, "/api/reservations/cancel", "POST", JSONObject().put("reservation_ref", ref)))
        require(result.get("cancelled") == true)
    }
    companion object {
        internal fun path(range: BookingRange): String {
            return path(BookingQuery(range))
        }
        internal fun path(query: BookingQuery): String {
            val interval = requireNotNull(query.effective)
            val format = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss")
            return "/api/reservations?" + linkedMapOf(
                "range_start" to interval.start.format(format),
                "range_end" to interval.end.format(format), "scope" to "all"
            ).apply {
                query.filters.vehicleRef?.let { put("vehicle_ref", uuid(it)) }
                query.filters.memberRef?.let { put("member_ref", uuid(it)) }
            }.entries.joinToString("&") { it.key + "=" + URLEncoder.encode(it.value, "UTF-8") }
        }
        internal fun time(value: String): LocalDateTime {
            // Explicit offsets must be converted, not discarded. Local values remain wall-clock values.
            return try {
                OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.of("Asia/Jerusalem")).toLocalDateTime()
            } catch (_: DateTimeParseException) { LocalDateTime.parse(value) }
        }
        private fun text(obj: JSONObject, key: String) = obj.get(key) as? String ?: error("Invalid response")
        private fun nullableText(obj: JSONObject, key: String): String? {
            require(obj.has(key))
            return if (obj.isNull(key)) null else text(obj, key)
        }
        private fun uuid(value: String) = value.also { require(UUID.fromString(it).toString() == it) }
        internal fun parse(body: String): List<BookingReservation> {
            val array = JSONArray(body)
            return (0 until array.length()).map { index ->
                parseOne(array.getJSONObject(index))
            }.also { rows -> require(rows.map { it.ref }.distinct().size == rows.size) }
        }
        internal fun parseOne(obj: JSONObject): BookingReservation {
                val start = time(text(obj, "start_time"))
                val end = time(text(obj, "end_time"))
                require(end.isAfter(start))
                val vehicle = nullableText(obj, "vehicle_ref")?.let(::uuid)
                val name = nullableText(obj, "vehicle_display_name")
                val category = nullableText(obj, "vehicle_category")?.let { wire ->
                    VehicleCategory.entries.singleOrNull { it.wire == wire } ?: error("Invalid response")
                }
                require(vehicle != null || (name == null && category == null))
                return BookingReservation(uuid(text(obj, "reservation_ref")), text(obj, "owner_name"),
                    uuid(text(obj, "member_ref")), start, end,
                    obj.get("is_mine") as? Boolean ?: error("Invalid response"), vehicle, name, category)
        }
    }
}
