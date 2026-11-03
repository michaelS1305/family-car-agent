import Foundation
import Combine

@MainActor
final class ProbeUploader: NSObject, ObservableObject, URLSessionDataDelegate {
    static let shared = ProbeUploader()
    nonisolated static let sessionID = "com.familycaragent.intentprobe.offline-upload.v1"
    @Published private(set) var diagnostics: [ProbeDiagnostic] = []
    @Published private(set) var storageError: String?
    var backgroundCompletion: (() -> Void)?
    private let store: ProbeStore
    private var session: URLSession!

    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.background(withIdentifier: sessionID)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.allowsCellularAccess = true
        config.allowsExpensiveNetworkAccess = true
        config.allowsConstrainedNetworkAccess = true
        config.waitsForConnectivity = true
        config.timeoutIntervalForResource = 24 * 60 * 60
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        return config
    }

    init(store: ProbeStore = ProbeStore(root: FileManager.default.urls(for: .applicationSupportDirectory,
                                                        in: .userDomainMask)[0]
            .appendingPathComponent("OfflineUploadProbe", isDirectory: true)),
         sessionFactory: ((URLSessionConfiguration, URLSessionDelegate) -> URLSession)? = nil) {
        self.store = store
        super.init()
        reload()
        // Recreate the same delegate-backed session on ordinary and background launch.
        session = sessionFactory?(Self.configuration(), self)
            ?? URLSession(configuration: Self.configuration(), delegate: self, delegateQueue: .main)
    }

    func reload() {
        do {
            let loaded = try store.load()
            diagnostics = loaded.records
            storageError = loaded.readFailureCount == 0 ? nil
                : "Could not read \(loaded.readFailureCount) diagnostic record(s); valid records were loaded."
        } catch {
            storageError = "Local diagnostics could not be read."
        }
    }

    private func publish(_ record: ProbeDiagnostic) {
        if let index = diagnostics.firstIndex(where: { $0.id == record.id }) {
            diagnostics[index] = record
        } else {
            diagnostics.insert(record, at: 0)
        }
    }

    @discardableResult
    private func save(_ record: ProbeDiagnostic) -> Bool {
        publish(record)
        do {
            try store.save(record)
            return true
        } catch {
            storageError = "Diagnostic persistence failed; displayed state may be memory-only."
            return false
        }
    }

    func enqueue(endpoint: String? = nil) -> String {
        var record = ProbeDiagnostic(event: ProbeEvent())
        do {
            try store.persist(record.event)
            record.persisted = true
        } catch {
            record.update("persistence_failed", error: "Local event persistence failed.")
            storageError = "Event persistence failed; displayed state is memory-only."
            publish(record)
            return "Event persistence failed. Upload was not started."
        }
        guard save(record) else {
            record.update("diagnostic_persistence_failed", error: "Event saved, but diagnostics could not be persisted. Upload was not started.")
            publish(record)
            return "Event saved, but diagnostics could not be persisted. Upload was not started."
        }
        do {
            let endpoint = try probeEndpoint(endpoint ?? UserDefaults.standard.string(forKey: "probeUploadEndpoint") ?? "")
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let task = session.uploadTask(with: request, fromFile: store.payload(record.id))
            task.taskDescription = record.id.uuidString
            record.registered = true
            record.taskIdentifier = task.taskIdentifier
            record.update("task_registered_delivery_unconfirmed")
            // Persist the task mapping before handing execution to the system.
            guard save(record) else {
                task.cancel()
                record.registered = false
                record.taskIdentifier = nil
                record.update("registration_cancelled", error: "Task mapping could not be persisted.")
                publish(record)
                return "Event saved, but upload registration was cancelled because diagnostics could not be saved."
            }
            task.resume()
            return "Event \(record.id.uuidString) saved. Background upload registered and resume requested. Server delivery is unconfirmed."
        } catch {
            record.update("registration_failed", error: "Configure a dedicated HTTPS test endpoint in the Probe first.")
            save(record)
            return "Event saved. Upload not registered: configure the test endpoint in the Probe."
        }
    }

    private func recordCompletion(taskID: Int, eventID: String?, status: Int?, errorCode: Int?) {
        guard let index = diagnostics.firstIndex(where: {
            if let eventID { return $0.id.uuidString == eventID }
            return $0.taskIdentifier == taskID
        }) else {
            storageError = "A background completion could not be associated with a persisted event."
            return
        }
        var record = diagnostics[index]
        // Cancellation after a failed mapping write must not overwrite that failure
        // or trigger another attempt to persist the same diagnostics.
        guard record.registered else { return }
        if let errorCode {
            record.update("transport_failed_delivery_unknown", error: "URLSession error code \(errorCode)")
        } else if let status {
            record.update((200..<300).contains(status) ? "http_success_verify_server_receipt" : "http_rejected",
                          error: (200..<300).contains(status) ? nil : "HTTP \(status)")
        } else {
            record.update("completion_without_http_response", error: "No HTTP status available.")
        }
        save(record)
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                               didCompleteWithError error: Error?) {
        let taskID = task.taskIdentifier
        let eventID = task.taskDescription
        let status = (task.response as? HTTPURLResponse)?.statusCode
        let errorCode = error.map { ($0 as NSError).code }
        DispatchQueue.main.async {
            self.recordCompletion(taskID: taskID, eventID: eventID, status: status, errorCode: errorCode)
        }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        // FIFO main queue delivery follows the preceding diagnostic writes.
        DispatchQueue.main.async {
            let completion = self.backgroundCompletion
            self.backgroundCompletion = nil
            completion?()
        }
    }
}
