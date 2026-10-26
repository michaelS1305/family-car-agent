import Foundation
#if canImport(Combine)
import Combine
#endif

@MainActor final class EntryModel: ObservableObject {
    enum Screen { case intro, login, bootstrap, onboarding, success, ready }
    @Published private(set) var screen = Screen.intro
    @Published private(set) var busy = false
    @Published private(set) var error: String?
    @Published private(set) var me: Me?
    @Published private(set) var step = 1
    @Published var route = LoginRoute.existing
    @Published var familyName = ""
    @Published var address = ""
    @Published var userName = ""
    @Published var familyCode = ""
    @Published var consent = false
    @Published private(set) var resolvedAddress = ""
    @Published private(set) var createdCode = ""
    private var resolutionToken: String?
    private var completed = false
    private var version = 0
    private var started = false
    private var api: (any BackendTransport)?
    private var sessions: SessionManager?
    private var providers: (any NativeAuthProvider)?
    private var checkingApple = false

    init(sessions: SessionManager, api: any BackendTransport, providers: any NativeAuthProvider) {
        self.sessions = sessions; self.api = api; self.providers = providers
    }

    #if canImport(UIKit)
    init() {
        do {
            let env = try AppEnvironment.current()
            guard Bundle.main.object(forInfoDictionaryKey: "FCAEnvironment") as? String == "development",
                  let key = Bundle.main.object(forInfoDictionaryKey: "FCASupabasePublishableKey") as? String else { throw AuthFailure.configuration }
            let api = try AuthAPI(environment: env, publicKey: key)
            self.api = api
            sessions = SessionManager(vault: KeychainVault(environment: env), transport: api)
            providers = NativeProviders(environment: env)
        } catch { self.error = AuthFailure.configuration.message }
    }
    #endif
    private func resetPrivate() {
        me = nil; familyName = ""; address = ""; userName = ""; familyCode = ""
        consent = false; resolutionToken = nil; resolvedAddress = ""; createdCode = ""; completed = false; step = 1
    }
    func logout() {
        version += 1; providers?.cancel(); resetPrivate(); screen = .intro; busy = false; error = nil
        do { try sessions?.clear() } catch { self.error = AuthFailure.storage.message }
    }
    private func perform(_ action: () async throws -> Void) async {
        guard !busy, sessions != nil else { return }
        busy = true; error = nil
        let current = version
        defer { if current == version { busy = false } }
        do { try await action() }
        catch {
            guard current == version else { return }
            let failure = error as? AuthFailure ?? .network
            switch failure {
            case .signedOut, .rejected(401, _), .rejected(403, "ACCOUNT_UNAVAILABLE"), .rejected(403, "MISSING_ACCOUNT"):
                logout(); if self.error == nil { self.error = failure.message }
            default:
                self.error = failure.message
                if failure == .rejected(409, "ADDRESS_RESOLUTION_EXPIRED") { resolutionToken = nil; step = 2 }
                if failure == .rejected(400, "INVALID_FAMILY_NAME") { step = 1 }
                if failure == .rejected(400, "INVALID_USER_NAME") { step = route == .create ? 4 : 5 }
            }
        }
    }
    func start() async {
        guard !started else { return }; started = true
        await perform {
            try sessions?.restore()
            guard sessions?.session != nil else { return }
            screen = .bootstrap
            try await bootstrap()
        }
    }
    func resume() async {
        // Ordinary foregrounding must not reset navigation or show global loading.
        guard !busy, !checkingApple, let user = sessions?.session?.appleUser else { return }
        checkingApple = true; let current = version
        defer { checkingApple = false }
        do {
            let valid = try await providers?.credentialValid(user) == true
            if current == version && !valid { logout(); if error == nil { error = AuthFailure.signedOut.message } }
        } catch { /* A system failure is not evidence of revocation. */ }
    }
    func selectRoute(_ selected: LoginRoute) {
        guard !busy, screen == .intro else { return }
        route = selected; error = nil; screen = .login
    }
    func backFromEntry() {
        guard !busy else { return }
        switch screen {
        case .login: error = nil; screen = .intro
        case .onboarding: error = nil; screen = .login
        default: break
        }
    }
    // The entry UI stops before any onboarding API operation. Existing domain checks
    // may still exercise the previously implemented onboarding flow independently.
    func login(apple: Bool, previewOnboarding: Bool = false) async {
        await perform {
            #if DEBUG
            var googleFlowCompleted = false
            defer {
                if !apple && !googleFlowCompleted { GoogleAuthDiagnostics.event("auth_flow_failed") }
            }
            #endif
            guard let sessions, let providers else { throw AuthFailure.configuration }
            try sessions.clear(); resetPrivate()
            let current = version; let selected = route
            let result = try await providers.authorize(apple: apple)
            guard current == version else { throw AuthFailure.stale }
            #if DEBUG
            if apple { AppleAuthDiagnostics.event("supabase_operation_reached") }
            #endif
            try await sessions.login(grant: result.grant, fields: result.fields, appleUser: result.appleUser)
            #if DEBUG
            if !apple { GoogleAuthDiagnostics.event("session_persisted") }
            #endif
            guard current == version else { throw AuthFailure.stale }
            switch selected {
            case .existing: screen = .bootstrap; try await finish(existing: true)
            case .create: screen = .onboarding; step = 1
            case .join:
                if previewOnboarding { screen = .onboarding; step = 1 }
                else { try await loadJoin() }
            }
            #if DEBUG
            googleFlowCompleted = true
            if !apple { GoogleAuthDiagnostics.event("route_restored") }
            #endif
        }
    }
    private func request<T: Decodable & Sendable>(_ type: T.Type, _ path: String, _ fields: [String: Field]? = nil) async throws -> T {
        guard let api, let sessions, let owner = sessions.session?.owner else { throw AuthFailure.signedOut }
        let current = version; let generation = sessions.generation
        func check() throws {
            guard current == version, generation == sessions.generation, sessions.session?.owner == owner else { throw AuthFailure.stale }
        }
        func attempt(force: Bool) async throws -> T {
            let token = try await sessions.access(owner: owner, force: force)
            try check()
            let result = try await api.backend(type, path: path, token: token, fields: fields)
            try check(); return result
        }
        do { return try await attempt(force: false) }
        catch AuthFailure.rejected(401, _) { try check(); return try await attempt(force: true) }
    }
    private func finish(existing: Bool) async throws {
        let profile = try await request(Me.self, "/api/me")
        guard profile.family_id > 0, profile.user_id > 0, let owner = sessions?.session?.owner else { throw AuthFailure.invalidResponse }
        if !existing && route == .create { createdCode = try await request(FamilyCode.self, "/api/family").family_code }
        try sessions?.activate(owner: owner)
        me = profile; resolutionToken = nil; familyCode = ""
        screen = existing ? .ready : .success
    }
    private func bootstrap() async throws {
        let current = version
        if let user = sessions?.session?.appleUser {
            guard try await providers?.credentialValid(user) == true else { throw AuthFailure.signedOut }
        }
        guard current == version else { throw AuthFailure.stale }
        try await finish(existing: true)
    }
    func retry() async { await perform { try await bootstrap() } }
    func enter() { guard screen == .success else { return }; screen = .ready }
    private func apply(_ state: JoinState) throws {
        let steps = ["family_name": 1, "address": 2, "address_confirmed": 3, "family_code": 4, "user_name": 5]
        guard let value = steps[state.step] else { throw AuthFailure.invalidResponse }
        step = value; screen = .onboarding
        familyName = state.family_name ?? ""; resolvedAddress = state.resolved_address ?? ""
        if address.isEmpty { address = state.normalized_address ?? "" }
    }
    private func loadJoin() async throws {
        try apply(await request(JoinState.self, "/api/onboarding/join-family/start", [:]))
    }
    func changeAddress() async {
        await perform {
            if route == .join {
                try apply(await request(JoinState.self, "/api/onboarding/join-family/address-confirmation", ["confirmed": .flag(false)]))
            } else { resolutionToken = nil; step = 2 }
        }
    }
    func next() async {
        await perform {
            if completed { try await finish(existing: false); return }
            guard screen == .onboarding else { return }
            let last = route == .create ? 4 : 5
            if step == 1 && !OnboardingValidation.validName(familyName) { throw AuthFailure.rejected(400, "INVALID_FAMILY_NAME") }
            if step == 2 && (address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || address.unicodeScalars.count > 200) {
                throw AuthFailure.rejected(400, "INVALID_ADDRESS_FORMAT")
            }
            if step == last {
                guard OnboardingValidation.validName(userName) else { throw AuthFailure.rejected(400, "INVALID_USER_NAME") }
                guard consent else { error = "כדי להשלים את ההרשמה, יש לאשר את הצהרת הכשירות לשימוש ברכב."; return }
            }
            if route == .create {
                switch step {
                case 1: step = 2
                case 2:
                    let value = try await request(AddressResult.self, "/api/onboarding/create-family/address", ["home_address": .text(address)])
                    guard !value.resolution_token.isEmpty, !value.display_address.isEmpty else { throw AuthFailure.invalidResponse }
                    resolutionToken = value.resolution_token; resolvedAddress = value.display_address; step = 3
                case 3: step = 4
                case 4:
                    guard let token = resolutionToken else { throw AuthFailure.rejected(409, "ADDRESS_RESOLUTION_EXPIRED") }
                    let result = try await request(CreatedResult.self, "/api/onboarding/create-family",
                        ["family_name": .text(familyName), "user_name": .text(userName), "address_resolution_token": .text(token)])
                    guard result.created else { throw AuthFailure.invalidResponse }
                    completed = true; try await finish(existing: false)
                default: throw AuthFailure.invalidResponse
                }
            } else {
                let suffix: String; let fields: [String: Field]
                switch step {
                case 1: suffix = "family-name"; fields = ["family_name": .text(familyName)]
                case 2: suffix = "address"; fields = ["home_address": .text(address)]
                case 3: suffix = "address-confirmation"; fields = ["confirmed": .flag(true)]
                case 4: suffix = "code"; fields = ["family_code": .text(familyCode)]
                default: suffix = "complete"; fields = ["user_name": .text(userName)]
                }
                do {
                    if step == 5 {
                        let result = try await request(CreatedResult.self, "/api/onboarding/join-family/complete", fields)
                        guard result.created else { throw AuthFailure.invalidResponse }
                        completed = true; try await finish(existing: false)
                    } else { try apply(await request(JoinState.self, "/api/onboarding/join-family/" + suffix, fields)) }
                } catch AuthFailure.rejected(409, "INVALID_JOIN_STEP") {
                    try await loadJoin()
                }
            }
        }
    }
}
