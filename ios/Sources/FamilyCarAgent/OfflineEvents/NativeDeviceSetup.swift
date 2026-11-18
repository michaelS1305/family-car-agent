import Foundation

enum VehicleConnectionMethod: String, Codable, CaseIterable { case carPlay, bluetooth }
enum NativeDeviceSetupError: Error { case busy, recoveryRequired, unavailable, stale }

/// View state and action routing are intentionally separate from the previous Boolean.
enum VehicleConnectionAuthorizationState: Equatable {
    case inactive, authorized, verificationPending, temporarilyUnavailable, bindingRemoved, verificationRequired, recoveryRequired
    var permitsActivation: Bool { self == .inactive || self == .bindingRemoved }
    var isAuthorized: Bool { self == .authorized }
    func afterVerificationFailure() -> Self {
        self == .verificationPending ? .temporarilyUnavailable : self
    }
}

/// Non-credential installation journal. queuePrepared is committed BEFORE any scope is enabled.
struct NativeDeviceRegistration: Codable, Equatable {
    let environment: String
    let owner: UUID
    let user: Int64
    let family: Int64
    let requestID: UUID
    var device: UUID?
    var queuePrepared = false
    var methods: [UUID: VehicleConnectionMethod] = [:]
}

@MainActor protocol NativeDeviceStore {
    func read(owner: UUID) throws -> NativeDeviceRegistration?
    func write(_ value: NativeDeviceRegistration) throws
}

/// Separate from SQLite so loss of a previously initialized queue cannot look like a new device.
@MainActor final class NativeDeviceFileStore: NativeDeviceStore {
    private let directory: URL
    init(directory: URL) { self.directory = directory }
    func read(owner: UUID) throws -> NativeDeviceRegistration? {
        let file = directory.appendingPathComponent(owner.uuidString + ".json")
        let data: Data
        do { data = try Data(contentsOf: file) }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile { return nil }
        return try JSONDecoder().decode(NativeDeviceRegistration.self, from: data)
    }
    func write(_ value: NativeDeviceRegistration) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path)
        var root = directory
        var attributes = URLResourceValues(); attributes.isExcludedFromBackup = true
        try root.setResourceValues(attributes)
        #endif
        let file = directory.appendingPathComponent(value.owner.uuidString + ".json")
        var options: Data.WritingOptions = [.atomic]
        #if os(iOS)
        options.insert(.completeFileProtectionUntilFirstUserAuthentication)
        #endif
        try JSONEncoder().encode(value).write(to: file, options: options)
        let handle = try FileHandle(forWritingTo: file)
        defer { try? handle.close() }
        try handle.synchronize()
    }
}

@MainActor protocol NativeDeviceSetupGateway: AnyObject {
    func check() throws
    var hasSavedScope: Bool { get }
    func register(requestID: UUID) async throws -> UUID
    func validate(device: UUID) async throws
    func bind(device: UUID, vehicle: UUID) async throws
    func enable(_ context: VehicleQueueContext, verification: UUID) async throws
}

/// Serializes activation and restoration; it never discovers/adopts devices from a list.
@MainActor final class NativeDeviceSetup {
    private let environment: AppEnvironment
    private let store: any NativeDeviceStore
    private let queue: VehicleEventQueue
    private(set) var busy = false
    init(environment: AppEnvironment, store: any NativeDeviceStore, queue: VehicleEventQueue) {
        self.environment = environment; self.store = store; self.queue = queue
    }
    func saved(_ identity: ChatIdentity) throws -> NativeDeviceRegistration? {
        let stored: NativeDeviceRegistration?
        do { stored = try store.read(owner: identity.owner) }
        catch { throw NativeDeviceSetupError.recoveryRequired }
        guard let value = stored else { return nil }
        guard value.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
              value.owner == identity.owner, value.user == identity.user, value.family == identity.family,
              !value.queuePrepared || value.device != nil else { throw NativeDeviceSetupError.recoveryRequired }
        return value
    }
    func setMethod(_ method: VehicleConnectionMethod, vehicle: UUID, identity: ChatIdentity) throws {
        guard !busy else { throw NativeDeviceSetupError.busy }
        guard var value = try saved(identity), value.queuePrepared, value.methods[vehicle] != nil else {
            throw NativeDeviceSetupError.recoveryRequired
        }
        value.methods[vehicle] = method; try store.write(value)
    }
    func readyForRestore(_ identity: ChatIdentity, scope: VehicleSessionScope?) throws -> Bool {
        let record = try saved(identity)
        if let scope {
            guard let record, record.queuePrepared, record.device == scope.device,
                  record.environment == scope.environment, record.user == scope.user, record.family == scope.family
            else { throw NativeDeviceSetupError.recoveryRequired }
        }
        return record?.queuePrepared == true
    }

