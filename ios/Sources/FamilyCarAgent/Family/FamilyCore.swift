import Foundation

enum FamilyRole: String, CaseIterable, Sendable {
    case none, parent, child
    var label: String { switch self { case .none: "ללא תפקיד"; case .parent: "הורה"; case .child: "ילד/ילדה" } }
}
struct FamilyMember: Decodable, Identifiable, Sendable {
    let id: UUID
    let name: String
    let role: FamilyRole
    let admin: Bool
    enum CodingKeys: String, CodingKey { case member_ref, name, role, is_family_admin }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .member_ref)
        name = try c.decode(String.self, forKey: .name)
        admin = try c.decode(Bool.self, forKey: .is_family_admin)
        guard c.contains(.role) else { throw AuthFailure.invalidResponse }
        if try c.decodeNil(forKey: .role) { role = .none }
        else {
            let value = try c.decode(String.self, forKey: .role)
            guard let parsed = FamilyRole(rawValue: value), parsed != .none else { throw AuthFailure.invalidResponse }
            role = parsed
        }
    }
}
struct FamilyProfile: Decodable, Sendable {
    let name: String
    var home_address: String
    var family_code: String
    let can_edit_roles: Bool
    var members: [FamilyMember]
    func validated() throws -> Self {
        guard FamilyInvitation.validCode(family_code), Set(members.map(\.id)).count == members.count else {
            throw AuthFailure.invalidResponse
        }
        return self
    }
}
struct FamilyAddressUpdate: Decodable, Sendable { let home_address: String }
enum FamilyOperation: Sendable {
    case profile, role(UUID, FamilyRole), resolve(String), address(String), regenerate
    var path: String {
        switch self {
        case .profile: "/api/family"
        case .role(let id, _): "/api/family/members/\(id.uuidString.lowercased())/role"
        case .resolve: "/api/family/address/resolve"
        case .address: "/api/family/address"
        case .regenerate: "/api/family/code/regenerate"
        }
    }
    var method: String {
        switch self { case .profile: "GET"; case .role, .address: "PATCH"; case .resolve, .regenerate: "POST" }
    }
    func body() throws -> Data? {
        let fields: [String: String?]
        switch self {
        case .profile: return nil
        case .role(_, let role): fields = ["role": role == .none ? nil : role.rawValue]
        case .resolve(let value): fields = ["home_address": value]
        case .address(let token): fields = ["resolution_token": token]
        case .regenerate: fields = [:]
        }
        return try JSONEncoder().encode(fields)
    }
}
enum FamilyReply: Sendable {
    case profile(FamilyProfile), member(FamilyMember), candidate(AddressResult), address(String), code(String)
}
protocol FamilyTransport: Sendable {
    func family(token: String, operation: FamilyOperation) async throws -> FamilyReply
}
@MainActor protocol FamilyGateway: AnyObject {
    var familyIdentity: ChatIdentity? { get }
    func familyRequest(identity: ChatIdentity, operation: FamilyOperation) async throws -> FamilyReply
}
enum FamilyInvitation {
    static let applicationLink = "[קישור לאפליקציה — יתווסף בקרוב]"
    static func validCode(_ code: String) -> Bool {
        code.utf8.count == 6 && code.utf8.allSatisfy { (97...122).contains($0) || (48...57).contains($0) }
    }
    static func message(code: String) -> String? {
        guard validCode(code) else { return nil }
        return """
        היי! 👋

        רוצה להצטרף למשפחה שלנו ב־Family Car Agent? 🚗

        תקבל סוכן חכם אישי שיעזור לך לנהל את הרכבים המשפחתיים, לעקוב אחרי השימוש בהם ולתאם נסיעות בקלות.

        📲 להצטרפות לאפליקציה:
        \(applicationLink)

        🔑 הקוד המשפחתי שלנו:
        \(code)

        🔒 חשוב: הקוד המשפחתי מיועד לבני המשפחה בלבד. נא לשמור עליו ולא להעביר אותו לאנשים מחוץ למשפחה.
        """
    }
}
