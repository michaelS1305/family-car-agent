package il.fca.companion

import android.Manifest
import android.app.Activity
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

class MainActivity : Activity() {
    private val app get() = application as FcaApplication
    private lateinit var content: LinearLayout
    private lateinit var status: TextView
    private var busy = false
    private var vehicles = emptyList<Pair<String, String>>()
    private var displayName = ""
    private val companion get() = getSystemService(CompanionDeviceManager::class.java)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24) }
        val scroll = ScrollView(this).apply { addView(content) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom); insets
        }
        setContentView(scroll)
        draw()
        callback(intent)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        callback(intent)
    }
    private fun callback(intent: Intent) {
        val uri = intent.data ?: return
        // Prevent duplicate code exchange on Activity recreation.
        intent.data = null
        task {
            val owner = app.auth.finishLogin(uri)
            val me = JSONObject(app.api.call(owner, "/api/me"))
            check(!me.isNull("family_id"))
            app.store.activate(owner)
            displayName = me.getString("name")
            load(owner)
            DeliveryWorker.enqueue(this)
        }
    }
    private fun label(text: String) { content.addView(TextView(this).apply { this.text = text; textSize = 16f }) }
    private fun button(text: String, action: () -> Unit) {
        content.addView(Button(this).apply { this.text = text; isEnabled = !busy; setOnClickListener { action() } })
    }
    private fun draw() {
        content.removeAllViews()
        label("${getString(R.string.app_name)} — TAKE / RETURN")
        status = TextView(this).also { content.addView(it) }
        val owner = app.store.activeOwner()
        if (owner == null) {
            button("כניסה עם Google") {
                runCatching {
                    check(BuildConfig.SUPABASE_URL.startsWith("https://") && BuildConfig.FCA_BASE_URL.startsWith("https://"))
                    app.store.activate(null)
                    startActivity(Intent(Intent.ACTION_VIEW, app.auth.beginLogin()))
                }.onFailure { status.text = "יש לבדוק את הגדרות הבנייה ולהתחיל כניסה מחדש" }
            }
            label("יש להיכנס לחשבון FCA קיים. אירועים מחשבון קודם נשמרים ואינם מועברים לחשבון אחר.")
            return
        }
        label("משתמש FCA: $displayName")
        val installation = app.store.installation(owner)
        label("התקנה: ${installation.device ?: "טרם נרשמה"}")
        button("רענון משתמש, מכשיר ורכבים") { task { load(owner) } }
        label("החזרה אוטומטית: לאחר ניתוק ו־30 שניות המתנה, בדיקת מיקום חד־פעמית ליד הבית. נדרשת הרשאת מיקום מדויק גם ברקע; אין מעקב רציף.")
        button("הגדרת הרשאת מיקום להחזרה") {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION), 13)
            else startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                android.net.Uri.parse("package:$packageName")))
        }
        label("בהגדרות מיקום יש לבחור ‘כל הזמן’. לאחר מכן רעננו את נתוני הרכב והבית.")
        button("רישום ההתקנה") { task {
            val device = JSONObject(app.api.call(owner, "/api/devices", "POST", JSONObject().put("request_id", installation.request)))
            check(device.isNull("revoked_at"))
            app.store.registered(owner, device.getString("device_ref"))
            load(owner)
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
            app.store.activate(null)
            app.auth.signOut()
            vehicles = emptyList(); displayName = ""; draw()
        }
        label("ניתוק ללא מיקום בית תקין לא מחזיר רכב. לאחר שדרוג נדרש חיבור Bluetooth אמיתי חדש לפני ההחזרה הראשונה.")
    }
    private fun task(action: () -> Unit) {
        if (busy) return
        busy = true; draw()
        app.io.execute {
            val message = try { action(); "בוצע" }
            catch (e: HttpFailure) { "הפעולה נכשלה (HTTP ${e.status}); המידע הממתין נשמר" }
            catch (_: Exception) { "הפעולה לא הושלמה. בדקו הרשאות, התחברות, רישום וקישור." }
            runOnUiThread { busy = false; draw(); status.text = message }
        }
    }
    private fun load(owner: String) {
        val me = JSONObject(app.api.call(owner, "/api/me"))
        check(!me.isNull("family_id"))
        displayName = me.getString("name")
        val data = JSONArray(app.api.call(owner, "/api/vehicles"))
        vehicles = (0 until data.length()).map { data.getJSONObject(it).let { v -> v.getString("vehicle_ref") to v.getString("display_name") } }
        app.store.installation(owner).device?.let { device ->
            // Fetch actual server device/binding state; never infer authorization from local mapping.
            val devices = JSONArray(app.api.call(owner, "/api/devices"))
            val registered = (0 until devices.length()).map { devices.getJSONObject(it) }
                .find { it.getString("device_ref") == device }
            check(registered != null && registered.isNull("revoked_at"))
            val bindings = JSONArray(app.api.call(owner, "/api/devices/$device/vehicle-bindings"))
            val usable = (0 until bindings.length()).map { bindings.getJSONObject(it) }
                .filter { it.getBoolean("usable") }.map { it.getString("vehicle_ref") }.toSet()
            app.store.associations(owner).filter { it.vehicle !in usable }.forEach {
                app.store.remove(owner, it.vehicle)
                DetectorPlatform.stop(companion, it.companionId)
            }
            // RETURN setup failure must not prevent existing TAKE/binding refresh.
            runCatching {
                val home = JSONObject(app.api.call(owner, "/api/devices/$device/return-home"))
                app.store.saveHome(owner, home.getDouble("latitude"), home.getDouble("longitude"))
            }.onFailure {
                app.store.clearHome(owner)
                app.store.diagnostic("return_home_refresh_failed")
            }
        }
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
        if (paired.isEmpty()) { status.text = "אין מכשירי Bluetooth מצומדים זמינים"; return }
        AlertDialog.Builder(this).setTitle("בחירת Bluetooth שכבר צומד")
            .setItems(paired.map { "${it.name ?: "Bluetooth"} — …${it.address.takeLast(5)}" }.toTypedArray()) { _, index ->
                associate(owner, vehicle, paired[index])
            }.show()
    }
    private fun associate(owner: String, vehicle: String, device: BluetoothDevice) {
        if (!packageManager.hasSystemFeature(PackageManager.FEATURE_COMPANION_DEVICE_SETUP) ||
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        val address = device.address
        if (device.bondState != BluetoothDevice.BOND_BONDED) return
        if (app.store.associations(owner).any { it.address == address && it.vehicle != vehicle }) {
            status.text = "Bluetooth זה כבר מקושר לרכב אחר; הסירו את הקישור קודם"; return
        }
        val existing = companion.myAssociations.find { it.deviceMacAddress?.toString().equals(address, true) }
        if (existing != null) { activate(owner, vehicle, address, existing); return }
        val request = AssociationRequest.Builder().setSingleDevice(true)
            .addDeviceFilter(BluetoothDeviceFilter.Builder().setAddress(address).build()).build()
        companion.associate(request, mainExecutor, object : CompanionDeviceManager.Callback() {
            override fun onAssociationPending(sender: IntentSender) {
                startIntentSenderForResult(sender, 12, null, 0, 0, 0)
            }
            override fun onAssociationCreated(info: AssociationInfo) {
                if (info.deviceMacAddress?.toString().equals(address, true)) activate(owner, vehicle, address, info)
            }
            override fun onFailure(error: CharSequence?) { status.text = "אישור מערכת לא הושלם; לא הופעל זיהוי" }
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
    }
}
