package il.fca.companion.detector

import android.Manifest
import android.bluetooth.BluetoothDevice
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import il.fca.companion.FcaApplication
import il.fca.companion.data.LocalStore

class AclReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Build.VERSION.SDK_INT != 35 || context.checkSelfPermission(
                Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return
        try {
            val device = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java) ?: return
            if (device.bondState != BluetoothDevice.BOND_BONDED) return
            val store = (context.applicationContext as FcaApplication).store
            val event = resolve(store, intent.action, device.address,
                intent.getIntExtra(BluetoothDevice.EXTRA_TRANSPORT, BluetoothDevice.TRANSPORT_AUTO)) ?: return
            // Only local persistence/scheduling; never Bluetooth identity or network I/O.
            DetectorEvents.record(context, event.first, event.second)
        } catch (_: Exception) {
            // Permission removal/malformed system input must fail closed without identity logs.
        }
    }

    internal companion object {
        fun resolve(store: LocalStore, action: String?, address: String, transport: Int): Pair<Int, Boolean>? {
            if (Build.VERSION.SDK_INT != 35 || transport != BluetoothDevice.TRANSPORT_BREDR) return null
            val connected = when (action) {
                BluetoothDevice.ACTION_ACL_CONNECTED -> true
                BluetoothDevice.ACTION_ACL_DISCONNECTED -> false
                else -> return null
            }
            val owner = store.activeOwner() ?: return null
            val association = store.associations(owner).singleOrNull { it.address.equals(address, true) } ?: return null
            return association.companionId to connected
        }
    }
}
