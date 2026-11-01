import Foundation
#if canImport(Combine)
import Combine
#endif

/// Screen-local data only. Every completion is fenced by identity and screen lifetime.
@MainActor final class FamilyModel: ObservableObject {
    enum AddressStage { case view, edit, verifying, confirm, saving }
    @Published private(set) var profile: FamilyProfile?
    @Published private(set) var loading = false
    @Published private(set) var loadError = false
    @Published private(set) var rolePending = Set<UUID>()
    @Published private(set) var roleErrors = Set<UUID>()
    @Published private(set) var stage = AddressStage.view
    @Published private(set) var draft = ""
    @Published private(set) var candidate: AddressResult?
    @Published private(set) var addressError: String?
    @Published private(set) var codePending = false
    @Published var codeConfirmation = false
    @Published private(set) var codeError = false
    @Published private(set) var invitation: String?
    private let gateway: any FamilyGateway
    private var identity: ChatIdentity?
    private var generation = 0
    private var tasks: [String: Task<Void, Never>] = [:]
    init(gateway: any FamilyGateway) { self.gateway = gateway }
    var current: Bool { identity != nil && identity == gateway.familyIdentity }
    var visibleProfile: FamilyProfile? { current ? profile : nil }
    var canManage: Bool { current && !loading && !loadError && profile?.can_edit_roles == true }
    var addressBusy: Bool { stage == .verifying || stage == .saving }
    func start() {
        guard let who = gateway.familyIdentity else { stop(); return }
        guard identity != who else { return }
        stop(); identity = who; refresh()
    }
    func stop() {
        generation += 1
        tasks.values.forEach { $0.cancel() }; tasks.removeAll(); identity = nil
        profile = nil; loading = false; loadError = false; rolePending = []; roleErrors = []
        stage = .view; draft = ""; candidate = nil; addressError = nil
        codePending = false; codeConfirmation = false; codeError = false; invitation = nil
    }
    private func run(_ key: String, _ operation: FamilyOperation,
                     success: @escaping @MainActor (FamilyReply) throws -> Void,
                     failure: @escaping @MainActor (Error) -> Void,
                     finish: @escaping @MainActor () -> Void = {}) {
        guard current, let who = identity, tasks[key] == nil else { return }
        let version = generation
        tasks[key] = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.familyRequest(identity: who, operation: operation)
                guard let self, self.current, self.generation == version, !Task.isCancelled else { return }
                try success(reply)
            } catch {
                guard let self, self.current, self.generation == version, !Task.isCancelled else { return }
                failure(error)
            }
            guard let self, self.current, self.generation == version else { return }
            finish(); self.tasks[key] = nil
        }
    }
    func refresh() {
        guard current, !loading, rolePending.isEmpty, !addressBusy, !codePending else { return }
        loading = true; loadError = false
        run("load", .profile, success: { [self] reply in
            guard case .profile(let data) = reply else { throw AuthFailure.invalidResponse }
            profile = try data.validated()
        }, failure: { [self] _ in loadError = true }, finish: { [self] in loading = false })
    }
    func role(_ id: UUID, _ role: FamilyRole) {
        guard canManage, let member = profile?.members.first(where: { $0.id == id }), member.role != role,
              !rolePending.contains(id) else { return }
        rolePending.insert(id); roleErrors.remove(id)
        run("role-\(id)", .role(id, role), success: { [self] reply in
            guard case .member(let updated) = reply, updated.id == id else { throw AuthFailure.invalidResponse }
            let members = profile?.members.map { $0.id == id ? updated : $0 } ?? []
            profile?.members = members
        }, failure: { [self] _ in roleErrors.insert(id) }, finish: { [self] in rolePending.remove(id) })
    }
    func editAddress() {
        guard canManage, !addressBusy else { return }
        draft = profile?.home_address ?? ""; candidate = nil; addressError = nil; stage = .edit
    }
    func changeDraft(_ value: String) {
        guard canManage, stage == .edit else { return }
        draft = value; candidate = nil; addressError = nil
    }
    func reviseAddress() {
        guard canManage, !addressBusy else { return }
        candidate = nil; addressError = nil; stage = .edit
    }
    func cancelAddress() {
        guard !addressBusy else { return }
        candidate = nil; draft = ""; addressError = nil; stage = .view
    }
    func verifyAddress() {
        guard canManage, stage == .edit else { return }
        guard !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, draft.unicodeScalars.count <= 200 else {
            addressError = "יש להזין עיר, רחוב ומספר בית, עד 200 תווים."; return
        }
        stage = .verifying; addressError = nil
        run("address", .resolve(draft), success: { [self] reply in
            guard case .candidate(let value) = reply,
                  [value.normalized_address, value.display_address, value.resolution_token].allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else { throw AuthFailure.invalidResponse }
            candidate = value; stage = .confirm
        }, failure: { [self] _ in stage = .edit; addressError = "לא ניתן לאמת את הכתובת. בדקו את הפרטים ונסו שוב." })
    }
    func confirmAddress() {
        guard canManage, stage == .confirm, let candidate else { return }
        stage = .saving; addressError = nil
        run("address", .address(candidate.resolution_token), success: { [self] reply in
            guard case .address(let address) = reply, !address.isEmpty else { throw AuthFailure.invalidResponse }
            profile?.home_address = address; self.candidate = nil; draft = ""; stage = .view
        }, failure: { [self] error in
            if case AuthFailure.rejected(_, "ADDRESS_RESOLUTION_EXPIRED") = error {
                self.candidate = nil; stage = .edit; addressError = "תוקף בדיקת הכתובת פג. יש לבדוק אותה מחדש."
            } else {
                stage = .confirm; addressError = "לא ניתן לאשר שהכתובת עודכנה. אפשר לנסות שוב או לחזור לעריכה ולבדוק מחדש."
            }
        })
    }
    func askRegenerate() { if canManage && !codePending && invitation == nil { codeConfirmation = true; codeError = false } }
    func regenerate() {
        guard canManage, codeConfirmation, !codePending, invitation == nil else { return }
        codePending = true; codeError = false
        run("code", .regenerate, success: { [self] reply in
            guard case .code(let code) = reply, FamilyInvitation.validCode(code) else { throw AuthFailure.invalidResponse }
            profile?.family_code = code; codeConfirmation = false
        }, failure: { [self] _ in codeError = true }, finish: { [self] in codePending = false })
    }
    func copyCode() -> String? {
        guard !loading, !loadError, !codePending else { return nil }
        return visibleProfile?.family_code
    }
    func share() {
        guard invitation == nil, let code = copyCode() else { return }
        invitation = FamilyInvitation.message(code: code)
    }
    func closeShare() { invitation = nil; if current { refresh() } }
}
