import Foundation

struct FirstVehicleSetupSnapshot: Equatable {
    var identity: ChatIdentity?
    var current: Bool
    var loaded: Bool
    var loading: Bool
    var loadError: Bool
    var canCreate: Bool
    var vehicleCount: Int
    var atRoot: Bool
    var hasVehicleDestination: Bool
    var blocked: Bool
    var successfullyLoaded: Bool { current && loaded && !loading && !loadError }
}

// Shell-lifetime state, like Android's activity state; not a permanent preference.
struct FirstVehicleSetupState {
    private var owner: UUID?
    private var family: Int64?
    private(set) var handled = false

    mutating func activate(_ identity: ChatIdentity?) {
        guard owner != identity?.owner || family != identity?.family else { return }
        owner = identity?.owner; family = identity?.family; handled = false
    }
    func needsCheck(_ identity: ChatIdentity?) -> Bool {
        guard let identity, identity.family > 0 else { return false }
        return owner == identity.owner && family == identity.family && !handled
    }
    mutating func observe(_ value: FirstVehicleSetupSnapshot) {
        if needsCheck(value.identity) && value.successfullyLoaded && value.vehicleCount > 0 {
            handled = true
        }
    }
    func visible(_ value: FirstVehicleSetupSnapshot) -> Bool {
        needsCheck(value.identity) && value.successfullyLoaded && value.canCreate &&
        value.vehicleCount == 0 && value.atRoot && !value.hasVehicleDestination && !value.blocked
    }
    mutating func handle(_ identity: ChatIdentity?) {
        if needsCheck(identity) { handled = true }
    }
}
