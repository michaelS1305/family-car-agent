package il.fca.companion.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import il.fca.companion.FcaApplication
import il.fca.companion.CompanionAccountRefresh
import il.fca.companion.delivery.DeliveryWorker
import il.fca.companion.net.ChatApi
import il.fca.companion.net.HistoryApi
import il.fca.companion.net.VehiclesApi
import il.fca.companion.net.FamilyApi
import il.fca.companion.net.RealtimeBroadcast
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class EntryViewModel(private val app: FcaApplication) : AndroidViewModel(app) {
    constructor(application: android.app.Application) : this(application as FcaApplication)
    private val pending = PendingLoginRoute(app)
    private var exchanging = false
    private val rootRefresh = AuthenticatedRootRefresh()
    internal val firstVehicleSetup = FirstVehicleSetupState()
    internal fun setupIdentity(): VehiclesIdentity? {
        val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() } ?: return null
        val family = model.authenticatedFamilyId ?: return null
        return if (model.screen == EntryScreen.AUTHENTICATED_APP) VehiclesIdentity(owner, family) else null
    }
    val model = OnboardingModel(object : OnboardingGateway {
        override suspend fun request(path: String, method: String, body: JSONObject?) = withContext(Dispatchers.IO) {
            val owner = checkNotNull(app.auth.owner())
            JSONObject(if (path == "/api/me" && method == "GET") app.api.bootstrap(owner)
                else if (path == "/api/family") app.api.call(owner, path, method, body)
                else app.api.onboarding(owner, path, method, body))
        }
        override suspend fun activate() = withContext(Dispatchers.IO) {
            app.store.activate(checkNotNull(app.auth.owner()))
            DeliveryWorker.enqueue(app)
        }
        override suspend fun clearSession() = withContext(Dispatchers.IO) {
            app.push.invalidate()
            app.push.revokeAvailable()
            app.push.invalidate() // Fence any foreground activation while revocation was in flight.
            app.store.activate(null); app.auth.signOut()
        }
    }, { app.auth.owner() })
    internal val account = AccountSettingsModel(object : AccountSettingsGateway {
        override suspend fun email(owner: String): String? = withContext(Dispatchers.IO) {
            // Read the authenticated Auth profile, not JWT text or a fabricated address.
            val profile = JSONObject(il.fca.companion.net.Http.request(il.fca.companion.BuildConfig.SUPABASE_URL,
                "/auth/v1/user", bearer = app.auth.access(owner),
                apiKey = il.fca.companion.BuildConfig.SUPABASE_PUBLISHABLE_KEY))
            check(profile.getString("id") == owner && app.auth.owner() == owner)
            (profile.opt("email") as? String)?.takeIf { it.isNotBlank() }
        }
        override suspend fun request(owner: String, method: String, preview: Boolean) = withContext(Dispatchers.IO) {
            check(app.auth.owner() == owner && app.store.activeOwner() == owner)
            if (method == "POST") app.push.invalidate()
            JSONObject(app.api.call(owner, "/api/account/deletion" + if (preview) "/preview" else "",
                method, if (method == "POST") JSONObject().put("confirmation", "DELETE_MY_ACCOUNT") else null))
        }
    }, {
        val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() }
        val family = model.authenticatedFamilyId
        if (owner != null && family != null && model.screen == EntryScreen.AUTHENTICATED_APP)
            AccountIdentity(owner, family) else null
    }, viewModelScope)
    fun openExistingSession() {
        val owner = app.store.activeOwner()
        if (owner != null && owner == app.auth.owner()) {
            if (model.screen != EntryScreen.AUTHENTICATED_APP && !model.busy) viewModelScope.launch {
                model.bootstrap { app.store.activeOwner() == owner && app.auth.owner() == owner }
            }
        } else {
            rootRefresh.reset()
            model.leaveAuthenticatedApp()
        }
    }
    fun reconcileOwner() {
        if (app.store.activeOwner() == null || app.store.activeOwner() != app.auth.owner()) firstVehicleSetup.clear()
        if (model.screen in setOf(EntryScreen.AUTHENTICATED_APP, EntryScreen.BOOTSTRAP, EntryScreen.SUCCESS) &&
            (app.store.activeOwner() == null || app.store.activeOwner() != app.auth.owner())) {
            rootRefresh.reset(); model.leaveAuthenticatedApp()
        }
        account.reconcile()
    }
    fun enteredApp() {
        if (account.state.protected) return
        val owner = app.store.activeOwner() ?: return
        model.authenticatedFamilyId?.let { app.push.activate(owner, it) }
        viewModelScope.launch {
            rootRefresh.enter(owner, { app.store.activeOwner() == it && app.auth.owner() == it }) {
                withContext(Dispatchers.IO) { CompanionAccountRefresh.refresh(app, it) }
            }
        }
    }
    fun beginLogin(openBrowser: (Uri) -> Unit) {
        if (exchanging || model.busy) return
        firstVehicleSetup.clear()
        try {
            pending.save(model.route)
            // Same activation boundary as the previous Companion login screen.
            app.push.invalidate()
            app.store.activate(null)
            openBrowser(app.auth.beginLogin())
        } catch (_: Exception) { pending.clear(); model.genericFailure() }
    }
    fun callback(uri: Uri) {
        if (exchanging) return
        val route = pending.take() ?: run { model.genericFailure(); return }
        exchanging = true
        model.authenticating = true
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { app.auth.finishLogin(uri) }
                model.authenticating = false
                model.authenticated(route)
            } catch (_: Exception) { model.genericFailure() }
            finally { exchanging = false; model.authenticating = false }
        }
    }
    fun next() { viewModelScope.launch { model.next() } }
    fun logout(completed: () -> Unit) {
        viewModelScope.launch {
            model.logout()
            reconcileOwner()
            completed()
        }
    }
    fun changeAddress() { viewModelScope.launch { model.changeAddress() } }
    fun back() { pending.clear(); model.back() }
}

