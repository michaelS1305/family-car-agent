package il.fca.companion.net

import java.time.Instant
import java.time.OffsetDateTime
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

enum class VehicleCategory(val wire: String, val label: String) {
    HATCHBACK("hatchback", "Hatchback"), SEDAN("sedan", "Sedan"), CROSSOVER("crossover", "Crossover"),
    MINIVAN("minivan", "Minivan"), SUV("suv", "SUV")
}
data class ManagedVehicle(val ref: String, val name: String, val createdAt: Instant,
    val retiredAt: Instant?, val category: VehicleCategory?, val manufacturerId: Int?,
    val manufacturerName: String?, val model: String?, val plate: String?) {
    val readOnly get() = retiredAt != null
}
data class Manufacturer(val id: Int, val name: String)
data class VehicleDraft(val name: String = "", val category: VehicleCategory? = null,
    val manufacturer: Manufacturer? = null, val manufacturerQuery: String = "",
    val model: String = "", val plate: String = "") {
    val valid get() = name.isNotBlank() && category != null && manufacturer != null &&
        manufacturerQuery == manufacturer.name && model.isNotBlank() && plate.isNotBlank()
}
data class VehicleSubmission(val requestId: String, val draft: VehicleDraft) {
    fun json(): JSONObject {
        require(draft.valid && UUID.fromString(requestId).version() == 4)
        return JSONObject().put("request_id", requestId).put("display_name", draft.name)
            .put("category", checkNotNull(draft.category).wire)
            .put("manufacturer_id", checkNotNull(draft.manufacturer).id)
            .put("model", draft.model).put("license_plate", draft.plate)
    }
}
interface VehiclesGateway {
    suspend fun vehicles(owner: String): List<ManagedVehicle>
    suspend fun canCreate(owner: String): Boolean
    suspend fun manufacturers(owner: String): List<Manufacturer>
    suspend fun create(owner: String, submission: VehicleSubmission): ManagedVehicle
}
class VehiclesApi(private val api: FcaApi) : VehiclesGateway {
    override suspend fun vehicles(owner: String) = withContext(Dispatchers.IO) {
        val rows = JSONArray(api.call(owner, "/api/vehicles?include_retired=true"))
        (0 until rows.length()).map { parseVehicle(rows.getJSONObject(it)) }
    }
    override suspend fun canCreate(owner: String) = withContext(Dispatchers.IO) {
        JSONObject(api.call(owner, "/api/family")).get("can_edit_roles") as Boolean
    }
    override suspend fun manufacturers(owner: String) = withContext(Dispatchers.IO) {
        parseManufacturers(api.call(owner, "/api/reference/manufacturers"))
    }
    override suspend fun create(owner: String, submission: VehicleSubmission) = withContext(Dispatchers.IO) {
        parseVehicle(JSONObject(api.call(owner, "/api/vehicles", "POST", submission.json())))
    }
    companion object {
        private fun text(o: JSONObject, key: String): String? {
            require(o.has(key))
            return if (o.isNull(key)) null else o.get(key) as String
        }
        internal fun parseVehicle(o: JSONObject): ManagedVehicle {
            val category = text(o, "category")?.let { value -> VehicleCategory.entries.single { it.wire == value } }
            require(o.has("manufacturer_id"))
            return ManagedVehicle(UUID.fromString(o.getString("vehicle_ref")).toString(),
                o.getString("display_name"), OffsetDateTime.parse(o.getString("created_at")).toInstant(),
                text(o, "retired_at")?.let { OffsetDateTime.parse(it).toInstant() }, category,
                if (o.isNull("manufacturer_id")) null else (o.get("manufacturer_id") as Int).also { require(it > 0) },
                text(o, "manufacturer_name_he"), text(o, "model"), text(o, "license_plate"))
        }
        internal fun parseManufacturers(body: String): List<Manufacturer> {
            val rows = JSONArray(body)
            return (0 until rows.length()).map {
                val row = rows.getJSONObject(it)
                Manufacturer((row.get("id") as Int).also { id -> require(id > 0) }, row.getString("name_he"))
            }.also { require(it.map(Manufacturer::id).distinct().size == it.size) }
        }
    }
}
