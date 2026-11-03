import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

#if canImport(Combine)
final class FakeUploadTask: URLSessionUploadTask, @unchecked Sendable {
    var resumed = false
    var cancelled = false
    var httpResponse: HTTPURLResponse?
    override var response: URLResponse? { httpResponse }
    override var taskIdentifier: Int { 42 }
    override func resume() { resumed = true }
    override func cancel() { cancelled = true }
}

final class FakeUploadSession: URLSession, @unchecked Sendable {
    let upload = FakeUploadTask()
    var request: URLRequest?
    var file: URL?
    var onUpload: ((URL) -> Void)?
    override func uploadTask(with request: URLRequest, fromFile fileURL: URL) -> URLSessionUploadTask {
        self.request = request
        file = fileURL
        onUpload?(fileURL)
        return upload
    }
}
#endif

@main
struct OfflineUploadProbeChecks {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ProbeStore(root: root)
        let event = ProbeEvent(now: Date(timeIntervalSince1970: 0))
        let data = try JSONEncoder().encode(event)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: String]
        precondition(Set(json.keys) == ["event_id", "created_at", "kind"])
        precondition(json["created_at"] == "1970-01-01T00:00:00Z")
        precondition(json["event_id"] == event.eventID.uuidString)
        precondition(json["kind"] == "synthetic_offline_upload")
        try store.persist(event)
        let persisted = try JSONDecoder().decode(ProbeEvent.self, from: Data(contentsOf: store.payload(event.eventID)))
        precondition(persisted == event)
        var record = ProbeDiagnostic(event: event)
        record.persisted = true
        record.update("registration_failed", error: "Synthetic error")
        try store.save(record)
        let restored = try ProbeStore(root: root).load().records
        precondition(restored.count == 1 && restored[0].persisted)
        precondition(restored[0].lastError == "Synthetic error" && !restored[0].registered)
        let corrupt = root.appendingPathComponent("corrupt.diagnostic")
        try Data("invalid JSON PRIVATE_SENTINEL".utf8).write(to: corrupt)
        let unreadable = root.appendingPathComponent("unreadable.diagnostic")
        try FileManager.default.createDirectory(at: unreadable, withIntermediateDirectories: false)
        let partial = try store.load()
        precondition(partial.records.count == 1 && partial.records[0].id == event.eventID)
        precondition(partial.readFailureCount == 2)
        try FileManager.default.removeItem(at: corrupt)
        try FileManager.default.removeItem(at: unreadable)
        let clean = try store.load()
        precondition(clean.readFailureCount == 0)
        let second = ProbeEvent()
        try store.persist(second)
        precondition(second.eventID != event.eventID)
        precondition(FileManager.default.fileExists(atPath: store.payload(event.eventID).path))
        for invalid in ["", "http://example.invalid", "https://user:password@example.invalid", "https://example.invalid/#fragment", "https://example.invalid/?secret=value"] {
            do { _ = try probeEndpoint(invalid); preconditionFailure("Invalid endpoint accepted") }
            catch ProbeUploadError.invalidEndpoint { }
        }
        _ = try probeEndpoint("https://example.invalid/events")
        let blocked = root.appendingPathComponent("not-a-directory")
        try Data().write(to: blocked)
        do { try ProbeStore(root: blocked).persist(event); preconditionFailure("Persistence should fail") }
        catch { }
        print("PASS: event JSON, persistence/reload, distinct events, endpoint validation, storage failure")

        #if canImport(Combine)
        let config = ProbeUploader.configuration()
        precondition(config.identifier == ProbeUploader.sessionID)
        precondition(config.sessionSendsLaunchEvents && !config.isDiscretionary)
        precondition(config.allowsCellularAccess && config.allowsExpensiveNetworkAccess)
        precondition(config.allowsConstrainedNetworkAccess && config.waitsForConnectivity)
        let fake = FakeUploadSession()
        let uploader = ProbeUploader(store: store, sessionFactory: { _, _ in fake })
        let message = uploader.enqueue(endpoint: "https://example.invalid/events")
        precondition(fake.upload.resumed && !fake.upload.cancelled)
        precondition(fake.request?.httpMethod == "POST")
        precondition(fake.request?.value(forHTTPHeaderField: "Content-Type") == "application/json")
        precondition(fake.request?.httpBody == nil)
        let sent = try JSONDecoder().decode(ProbeEvent.self, from: Data(contentsOf: fake.file!))
        precondition(fake.upload.taskDescription == sent.eventID.uuidString)
        precondition(message.contains("delivery is unconfirmed"))
        precondition(uploader.diagnostics.first?.registered == true)
        uploader.urlSession(fake, task: fake.upload,
                            didCompleteWithError: NSError(domain: NSURLErrorDomain, code: -1009,
                                userInfo: [NSLocalizedDescriptionKey: "PRIVATE_RESPONSE_SENTINEL"]))
        var finished = false
        uploader.backgroundCompletion = { finished = true }
        uploader.urlSessionDidFinishEvents(forBackgroundURLSession: fake)
        // Drain main-queue delegate work, including the background completion callback.
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        precondition(finished && uploader.backgroundCompletion == nil)
        let completed = try store.load().records.first { $0.id == sent.eventID }!
        precondition(completed.status == "transport_failed_delivery_unknown")
        precondition(completed.lastError == "URLSession error code -1009")
        fake.upload.httpResponse = HTTPURLResponse(url: URL(string: "https://example.invalid")!,
                                                  statusCode: 204, httpVersion: nil, headerFields: nil)
        uploader.urlSession(fake, task: fake.upload, didCompleteWithError: nil)
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        let successful = try store.load().records.first { $0.id == sent.eventID }!
        precondition(successful.status == "http_success_verify_server_receipt")
        precondition(successful.lastError == nil)
        fake.upload.httpResponse = HTTPURLResponse(url: URL(string: "https://example.invalid")!,
                                                  statusCode: 503, httpVersion: nil, headerFields: nil)
        uploader.urlSession(fake, task: fake.upload, didCompleteWithError: nil)
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        let rejected = try store.load().records.first { $0.id == sent.eventID }!
        precondition(rejected.status == "http_rejected" && rejected.lastError == "HTTP 503")
        let unavailable = FakeUploadSession()
        let noEndpoint = ProbeUploader(store: store, sessionFactory: { _, _ in unavailable })
        _ = noEndpoint.enqueue(endpoint: "")
        precondition(!unavailable.upload.resumed && unavailable.request == nil)
        precondition(noEndpoint.diagnostics.first?.status == "registration_failed")
        let badStore = ProbeUploader(store: ProbeStore(root: blocked), sessionFactory: { _, _ in unavailable })
        _ = badStore.enqueue(endpoint: "https://example.invalid/events")
        precondition(!unavailable.upload.resumed)
        precondition(badStore.diagnostics.first?.status == "persistence_failed")
        let mappingFailure = FakeUploadSession()
        mappingFailure.onUpload = { payload in
            let diagnostic = payload.deletingPathExtension().appendingPathExtension("diagnostic")
            try! FileManager.default.removeItem(at: diagnostic)
            try! FileManager.default.createDirectory(at: diagnostic, withIntermediateDirectories: false)
        }
        let failedMapping = ProbeUploader(store: store, sessionFactory: { _, _ in mappingFailure })
        let failureMessage = failedMapping.enqueue(endpoint: "https://example.invalid/events")
        precondition(failureMessage.contains("cancelled"))
        precondition(mappingFailure.upload.cancelled && !mappingFailure.upload.resumed)
        precondition(failedMapping.diagnostics.first?.registered == false)
        precondition(failedMapping.diagnostics.first?.taskIdentifier == nil)
        precondition(failedMapping.diagnostics.first?.status == "registration_cancelled")
        precondition(failedMapping.storageError?.contains("memory-only") == true)
        failedMapping.urlSession(mappingFailure, task: mappingFailure.upload,
                                 didCompleteWithError: NSError(domain: NSURLErrorDomain, code: -999))
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        precondition(failedMapping.diagnostics.first?.status == "registration_cancelled")
        // Make the path writable again: the callback must not have retried its save.
        let failedPath = mappingFailure.file!.deletingPathExtension().appendingPathExtension("diagnostic")
        try FileManager.default.removeItem(at: failedPath)
        failedMapping.urlSession(mappingFailure, task: mappingFailure.upload,
                                 didCompleteWithError: NSError(domain: NSURLErrorDomain, code: -999))
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { continuation.resume() }
        }
        precondition(!FileManager.default.fileExists(atPath: failedPath.path))
        try Data("invalid".utf8).write(to: corrupt)
        uploader.reload()
        precondition(!uploader.diagnostics.isEmpty)
        precondition(uploader.storageError?.contains("1 diagnostic record") == true)
        print("PASS: background configuration, file upload registration/resume, delegate diagnostics, completion, failure guards")
        #else
        print("SKIP: Apple URLSession/Combine runtime tests require macOS")
        #endif
    }
}
