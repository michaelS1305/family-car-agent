#if DEBUG && os(iOS)
import SwiftUI
import UIKit

/// Dev-only transfer to a deliberately unimplemented route. A 404 is the expected
/// network result. No vehicle context or Authorization header is constructed.
@MainActor enum Phase4DeviceDiagnostics {
    static let identifier = AppEnvironment.development.bundleIdentifier + ".phase4-diagnostic.v1"
    private static var transport: VehicleBackgroundUploadTransport?
    private static var submittedInProcess = false
    private static var preparing = false
    private static var bodyURL: URL {
        URL.applicationSupportDirectory.appendingPathComponent("phase4-synthetic.json")
    }
    static func record(_ key: String, _ value: String) {
        UserDefaults.standard.set(value, forKey: "phase4." + key)
    }
    static func sample(_ key: String) {
        let protected = UIApplication.shared.isProtectedDataAvailable ? "available" : "unavailable"
        let status = KeychainVault(environment: .development).diagnosticRead()
        record(key, "protected data " + protected + " · " + status)
    }
    private static func session() throws -> VehicleBackgroundUploadTransport {
        if let transport { return transport }
        let t = try VehicleBackgroundUploadTransport(identifier: identifier)
        t.onCompletion = { result in
            sample("callback")
            record("transfer", !result.transportFailed && result.status == 404 ? "expected 404 received" : "unexpected transfer result")
            try? FileManager.default.removeItem(at: bodyURL)
        }
        transport = t
        return t
    }
    static func register() async {
        guard !preparing else { return }
        preparing = true
        defer { preparing = false }
        do {
            let t = try session()
            guard await t.allTasks().isEmpty else { record("transfer", "already registered"); return }
            try FileManager.default.createDirectory(at: bodyURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("{}".utf8).write(to: bodyURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            var request = URLRequest(url: AppEnvironment.development.backendURL.appendingPathComponent("__fca_debug__/phase4-no-handler"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let task = try t.create(request: request, file: bodyURL, tag: "phase4-test")
            submittedInProcess = true
            record("callback", "pending"); record("restoration", "not observed")
            record("transfer", "registered"); t.resume(task.identifier)
        } catch { record("transfer", "registration failed") }
    }
    static func restore(_ completion: @escaping () -> Void) throws {
        let t = try session()
        record("restoration", submittedInProcess ? "system callback / existing process" : "system callback / new process")
        sample("restoreRead")
        t.handleBackgroundEvents(completion: completion)
    }
    static func refresh() async {
        do {
            let sessions = try VehicleSessionRuntime.shared.get().sessions
            guard let current = sessions.session, current.activated else { record("refresh", "session unavailable"); return }
            let generation = sessions.generation
            // Exercise the expiration branch without changing the stored expiry or clock.
            _ = try await sessions.access(owner: current.owner, now: .distantFuture)
            record("refresh", sessions.generation == generation && sessions.session?.owner == current.owner ? "refresh succeeded" : "identity changed")
        } catch { record("refresh", "refresh unavailable") }
    }
}

struct Phase4DiagnosticControl: ViewModifier {
    @State private var visible = false
    @State private var refreshing = false
    @AppStorage("phase4.migration") private var migration = "not observed"
    @AppStorage("phase4.read") private var read = "not sampled"
    @AppStorage("phase4.refresh") private var refresh = "not tested"
    @AppStorage("phase4.transfer") private var transfer = "not registered"
    @AppStorage("phase4.callback") private var callback = "not sampled"
    @AppStorage("phase4.restoration") private var restoration = "not observed"
    @AppStorage("phase4.restoreRead") private var restoreRead = "not sampled"

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottomLeading) {
            Button("P4") { visible = true }.buttonStyle(.bordered).accessibilityLabel("Phase 4 diagnostics")
        }.sheet(isPresented: $visible) {
            List {
                Text("FCA Dev · Phase 4")
                Text("Migration: " + migration)
                Button("Read stored session") { Phase4DeviceDiagnostics.sample("read") }
                Text(read)
                Button("Exercise expiry and refresh Dev session") {
                    refreshing = true
                    Task { await Phase4DeviceDiagnostics.refresh(); refreshing = false }
                }.disabled(refreshing)
                Text(refresh)
                Button("Queue synthetic transfer") { Task { await Phase4DeviceDiagnostics.register() } }
                Text(transfer); Text("Completion: " + callback)
                Text("Restoration: " + restoration); Text(restoreRead)
                Button("Close") { visible = false }
            }
        }
    }
}
#endif
