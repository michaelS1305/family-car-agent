package il.fca.companion.detector

import android.Manifest
import android.companion.CompanionDeviceManager
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.CancellationSignal
import il.fca.companion.data.Association
import il.fca.companion.data.LocalStore
import il.fca.companion.data.ReturnCandidate
import org.json.JSONObject
import java.time.Instant

/** Platform adapter and unchanged RETURN qualification, shared by the FGS only. */
internal class ReturnExecution(private val context: Context, private val store: LocalStore,
                               private val deliver: () -> Unit) {
    private fun log(value: String) = ReturnWorker.diagnostic(store::diagnostic, value)
    fun invalid(candidate: ReturnCandidate): String? {
        if (store.activeOwner() != candidate.owner || candidate !in store.candidates(candidate.owner)) return "candidate_invalid"
        val local = store.associations(candidate.owner).singleOrNull { it.vehicle == candidate.vehicle }
            ?: return "candidate_invalid"
        if (local.connected || store.installation(candidate.owner).device == null) return "candidate_invalid"
        val system = context.getSystemService(CompanionDeviceManager::class.java).myAssociations
        if (!matches(local, system.map { it.id to it.deviceMacAddress?.toString() })) return "association_missing"
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
            return "fine_permission_missing"
        if (context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED)
            return "background_permission_missing"
        if (!context.getSystemService(LocationManager::class.java).isLocationEnabled) return "location_disabled"
        return null
    }

    fun acquisition(): ReturnLocationAcquisition {
        val manager = context.getSystemService(LocationManager::class.java)
        fun provider(source: ReturnLocationAcquisition.Source) = when (source) {
            ReturnLocationAcquisition.Source.GPS -> LocationManager.GPS_PROVIDER
            ReturnLocationAcquisition.Source.NETWORK -> LocationManager.NETWORK_PROVIDER
        }
        return ReturnLocationAcquisition(object : ReturnLocationAcquisition.Providers {
            override fun available(source: ReturnLocationAcquisition.Source) = manager.hasProvider(provider(source))
            override fun enabled(source: ReturnLocationAcquisition.Source) = manager.isProviderEnabled(provider(source))
            override fun cached(source: ReturnLocationAcquisition.Source): Location? {
                if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                    throw SecurityException()
                return manager.getLastKnownLocation(provider(source))
            }
            override fun request(source: ReturnLocationAcquisition.Source, cancellation: CancellationSignal,
                                 started: () -> Unit, callback: (Location?) -> Unit) {
                if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                    throw SecurityException()
                started()
                manager.getCurrentLocation(provider(source), cancellation, context.mainExecutor, callback)
            }
        }, store::diagnostic)
    }

    fun decide(candidate: ReturnCandidate, result: ReturnWorker.LocationCheck): String {
        val home = store.homeCheck(candidate.owner)
        val fix = result.fix
        val reason = result.reason ?: home.reason ?: ReturnWorker.fixFailure(fix)
            ?: ReturnWorker.homeRadiusFailure(fix!!, home.home!!)
        if (reason != null) {
            log("return_home_check_failed_$reason")
            return reason
        }
        val body = JSONObject().put("take_event_id", candidate.take).put("latitude", fix!!.latitude)
            .put("longitude", fix.longitude).put("accuracy_m", fix.accuracy.toDouble())
            .put("location_at", Instant.ofEpochMilli(fix.time).toString())
        if (!store.queueReturn(candidate, body.toString())) return "candidate_invalid"
        log("return_queued")
        deliver()
        return "queued"
    }

    companion object {
        fun matches(local: Association, system: List<Pair<Int, String?>>): Boolean =
            system.any { it.first == local.companionId && it.second != null && it.second.equals(local.address, true) }
    }
}