    func validateOffline(_ identity: ChatIdentity, scope: VehicleSessionScope) async throws {
        guard try readyForRestore(identity, scope: scope) else { throw NativeDeviceSetupError.recoveryRequired }
        let context = try VehicleQueueContext(environment: environment, identity: identity, device: scope.device)
        do { try await queue.validateSequence(context) }
        catch { throw NativeDeviceSetupError.recoveryRequired }
    }
    func connectionState(_ identity: ChatIdentity, vehicle: UUID, namespace: UUID?) async throws -> VehicleConnectionAuthorizationState {
        guard let record = try saved(identity), record.queuePrepared, let device = record.device else { return .inactive }
        let context = try VehicleQueueContext(environment: environment, identity: identity, device: device)
        try await queue.validateSequence(context)
        switch try await queue.authorizationStatus(context, vehicle: vehicle, namespace: namespace) {
        case .unknown: return .verificationRequired
        case .pending: return .verificationPending
        case .authorized: return .authorized
        case .removed: return .bindingRemoved
        case .fenced: return .verificationRequired
        }
    }
    func activate(identity: ChatIdentity, vehicle: UUID?, method: VehicleConnectionMethod?, gateway: any NativeDeviceSetupGateway) async throws {
        guard !busy else { throw NativeDeviceSetupError.busy }
        busy = true; defer { busy = false }
        try gateway.check()
        var value: NativeDeviceRegistration
        if let existing = try saved(identity) { value = existing }
        else {
            guard vehicle != nil, !gateway.hasSavedScope else { throw NativeDeviceSetupError.recoveryRequired }
            let history = try await queue.hasDeviceHistory(environment: environment, owner: identity.owner)
            guard !history else { throw NativeDeviceSetupError.recoveryRequired }
            try gateway.check()
            value = .init(environment: environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
                          owner: identity.owner, user: identity.user, family: identity.family, requestID: UUID())
            try store.write(value) // No POST is allowed before this succeeds.
        }
        // Restoration never registers or binds anything implicitly.
        if vehicle == nil && !value.queuePrepared { return }
        if value.device == nil {
            let device = try await gateway.register(requestID: value.requestID)
            try gateway.check()
            value.device = device; try store.write(value)
        }
        guard let device = value.device else { throw NativeDeviceSetupError.recoveryRequired }
        let context = try VehicleQueueContext(environment: environment, identity: identity, device: device)
        if !value.queuePrepared {
            // Only this journal's never-enabled registration may initialize a zero cursor.
            try await queue.initializeFreshDevice(context); try gateway.check()
            value.queuePrepared = true; try store.write(value)
        } else {
            // reactivate requires the exact existing partition; it never inserts/resets it.
            do { try await queue.reactivate(context) }
            catch { throw NativeDeviceSetupError.recoveryRequired }
            try gateway.check()
        }
        let verification = try await queue.beginVerification(context)
        try gateway.check()
        try await gateway.validate(device: device); try gateway.check()
        if let vehicle, let method {
            try await gateway.bind(device: device, vehicle: vehicle); try gateway.check()
            value.methods[vehicle] = method; try store.write(value)
        }
        try await gateway.enable(context, verification: verification); try gateway.check()
    }
}
