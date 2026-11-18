package il.fca.companion

import android.Manifest
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.material3.MaterialTheme
import android.app.AlertDialog
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.companion.*
import android.content.Intent
import android.content.IntentSender
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.view.WindowInsets
import android.widget.*
import il.fca.companion.delivery.DeliveryWorker
import il.fca.companion.detector.DetectorPlatform
import il.fca.companion.net.HttpFailure
import org.json.JSONArray
import org.json.JSONObject
import il.fca.companion.ui.*
import java.util.UUID

class MainActivity : ComponentActivity() {
    companion object { const val VEHICLE_TARGET = "vehicle_target" }
    private val app get() = application as FcaApplication
    private lateinit var content: LinearLayout
    private lateinit var status: TextView
    private var busy by mutableStateOf(false)
    private var target by mutableStateOf<String?>(null)
    private var targetName by mutableStateOf("")
    private var targetRetired by mutableStateOf(false)
    private var targetVerified by mutableStateOf(false)
    private var verificationLoading by mutableStateOf(true)
    private var presentation by mutableStateOf(CompanionPresentation())
    private var productMessage by mutableStateOf<String?>(null)
    private var picker by mutableStateOf<List<BluetoothDevice>?>(null)
    private var productGeneration = 0L
    private var targetOwner: String? = null
    private var productContent = false
    private var vehicles = emptyList<Pair<String, String>>()
    private var displayName = ""
    private val companion get() = getSystemService(CompanionDeviceManager::class.java)

