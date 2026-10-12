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
    val model = OnboardingModel(object : OnboardingGateway {
        override suspend fun request(path: String, method: String, body: JSONObject?) = withContext(Dispatchers.IO) {
            val owner = checkNotNull(app.auth.owner())
            JSONObject(if (path == "/api/family") app.api.call(owner, path, method, body)
                else app.api.onboarding(owner, path, method, body))
        }
        override suspend fun activate() = withContext(Dispatchers.IO) {
            app.store.activate(checkNotNull(app.auth.owner()))
            DeliveryWorker.enqueue(app)
        }
        override suspend fun clearSession() = withContext(Dispatchers.IO) {
            app.store.activate(null); app.auth.signOut()
        }
    })
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
        if (model.screen in setOf(EntryScreen.AUTHENTICATED_APP, EntryScreen.BOOTSTRAP, EntryScreen.SUCCESS) &&
            (app.store.activeOwner() == null || app.store.activeOwner() != app.auth.owner())) {
            rootRefresh.reset(); model.leaveAuthenticatedApp()
        }
    }
    fun enteredApp() {
        val owner = app.store.activeOwner() ?: return
        viewModelScope.launch {
            rootRefresh.enter(owner, { app.store.activeOwner() == it && app.auth.owner() == it }) {
                withContext(Dispatchers.IO) { CompanionAccountRefresh.refresh(app, it) }
            }
        }
    }
    fun beginLogin(openBrowser: (Uri) -> Unit) {
        if (exchanging || model.busy) return
        try {
            pending.save(model.route)
            // Same activation boundary as the previous Companion login screen.
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
    private lateinit var viewModel: EntryViewModel
    private lateinit var chat: ChatViewModel
    private lateinit var history: HistoryViewModel
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        viewModel = ViewModelProvider(this)[EntryViewModel::class.java]
        val app = application as FcaApplication
        chat = ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                ChatViewModel(ChatApi(app.api), {
                    app.store.activeOwner()?.takeIf { it == app.auth.owner() }
                }) as T
        })[ChatViewModel::class.java]
        val entryModel = viewModel.model
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
        chat.activateOwner()
        if (intent.data != null) callback(intent)
        else if (savedInstanceState == null || viewModel.model.screen == EntryScreen.INTRO) viewModel.openExistingSession()
        setContent {
            EntryUi(viewModel.model, chat, history,
                login = { viewModel.beginLogin { startActivity(Intent(Intent.ACTION_VIEW, it)) } },
                next = viewModel::next, back = viewModel::back, changeAddress = viewModel::changeAddress,
                retryBootstrap = viewModel::openExistingSession, enteredApp = viewModel::enteredApp,
                logout = { viewModel.logout { chat.activateOwner() } })
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.data != null) callback(intent) else viewModel.reconcileOwner()
        chat.activateOwner()
    }
    override fun onResume() {
        super.onResume()
        viewModel.reconcileOwner()
        chat.activateOwner()
    }
    private fun callback(intent: Intent) {
        val uri = intent.data ?: return
        intent.data = null
        viewModel.callback(uri)
    }
}
