package il.fca.companion.net

import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

enum class FamilyRole(val wire: String?, val label: String) {
    NONE(null, "ללא תפקיד"), PARENT("parent", "הורה"), CHILD("child", "ילד/ילדה")
}
data class FamilyMember(val ref: String, val name: String, val role: FamilyRole, val admin: Boolean)
data class FamilyProfile(val name: String, val address: String, val code: String,
                         val canManage: Boolean, val members: List<FamilyMember>)

interface FamilyGateway {
    suspend fun profile(owner: String): FamilyProfile
    suspend fun role(owner: String, ref: String, role: FamilyRole): FamilyMember
    suspend fun resolve(owner: String, draft: String): ResolvedAddress
    suspend fun address(owner: String, candidate: ResolvedAddress): String
    suspend fun regenerate(owner: String): String
}

class FamilyApi(private val api: FcaApi) : FamilyGateway {
    private suspend fun request(owner: String, path: String, method: String = "GET", body: JSONObject? = null) =
        withContext(Dispatchers.IO) { JSONObject(api.call(owner, path, method, body)) }
    override suspend fun profile(owner: String) = parseProfile(request(owner, "/api/family"))
    override suspend fun role(owner: String, ref: String, role: FamilyRole): FamilyMember =
        parseMember(request(owner, "/api/family/members/${UUID.fromString(ref)}/role", "PATCH",
            JSONObject().put("role", role.wire ?: JSONObject.NULL))).also { require(it.ref == ref) }
    override suspend fun resolve(owner: String, draft: String) =
        AddressVerification.resolve(draft, creatingFamily = false) { path, body -> request(owner, path, "POST", body) }
    override suspend fun address(owner: String, candidate: ResolvedAddress) =
        request(owner, "/api/family/address", "PATCH", JSONObject().put("resolution_token", candidate.token))
            .getString("home_address")
    override suspend fun regenerate(owner: String) =
        code(request(owner, "/api/family/code/regenerate", "POST", JSONObject()))
    companion object {
        internal fun parseMember(row: JSONObject): FamilyMember {
            require(row.has("role"))
            val role = if (row.isNull("role")) FamilyRole.NONE else
                FamilyRole.entries.single { it.wire == row.getString("role") }
            return FamilyMember(UUID.fromString(row.getString("member_ref")).toString(), row.getString("name"),
                role, row.get("is_family_admin") as Boolean)
        }
        internal fun code(row: JSONObject) = row.getString("family_code").also { require(it.matches(Regex("[a-z0-9]{6}"))) }
        internal fun parseProfile(row: JSONObject): FamilyProfile {
            val array = row.getJSONArray("members")
            val members = (0 until array.length()).map { parseMember(array.getJSONObject(it)) }
            require(members.map { it.ref }.distinct().size == members.size)
            return FamilyProfile(row.getString("name"), row.getString("home_address"), code(row),
                row.get("can_edit_roles") as Boolean, members)
        }
    }
}