class EntryActivity : ComponentActivity() {
    private fun enteredApp() {
        viewModel.enteredApp()
        if (!il.fca.companion.push.NativePush.supported) return
        val prefs = getSharedPreferences("push-permission", MODE_PRIVATE)
        if (!prefs.getBoolean("asked", false) &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            prefs.edit().putBoolean("asked", true).apply()
            // Same platform permission mechanism as Companion; no result callback is
            // needed because every notification checks the current OS permission.
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 6124)
        }
    }
    private lateinit var viewModel: EntryViewModel
    private lateinit var chat: ChatViewModel
    private lateinit var history: HistoryViewModel
    private lateinit var vehicles: VehiclesViewModel
    private lateinit var family: FamilyViewModel
    private lateinit var booking: BookingViewModel
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        viewModel = ViewModelProvider(this)[EntryViewModel::class.java]
        viewModel.firstVehicleSetup.restoreOnce(savedInstanceState?.getBundle("firstVehicleSetup"))
        val app = application as FcaApplication
        chat = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                ChatViewModel(ChatApi(app.api), {
                    app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                }) as T
        })[ChatViewModel::class.java]
        val entryModel = viewModel.model
        booking = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                BookingViewModel(il.fca.companion.net.BookingApi(app.api), {
                    val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                    val familyId = entryModel.authenticatedFamilyId
                    if (owner != null && familyId != null && entryModel.screen == EntryScreen.AUTHENTICATED_APP)
                        BookingIdentity(owner, familyId) else null
                }, vehicleLoad = il.fca.companion.net.VehiclesApi(app.api)::vehicles,
                    memberLoad = { owner -> il.fca.companion.net.FamilyApi(app.api).profile(owner).members }) as T
        })[BookingViewModel::class.java]
        history = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                HistoryViewModel(HistoryApi(app.api), {
                    val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                    val family = entryModel.authenticatedFamilyId
                    if (owner != null && family != null && entryModel.screen == EntryScreen.AUTHENTICATED_APP)
                        HistoryIdentity(owner, family) else null
                }, { identity -> RealtimeBroadcast(app.auth).subscribe(identity.owner,
                    "family:${identity.family}:car-status", "car_status_changed") }) as T
        })[HistoryViewModel::class.java]
        vehicles = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                VehiclesViewModel(VehiclesApi(app.api), {
                    val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                    val family = entryModel.authenticatedFamilyId
                    if (owner != null && family != null && entryModel.screen == EntryScreen.AUTHENTICATED_APP)
                        VehiclesIdentity(owner, family) else null
                }) as T
        })[VehiclesViewModel::class.java]
        family = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                FamilyViewModel(FamilyApi(app.api), {
                    val owner = app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                    val familyId = entryModel.authenticatedFamilyId
                    if (owner != null && familyId != null && entryModel.screen == EntryScreen.AUTHENTICATED_APP)
                        FamilyIdentity(owner, familyId) else null
                }) as T
        })[FamilyViewModel::class.java]
        chat.activateOwner()
        if (intent.data != null) callback(intent)
        else if (savedInstanceState == null || viewModel.model.screen == EntryScreen.INTRO) viewModel.openExistingSession()
        setContent {
            EntryUi(viewModel.model, chat, history, vehicles, family, booking,
                login = { viewModel.beginLogin { startActivity(Intent(Intent.ACTION_VIEW, it)) } },
                next = viewModel::next, back = viewModel::back, changeAddress = viewModel::changeAddress,
                retryBootstrap = viewModel::openExistingSession, enteredApp = ::enteredApp,
                logout = { viewModel.logout { chat.activateOwner() } }, account = viewModel.account,
                firstVehicleSetup = viewModel.firstVehicleSetup, setupIdentity = viewModel::setupIdentity)
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.data != null) callback(intent) else viewModel.reconcileOwner()
        chat.activateOwner()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBundle("firstVehicleSetup", viewModel.firstVehicleSetup.save())
        super.onSaveInstanceState(outState)
    }
    override fun onResume() {
        super.onResume()
        viewModel.reconcileOwner()
        chat.activateOwner()
        if (viewModel.model.screen == EntryScreen.AUTHENTICATED_APP) viewModel.enteredApp()
    }
    private fun callback(intent: Intent) {
        val uri = intent.data ?: return
        intent.data = null
        viewModel.callback(uri)
    }
}
