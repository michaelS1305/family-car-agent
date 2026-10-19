package il.fca.companion.net

import java.time.LocalDate
import java.time.OffsetDateTime
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

data class VehicleDetail(val vehicle: ManagedVehicle, val inUse: Boolean) {
    val status get() = if (vehicle.readOnly) "לא פעיל" else if (inUse) "בשימוש" else "פנוי"
}
data class VehicleMaintenance(val ref: String, val description: String, val date: LocalDate, val completed: Boolean = false)
interface VehicleDetailsGateway {
    suspend fun detail(owner: String, ref: String): VehicleDetail
    suspend fun maintenance(owner: String, ref: String): List<VehicleMaintenance>
    suspend fun canManage(owner: String): Boolean
    suspend fun manufacturers(owner: String): List<Manufacturer>
    suspend fun edit(owner: String, ref: String, draft: VehicleDraft)
    suspend fun retire(owner: String, ref: String)
    suspend fun addMaintenance(owner: String, ref: String, description: String, date: LocalDate)
    suspend fun updateMaintenance(owner: String, ref: String, item: String, description: String, date: LocalDate)
    suspend fun deleteMaintenance(owner: String, ref: String, item: String)
    suspend fun completeMaintenance(owner: String, ref: String, item: String)
}
class VehicleDetailsApi(private val api: FcaApi) : VehicleDetailsGateway {
    private val vehicles = VehiclesApi(api)
    private fun path(ref: String) = "/api/vehicles/${UUID.fromString(ref)}"
    override suspend fun detail(owner: String, ref: String) = withContext(Dispatchers.IO) {
        val body = JSONObject(api.call(owner, path(ref)))
        VehicleDetail(VehiclesApi.parseVehicle(body), body.get("in_use") as Boolean).also {
            require(it.vehicle.ref == ref)
        }
    }
    override suspend fun maintenance(owner: String, ref: String) = withContext(Dispatchers.IO) {
        parseMaintenance(api.call(owner, path(ref) + "/maintenance"))
    }
    override suspend fun canManage(owner: String) = vehicles.canCreate(owner)
    override suspend fun manufacturers(owner: String) = vehicles.manufacturers(owner)
    override suspend fun edit(owner: String, ref: String, draft: VehicleDraft) { withContext(Dispatchers.IO) {
        api.call(owner, path(ref), "PUT", editBody(draft))
    } }
    override suspend fun retire(owner: String, ref: String) { withContext(Dispatchers.IO) {
        api.call(owner, path(ref) + "/retire", "POST")
    } }
    override suspend fun addMaintenance(owner: String, ref: String, description: String, date: LocalDate) {
        withContext(Dispatchers.IO) {
            api.call(owner, path(ref) + "/maintenance", "POST",
                JSONObject().put("description", description).put("scheduled_date", date.toString()))
        }
    }
    override suspend fun updateMaintenance(owner: String, ref: String, item: String, description: String, date: LocalDate) {
        withContext(Dispatchers.IO) {
            api.call(owner, path(ref) + "/maintenance/${UUID.fromString(item)}", "PUT",
                JSONObject().put("description", description).put("scheduled_date", date.toString()))
        }
    }
    override suspend fun deleteMaintenance(owner: String, ref: String, item: String) {
        withContext(Dispatchers.IO) {
            api.call(owner, path(ref) + "/maintenance/${UUID.fromString(item)}", "DELETE")
        }
    }
    override suspend fun completeMaintenance(owner: String, ref: String, item: String) {
        withContext(Dispatchers.IO) {
            api.call(owner, path(ref) + "/maintenance/${UUID.fromString(item)}/complete", "POST")
        }
    }
    companion object {
        internal fun editBody(draft: VehicleDraft): JSONObject {
            require(draft.valid)
            return JSONObject().put("display_name", draft.name).put("category", draft.category!!.wire)
                .put("manufacturer_id", draft.manufacturer!!.id).put("model", draft.model).put("license_plate", draft.plate)
        }
        internal fun parseMaintenance(body: String): List<VehicleMaintenance> {
            val rows = JSONArray(body)
            return (0 until rows.length()).map { i ->
                val row = rows.getJSONObject(i)
                OffsetDateTime.parse(row.getString("created_at"))
                VehicleMaintenance(UUID.fromString(row.getString("maintenance_ref")).toString(),
                    row.getString("description"), LocalDate.parse(row.getString("scheduled_date")),
                    if (row.has("completed")) row.get("completed") as Boolean else false)
            }.also { require(it.map(VehicleMaintenance::ref).distinct().size == it.size) }
        }
    }
}
