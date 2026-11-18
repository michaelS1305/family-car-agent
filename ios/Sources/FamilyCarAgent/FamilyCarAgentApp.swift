import SwiftUI

@main
struct FamilyCarAgentApp: App {
    @AppStorage(AppAppearance.storageKey) private var appearancePreference = AppAppearance.system.rawValue
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(VehicleSyncAppDelegate.self) private var vehicleSyncDelegate
    #endif
    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(AppAppearance(storedValue: appearancePreference).colorScheme)
        }
    }
}
