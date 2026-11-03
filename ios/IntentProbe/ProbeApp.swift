import SwiftUI
import UIKit
import AppIntents

#if DEBUG
struct FCATestOfflineUploadIntent: AppIntent {
    static let title: LocalizedStringResource = "FCA Test Offline Upload"
    static let description = IntentDescription("Queues a synthetic file-backed background upload to a configured test endpoint.")
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> & ProvidesDialog {
        let message = await ProbeUploader.shared.enqueue()
        return .result(value: message, dialog: IntentDialog(stringLiteral: message))
    }
}
#endif

final class ProbeAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        guard identifier == ProbeUploader.sessionID else {
            completionHandler()
            return
        }
        ProbeUploader.shared.backgroundCompletion = completionHandler
    }
}

@main
struct ProbeApp: App {
    @UIApplicationDelegateAdaptor(ProbeAppDelegate.self) private var delegate
    var body: some Scene { WindowGroup { ProbeDiagnosticsView() } }
}

private struct ProbeDiagnosticsView: View {
    @StateObject private var uploader = ProbeUploader.shared
    @State private var endpoint = UserDefaults.standard.string(forKey: "probeUploadEndpoint") ?? ""
    @State private var configurationMessage = ""
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            List {
                Section("Dedicated test endpoint") {
                    Text("Synthetic events only. Use a test HTTPS receiver that records event_id and its own UTC receipt time. Never enter an FCA production endpoint or credentials.")
                    TextField("https://your-test-receiver/path", text: $endpoint)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button("Save test endpoint") {
                        do {
                            let url = try probeEndpoint(endpoint)
                            UserDefaults.standard.set(url.absoluteString, forKey: "probeUploadEndpoint")
                            configurationMessage = "Saved locally. Existing tasks retain their original destination."
                        } catch {
                            configurationMessage = "Enter an HTTPS URL without credentials, query or fragment."
                        }
                    }
                    Text(configurationMessage)
                }
                Section("Experiment") {
                    Text("Run FCA Test Offline Upload in Shortcuts while offline. Registration does not prove delivery. Check the server without reopening this app after restoring connectivity.")
                    Text(ProbeUploader.sessionID).font(.caption).textSelection(.enabled)
                    Button("Refresh local diagnostics") { uploader.reload() }
                    if let error = uploader.storageError { Text(error).foregroundStyle(.red) }
                }
                ForEach(uploader.diagnostics) { record in
                    Section(record.event.eventID.uuidString) {
                        Text("Created UTC: \(record.event.createdAt)")
                        Text("Persisted: \(record.persisted ? "yes" : "no")")
                        Text("Task registered: \(record.registered ? "yes" : "no")")
                        Text("Task ID: \(record.taskIdentifier.map(String.init) ?? "none")")
                        Text("Status: \(record.status)")
                        Text("Updated UTC: \(record.updatedAt)")
                        Text("Last error: \(record.lastError ?? "none")")
                    }.textSelection(.enabled)
                }
            }
            .navigationTitle("FCA Intent Probe")
            .onChange(of: scenePhase) { _, phase in if phase == .active { uploader.reload() } }
        }
    }
}
