#if canImport(UIKit)
import Foundation
import UIKit

@MainActor final class VehicleBackgroundUploadTransport: NSObject, VehicleUploadTransport, URLSessionDataDelegate {
    private static var liveIdentifiers = Set<String>()
    let identifier: String
    private var session: URLSession!
    private var known: [Int64: URLSessionTask] = [:]
    private var bodies: [Int: Data] = [:]
    private var oversized = Set<Int>()
    private var callbacks: Task<Void, Never>?
    private var backgroundCompletion: (() -> Void)?
    private var finishedEvents = false
    private var pendingCompletions: [VehicleUploadCompletion] = []
    var onCompletion: (@MainActor (VehicleUploadCompletion) async -> Void)? {
        didSet {
            guard onCompletion != nil else { return }
            let pending = pendingCompletions; pendingCompletions.removeAll()
            for result in pending { deliver(result) }
            if finishedEvents { finishAfterCallbacks() }
        }
    }

    static func configuration(identifier: String) -> URLSessionConfiguration {
        let config = URLSessionConfiguration.background(withIdentifier: identifier)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.allowsCellularAccess = true
        config.allowsExpensiveNetworkAccess = true
        config.allowsConstrainedNetworkAccess = true
        config.waitsForConnectivity = true
        config.timeoutIntervalForResource = 24 * 60 * 60
        config.httpCookieStorage = nil; config.urlCredentialStorage = nil; config.urlCache = nil
        return config
    }

    init(identifier: String) throws {
        guard Self.liveIdentifiers.insert(identifier).inserted else { throw VehicleQueueError.conflict }
        self.identifier = identifier
        super.init()
        session = URLSession(configuration: Self.configuration(identifier: identifier), delegate: self, delegateQueue: .main)
    }

    func allTasks() async -> [VehicleUploadTask] {
        let tasks = await session.allTasks
        known = Dictionary(uniqueKeysWithValues: tasks.map { (Int64($0.taskIdentifier), $0) })
        return tasks.filter { $0.state != .completed }.map(Self.snapshot)
    }

    func create(request: URLRequest, file: URL, tag: String) throws -> VehicleUploadTask {
        guard request.url?.scheme == "https", request.httpMethod == "POST", file.isFileURL else {
            throw VehicleQueueError.invalidInput
        }
        let task = session.uploadTask(with: request, fromFile: file)
        task.taskDescription = tag
        known[Int64(task.taskIdentifier)] = task
        return Self.snapshot(task)
    }

    func resume(_ task: Int64) { known[task]?.resume() }
    func cancel(_ task: Int64) { known[task]?.cancel() }

    /// Install before reconstruction when possible; also handles already-drained callbacks.
    func handleBackgroundEvents(completion: @escaping () -> Void) {
        backgroundCompletion = completion
        if finishedEvents { finishAfterCallbacks() }
    }

    /// Teardown only after the future owner has reconciled/cancelled outstanding work.
    func invalidate() { session.invalidateAndCancel() }

    private static func snapshot(_ task: URLSessionTask) -> VehicleUploadTask {
        let state: VehicleUploadTask.State
        switch task.state {
        case .running: state = .running
        case .suspended: state = .suspended
        case .canceling: state = .cancelling
        default: state = .completed
        }
        return VehicleUploadTask(identifier: Int64(task.taskIdentifier), tag: task.taskDescription, state: state)
    }

    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let id = dataTask.taskIdentifier
        DispatchQueue.main.async {
            self.finishedEvents = false
            guard !self.oversized.contains(id) else { return }
            var body = self.bodies[id] ?? Data()
            guard body.count + data.count <= 65_536 else {
                self.oversized.insert(id); self.bodies.removeValue(forKey: id); dataTask.cancel(); return
            }
            body.append(data); self.bodies[id] = body
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let id = task.taskIdentifier, tag = task.taskDescription
        let response = task.response as? HTTPURLResponse
        let status = response?.statusCode, retry = response?.value(forHTTPHeaderField: "Retry-After")
        // Background transfers can follow redirects without the ordinary redirect
        // callback. Never accept an admission body from a changed response URL.
        let failed = error != nil || response?.url != task.originalRequest?.url
        DispatchQueue.main.async {
            self.finishedEvents = false
            let result = VehicleUploadCompletion(task: Int64(id), tag: tag, status: status,
                body: self.bodies.removeValue(forKey: id) ?? Data(), retryAfter: retry,
                transportFailed: failed || self.oversized.remove(id) != nil)
            self.known.removeValue(forKey: Int64(id))
            self.deliver(result)
        }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async { self.finishedEvents = true; self.finishAfterCallbacks() }
    }

    private func finishAfterCallbacks() {
        guard onCompletion != nil else { return }
        let previous = callbacks
        callbacks = Task { @MainActor in
            await previous?.value
            let completion = self.backgroundCompletion
            self.backgroundCompletion = nil
            if completion != nil { self.finishedEvents = false }
            completion?()
        }
    }

    private func deliver(_ result: VehicleUploadCompletion) {
        guard let handler = onCompletion else { pendingCompletions.append(result); return }
        let previous = callbacks
        callbacks = Task { @MainActor in
            await previous?.value
            await handler(result)
        }
    }

    nonisolated func urlSession(_ session: URLSession, didBecomeInvalidWithError error: Error?) {
        DispatchQueue.main.async { Self.liveIdentifiers.remove(self.identifier) }
    }
}

/// Reattach only to the exact device scope explicitly enabled in this login.
@MainActor final class VehicleSyncAppDelegate: NSObject, UIApplicationDelegate {
    private(set) static var restorationUnavailable = false

    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            do {
                #if DEBUG && os(iOS)
                if identifier == Phase4DeviceDiagnostics.identifier {
                    try Phase4DeviceDiagnostics.restore(completionHandler)
                    return
                }
                #endif
                let transport = try await VehicleSessionRuntime.shared.get().restore(identifier)
                guard transport.identifier == identifier else { throw VehicleQueueError.contextUnavailable }
                transport.handleBackgroundEvents(completion: completionHandler)
            } catch {
                Self.restorationUnavailable = true
                completionHandler()
            }
        }
    }
}
#endif
