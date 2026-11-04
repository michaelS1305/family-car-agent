import SwiftUI

@main
struct FamilyCarAgentApp: App {
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(VehicleSyncAppDelegate.self) private var vehicleSyncDelegate
    #endif
    var body: some Scene {
        WindowGroup {
            ContentView()
                #if DEBUG && os(iOS)
                .modifier(Phase4DiagnosticControl())
                #endif
        }
    }
}
