import Foundation

struct ProbeEvent: Codable, Equatable {
    let eventID: UUID
    let createdAt: String
    let kind = "synthetic_offline_upload"

    init(id: UUID = UUID(), now: Date = Date()) {
        eventID = id
        createdAt = ISO8601DateFormatter().string(from: now)
    }

    enum CodingKeys: String, CodingKey {
        case eventID = "event_id", createdAt = "created_at", kind
    }
}

struct ProbeDiagnostic: Codable, Identifiable {
    var id: UUID { event.eventID }
    let event: ProbeEvent
    var persisted = false
    var registered = false
    var taskIdentifier: Int?
    var status = "created"
    var lastError: String?
    var updatedAt = ISO8601DateFormatter().string(from: Date())

    mutating func update(_ status: String, error: String? = nil) {
        self.status = status
        lastError = error
        updatedAt = ISO8601DateFormatter().string(from: Date())
    }
}

enum ProbeUploadError: Error {
    case invalidEndpoint
}

func probeEndpoint(_ text: String) throws -> URL {
    guard let parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
          parts.scheme == "https", let host = parts.host, !host.isEmpty,
          parts.user == nil, parts.password == nil, parts.fragment == nil,
          parts.query == nil, let url = parts.url else {
        throw ProbeUploadError.invalidEndpoint
    }
    return url
}

// Accessed only on the main actor in the app. Each event has its own immutable payload.
struct ProbeStore {
    let root: URL

    func prepare() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                                             ofItemAtPath: root.path)
        var directory = root
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        #endif
    }

    func payload(_ id: UUID) -> URL { root.appendingPathComponent(id.uuidString + ".json") }

    func persist(_ event: ProbeEvent) throws {
        try prepare()
        try JSONEncoder().encode(event).write(to: payload(event.eventID), options: .atomic)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                                             ofItemAtPath: payload(event.eventID).path)
        #endif
    }

    func save(_ diagnostic: ProbeDiagnostic) throws {
        try JSONEncoder().encode(diagnostic).write(
            to: root.appendingPathComponent(diagnostic.id.uuidString + ".diagnostic"), options: .atomic)
    }

    func load() throws -> (records: [ProbeDiagnostic], readFailureCount: Int) {
        try prepare()
        let files = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "diagnostic" }
        var records: [ProbeDiagnostic] = []
        var readFailureCount = 0
        for file in files {
            do {
                records.append(try JSONDecoder().decode(ProbeDiagnostic.self, from: Data(contentsOf: file)))
            } catch {
                readFailureCount += 1
            }
        }
        return (records.sorted { $0.event.createdAt > $1.event.createdAt }, readFailureCount)
    }
}