    override fun onCreate(state: Bundle?) {
        applyFcaPlatformTheme(this)
        super.onCreate(state)
        readTarget(intent)
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24) }
        val scroll = ScrollView(this).apply { addView(content) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom); insets
        }
        setContentView(scroll)
        draw()
        app.store.activeOwner()?.let { owner -> task { load(owner) } }
    }
    private fun readTarget(intent: Intent) {
        productGeneration++
        target = intent.getStringExtra(VEHICLE_TARGET)?.let { value -> runCatching { UUID.fromString(value).toString() }.getOrNull() }
        targetOwner = app.store.activeOwner()
        targetName = ""; targetRetired = false; targetVerified = false
        verificationLoading = true
        presentation = CompanionPresentation(); productMessage = null; picker = null
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent); readTarget(intent)
        // A reused singleTask Activity must never retain the previous vehicle.
        if (target == null) { finish(); return }
        draw()
        app.store.activeOwner()?.let { owner -> task { load(owner) } }
    }
    override fun onResume() {
        super.onResume()
        if (target != null && (targetOwner == null || targetOwner != app.store.activeOwner() || targetOwner != app.auth.owner())) {
            productGeneration++; targetVerified = false; picker = null; finish()
        }
    }
    private fun label(text: String) { content.addView(TextView(this).apply { this.text = text; textSize = 16f }) }
    private fun button(text: String, action: () -> Unit) {
        content.addView(Button(this).apply { this.text = text; isEnabled = !busy; setOnClickListener { action() } })
    }
    private fun draw() {
        if (target != null) {
            if (!productContent) {
                productContent = true
                setContent {
                    FcaTheme {
                        CompanionScreen(targetName, presentation, busy, targetVerified, targetRetired, productMessage, verificationLoading,
                            back = { finish() }, refresh = { app.store.activeOwner()?.let { owner -> task { load(owner) } } },
                            register = { app.store.activeOwner()?.let { owner -> task {
                                if (!targetVerified || targetRetired) return@task
                                register(owner)
                            } } },
                            bluetooth = {
                                val owner = app.store.activeOwner()
                                val vehicle = target
                                if (owner != null && vehicle != null && targetVerified && !targetRetired) {
                                    if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)
                                        requestPermissions(arrayOf(Manifest.permission.BLUETOOTH_CONNECT), 11)
                                    else choosePaired(owner, vehicle)
                                }
                            }, permissions = ::locationPermissions)
                        picker?.let { devices ->
                            val owner = app.store.activeOwner()
                            val vehicle = target
                            val address = if (owner != null) app.store.associations(owner).find { it.vehicle == vehicle }?.address else null
                            BluetoothPicker(devices.map { BluetoothChoice(runCatching { it.name }.getOrNull() ?: "Bluetooth", it.address == address) },
                                choose = { index ->
                                    picker = null
                                    if (owner != null && vehicle != null && targetVerified && !targetRetired) associate(owner, vehicle, devices[index])
                                }, close = { picker = null })
                        }
                    }
                }
            }
            return
        }
        content.removeAllViews()
        label("${getString(R.string.app_name)} — TAKE / RETURN")
        status = TextView(this).also { content.addView(it) }
        val owner = app.store.activeOwner()
        if (owner == null) {
            startActivity(Intent(this, il.fca.companion.ui.EntryActivity::class.java))
            finish()
            return
        }
        label("משתמש FCA: $displayName")
        val installation = app.store.installation(owner)
        label("התקנה: ${installation.device ?: "טרם נרשמה"}")
        button("רענון משתמש, מכשיר ורכבים") { task { load(owner) } }
        label("החזרה אוטומטית: לאחר ניתוק ו־30 שניות המתנה, בדיקת מיקום חד־פעמית ליד הבית. נדרשת הרשאת מיקום מדויק גם ברקע; אין מעקב רציף.")
        button("הגדרת הרשאת מיקום להחזרה") {
            locationPermissions()
        }
        label("בהגדרות מיקום יש לבחור ‘כל הזמן’. לאחר מכן רעננו את נתוני הרכב והבית.")
        button("רישום ההתקנה") { task {
            register(owner)
        } }
        button("קישור רכב ל־Bluetooth שכבר צומד") {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.BLUETOOTH_CONNECT), 11)
            else chooseVehicle(owner)
        }
        app.store.associations(owner).forEach { association ->
            val name = vehicles.find { it.first == association.vehicle }?.second ?: association.vehicle
            label("$name — ${if (association.connected) "מחובר" else "לא מחובר"} — …${association.address.takeLast(5)}")
            button("הסרת קישור: $name") { task {
                val device = app.store.installation(owner).device ?: error("Register first")
                app.api.call(owner, "/api/devices/$device/vehicle-bindings/${association.vehicle}", "DELETE")
                app.store.remove(owner, association.vehicle)
                DetectorPlatform.stop(companion, association.companionId)
            } }
        }
        label("אירועים ממתינים: ${app.store.pending(owner)}")
        button("ניסיון משלוח ורענון אבחון") { DeliveryWorker.enqueue(this); draw() }
        label(app.store.diagnostics())
        button("יציאה מהחשבון (התור נשמר)") {
            app.push.invalidate()
            task {
                app.push.revokeAvailable()
                app.push.invalidate()
                app.store.activate(null)
                app.auth.signOut()
                vehicles = emptyList(); displayName = ""
            }
        }
        label("ניתוק ללא מיקום בית תקין לא מחזיר רכב. לאחר שדרוג נדרש חיבור Bluetooth אמיתי חדש לפני ההחזרה הראשונה.")
    }
    private fun task(action: () -> Unit) {
        if (busy) return
        val version = productGeneration
        busy = true; draw()
        app.io.execute {
            val message = try { action(); "בוצע" }
            catch (e: HttpFailure) { "הפעולה נכשלה (HTTP ${e.status}); המידע הממתין נשמר" }
            catch (_: Exception) { "הפעולה לא הושלמה. בדקו הרשאות, התחברות, רישום וקישור." }
            runOnUiThread {
                busy = false
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (version != productGeneration) app.store.activeOwner()?.let { owner -> task { load(owner) } }
                else if (target != null) { verificationLoading = false; productMessage = message.takeUnless { it == "בוצע" }; draw() }
                else { draw(); status.text = message }
            }
        }
    }
    private fun locationPermissions() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION), 13)
        else startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            android.net.Uri.parse("package:$packageName")))
    }
    private fun register(owner: String) {
        val installation = app.store.installation(owner)
        val device = JSONObject(app.api.call(owner, "/api/devices", "POST", JSONObject().put("request_id", installation.request)))
        check(device.isNull("revoked_at"))
        app.store.registered(owner, device.getString("device_ref"))
        load(owner)
    }
    private fun load(owner: String) {
        val vehicle = target
        val version = productGeneration
        if (vehicle != null) {
            runOnUiThread { if (version == productGeneration) { verificationLoading = true; targetVerified = false; presentation = CompanionPresentation() } }
            val detail = JSONObject(app.api.call(owner, "/api/vehicles/$vehicle"))
            val retired = !detail.isNull("retired_at")
            val before = if (retired) CompanionPresentation(CompanionHealth.RETIRED) else readCompanionPresentation(app, owner, vehicle)
            val refreshed = retired || before.device == DeviceHealth.INVALID ||
                runCatching { CompanionAccountRefresh.refresh(app, owner) }.isSuccess
            val snapshot = if (retired) CompanionPresentation(CompanionHealth.RETIRED)
                else if (before.device == DeviceHealth.INVALID) before
                else if (refreshed) readCompanionPresentation(app, owner, vehicle) else CompanionPresentation()
            runOnUiThread {
                if (version == productGeneration && app.store.activeOwner() == owner && app.auth.owner() == owner) {
                    targetName = detail.getString("display_name"); targetRetired = retired
                    targetVerified = true; presentation = snapshot
                }
            }
            return
        }
        val me = JSONObject(app.api.call(owner, "/api/me"))
        check(!me.isNull("family_id"))
        displayName = me.getString("name")
        val data = JSONArray(app.api.call(owner, "/api/vehicles"))
        vehicles = (0 until data.length()).map { data.getJSONObject(it).let { v -> v.getString("vehicle_ref") to v.getString("display_name") } }
        CompanionAccountRefresh.refresh(app, owner)
    }
    private fun chooseVehicle(owner: String) {
        if (app.store.installation(owner).device == null || vehicles.isEmpty()) {
            status.text = "יש לרשום את ההתקנה ולטעון רכבים תחילה"; return
        }
        AlertDialog.Builder(this).setTitle("בחירת רכב משפחתי")
            .setItems(vehicles.map { it.second }.toTypedArray()) { _, i -> choosePaired(owner, vehicles[i].first) }.show()
    }
    private fun choosePaired(owner: String, vehicle: String) {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val paired = getSystemService(BluetoothManager::class.java).adapter?.bondedDevices?.toList().orEmpty()
        if (paired.isEmpty()) { if (target != null) productMessage = "אין מכשירי Bluetooth מצומדים זמינים" else status.text = "אין מכשירי Bluetooth מצומדים זמינים"; return }
        if (target != null) { picker = paired; return }
        AlertDialog.Builder(this).setTitle("בחירת Bluetooth שכבר צומד")
            .setItems(paired.map { "${it.name ?: "Bluetooth"} — …${it.address.takeLast(5)}" }.toTypedArray()) { _, index ->
                associate(owner, vehicle, paired[index])
            }.show()
    }
    private fun associate(owner: String, vehicle: String, device: BluetoothDevice) {
        val version = productGeneration
        if (!packageManager.hasSystemFeature(PackageManager.FEATURE_COMPANION_DEVICE_SETUP) ||
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val address = device.address
        if (device.bondState != BluetoothDevice.BOND_BONDED) return
        if (app.store.associations(owner).any { it.address == address && it.vehicle != vehicle }) {
            if (target != null) productMessage = "Bluetooth זה כבר מקושר לרכב אחר; הסירו את הקישור קודם"
            else status.text = "Bluetooth זה כבר מקושר לרכב אחר; הסירו את הקישור קודם"
            return
        }
        val existing = companion.myAssociations.find { it.deviceMacAddress?.toString().equals(address, true) }
        if (existing != null) { activate(owner, vehicle, address, existing); return }
        val request = AssociationRequest.Builder().setSingleDevice(true)
            .addDeviceFilter(BluetoothDeviceFilter.Builder().setAddress(address).build()).build()
        companion.associate(request, mainExecutor, object : CompanionDeviceManager.Callback() {
            override fun onAssociationPending(sender: IntentSender) {
                if (version != productGeneration) return
                startIntentSenderForResult(sender, 12, null, 0, 0, 0)
            }
            override fun onAssociationCreated(info: AssociationInfo) {
                if (version == productGeneration && info.deviceMacAddress?.toString().equals(address, true)) activate(owner, vehicle, address, info)
            }
            override fun onFailure(error: CharSequence?) {
                if (version != productGeneration) return
                if (target != null) productMessage = "אישור מערכת לא הושלם; לא הופעל זיהוי"
                else status.text = "אישור מערכת לא הושלם; לא הופעל זיהוי"
            }
        })
    }
    private fun activate(owner: String, vehicle: String, address: String, info: AssociationInfo) = task {
        check(app.store.activeOwner() == owner && app.auth.owner() == owner)
        val device = app.store.installation(owner).device ?: error("Register first")
        app.api.call(owner, "/api/devices/$device/vehicle-bindings/$vehicle", "PUT")
        val old = app.store.associations(owner).find { it.vehicle == vehicle }
        if (old != null && old.companionId != info.id)
            DetectorPlatform.stop(companion, old.companionId)
        app.store.associate(owner, vehicle, address, info.id)
        DetectorPlatform.start(companion, info.id)
        app.store.diagnostic("association_enabled_wait_for_connection")
        if (target != null) load(owner)
    }
}
