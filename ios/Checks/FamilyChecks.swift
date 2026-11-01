import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@MainActor final class FamilyMock: FamilyGateway {
    var familyIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
    var calls: [FamilyOperation] = []
    var reply: FamilyReply!
    var error: AuthFailure?
    var pause = false
    var continuation: CheckedContinuation<Void, Never>?
    func familyRequest(identity: ChatIdentity, operation: FamilyOperation) async throws -> FamilyReply {
        calls.append(operation)
        let captured = reply!
        if pause { await withCheckedContinuation { continuation = $0 } }
        if let error { throw error }
        return captured
    }
    func release() { pause = false; continuation?.resume(); continuation = nil }
}
@main struct FamilyChecks {
    @MainActor static var count = 0
    @MainActor static func check(_ value: Bool, _ message: String) { precondition(value, message); count += 1 }
    @MainActor static func settle() async { for _ in 0..<60 { await Task.yield() }; try? await Task.sleep(for: .milliseconds(5)) }
    static func decode<T: Decodable>(_ type: T.Type, _ text: String) throws -> T { try JSONDecoder().decode(type, from: Data(text.utf8)) }
    @MainActor static func main() async throws {
        let id = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
        let memberJSON = "{\"member_ref\":\"\(id)\",\"name\":\"בדיקה\",\"role\":null,\"is_family_admin\":true}"
        let profileJSON = "{\"name\":\"משפחה\",\"home_address\":\"כתובת ישנה\",\"family_code\":\"abc123\",\"can_edit_roles\":true,\"members\":[\(memberJSON)]}"
        let profile = try decode(FamilyProfile.self, profileJSON).validated()
        check(profile.members[0].role == .none && profile.members[0].admin, "roles and admin separate")
        for role in ["parent", "child"] {
            let member = try decode(FamilyMember.self, memberJSON.replacingOccurrences(of: ":null", with: ":\"\(role)\""))
            check(member.role.rawValue == role, "role decoding")
        }
        for invalid in [memberJSON.replacingOccurrences(of: "\"role\":null,", with: ""), memberJSON.replacingOccurrences(of: ":null", with: ":\"admin\"")] {
            do { _ = try decode(FamilyMember.self, invalid); preconditionFailure("invalid role accepted") } catch { count += 1 }
        }
        var duplicate = profile; duplicate.members += profile.members
        do { _ = try duplicate.validated(); preconditionFailure("duplicate accepted") } catch { count += 1 }
        let body = try JSONSerialization.jsonObject(with: FamilyOperation.role(id, .none).body()!) as! [String: Any]
        check(body["role"] is NSNull, "none encoded as explicit null")
        check(FamilyOperation.role(id, .parent).method == "PATCH", "role PATCH")
        check(FamilyOperation.resolve("fixture").path == "/api/family/address/resolve", "resolve isolated from create")
        check(FamilyOperation.address("fixture").method == "PATCH", "address PATCH")
        let save = try JSONSerialization.jsonObject(with: FamilyOperation.address("fixture").body()!) as! [String: String]
        check(save == ["resolution_token": "fixture"], "save only token")
        check(FamilyOperation.regenerate.method == "POST", "regenerate POST")
        check(FamilyInvitation.message(code: "invalid") == nil, "invalid invitation rejected")
        check(!FamilyInvitation.validCode("abc123\n") && !FamilyInvitation.validCode("ABC123"), "strict code alphabet and length")
        let message = FamilyInvitation.message(code: "abc123")!
        check(message.contains("abc123") && message.contains(FamilyInvitation.applicationLink) && message.contains("מיועד לבני המשפחה בלבד"), "invitation exact data and warning")
        let candidate = try decode(AddressResult.self, "{\"display_address\":\"מאומתת\",\"normalized_address\":\"כתובת\",\"resolution_token\":\"fixture\",\"latitude\":31.0,\"longitude\":35.0}")
        check(candidate.location?.latitude == 31, "existing coordinate decoder")
        let absent = try decode(AddressResult.self, "{\"display_address\":\"מאומתת\",\"normalized_address\":\"כתובת\",\"resolution_token\":\"fixture\"}")
        check(absent.location == nil, "map fallback")
        let api = FamilyMock(); api.reply = .profile(profile)
        let model = FamilyModel(gateway: api)
        model.start(); model.start(); await settle()
        check(api.calls.count == 1 && model.visibleProfile != nil && model.canManage, "load once")
        check(model.copyCode() == "abc123", "explicit copy data")
        model.share(); model.share()
        check(model.invitation == message, "share repeated tap")
        model.closeShare(); await settle()
        check(model.invitation == nil && model.profile != nil, "share cancel retains profile")
        api.reply = .member(try decode(FamilyMember.self, memberJSON.replacingOccurrences(of: ":null", with: ":\"parent\"")))
        let beforeRole = api.calls.count
        model.role(id, .parent); model.role(id, .parent); await settle()
        check(api.calls.count == beforeRole + 1 && model.profile?.members[0].role == .parent, "role duplicate and success")
        api.error = .network
        model.role(id, .child); await settle()
        check(model.roleErrors.contains(id) && model.profile?.members[0].role == .parent && model.rolePending.isEmpty, "role failure preserves confirmed")
        api.error = nil
        model.editAddress(); model.changeDraft(" "); model.verifyAddress()
        check(model.stage == .edit && model.addressError != nil, "invalid draft")
        model.changeDraft("רחוב 1 עיר"); api.reply = .candidate(candidate)
        let beforeVerify = api.calls.count
        model.verifyAddress(); model.verifyAddress(); await settle()
        check(api.calls.count == beforeVerify + 1 && model.stage == .confirm, "verify once")
        model.reviseAddress(); check(model.candidate == nil && model.stage == .edit, "revision clears token")
        model.verifyAddress(); await settle(); api.error = .network
        model.confirmAddress(); await settle()
        check(model.stage == .confirm && model.profile?.home_address == "כתובת ישנה", "save failure preserves old")
        api.error = .rejected(409, "ADDRESS_RESOLUTION_EXPIRED")
        model.confirmAddress(); await settle()
        check(model.stage == .edit && model.candidate == nil, "expired token reverify")
        api.error = nil; api.reply = .candidate(candidate); model.verifyAddress(); await settle()
        api.reply = .address("כתובת חדשה"); let beforeSave = api.calls.count
        model.confirmAddress(); model.confirmAddress(); await settle()
        check(api.calls.count == beforeSave + 1 && model.profile?.home_address == "כתובת חדשה" && model.candidate == nil, "save confirmed only")
        model.editAddress(); model.cancelAddress()
        check(model.stage == .view && model.draft.isEmpty, "cancel edit")
        api.reply = .code("def456"); let beforeCode = api.calls.count
        model.regenerate(); await settle(); check(api.calls.count == beforeCode, "regenerate requires confirmation")
        model.askRegenerate(); model.regenerate(); model.regenerate(); await settle()
        check(api.calls.count == beforeCode + 1 && model.copyCode() == "def456", "confirmed regeneration once")
        api.error = .network; model.askRegenerate(); model.regenerate(); await settle()
        check(model.codeError && model.copyCode() == "def456", "regeneration failure")
        api.error = nil; api.reply = .profile(profile); api.pause = true
        model.refresh(); await settle(); api.familyIdentity = nil
        check(model.visibleProfile == nil && model.copyCode() == nil, "identity gate immediate")
        model.stop(); api.release(); await settle()
        check(model.profile == nil && model.invitation == nil && model.draft.isEmpty, "logout late result discarded")
        api.familyIdentity = ChatIdentity(owner: UUID(), user: 5, family: 6, generation: 1, version: 1)
        api.reply = .profile(try decode(FamilyProfile.self, profileJSON.replacingOccurrences(of: "\"can_edit_roles\":true", with: "\"can_edit_roles\":false")))
        model.start(); await settle(); let beforeDenied = api.calls.count
        model.editAddress(); model.role(id, .child); model.askRegenerate(); model.regenerate(); await settle()
        check(!model.canManage && api.calls.count == beforeDenied && model.stage == .view, "read only permissions")
        model.stop(); api.error = .network; model.start(); await settle()
        check(model.loadError, "load error")
        api.error = nil; model.refresh(); await settle()
        check(!model.loadError && model.profile != nil, "retry load")
        model.stop()
        // Each mutation may finish after a screen cancellation or family switch.
        for operation in ["role", "resolve", "save", "code"] {
            api.reply = .profile(profile); model.start(); await settle()
            if operation == "save" {
                model.editAddress(); model.changeDraft("רחוב 1 עיר")
                api.reply = .candidate(candidate); model.verifyAddress(); await settle()
            }
            api.pause = true
            switch operation {
            case "role": api.reply = .member(profile.members[0]); model.role(id, .child)
            case "resolve": api.reply = .candidate(candidate); model.editAddress(); model.verifyAddress()
            case "save": api.reply = .address("תשובה מאוחרת"); model.confirmAddress()
            default: api.reply = .code("zzz999"); model.askRegenerate(); model.regenerate()
            }
            await settle()
            check(api.continuation != nil, "operation suspended")
            let old = api.familyIdentity!
            api.familyIdentity = ChatIdentity(owner: old.owner, user: old.user, family: old.family + 1, generation: old.generation, version: old.version)
            check(model.visibleProfile == nil && !model.canManage && model.copyCode() == nil, "family switch hides old data immediately")
            model.stop(); api.release(); await settle()
            check(model.profile == nil && model.candidate == nil && !model.codePending && model.rolePending.isEmpty, "late mutation cannot restore state")
        }
        api.reply = .profile(profile); model.start(); await settle()
        model.editAddress(); model.changeDraft("רחוב 1 עיר")
        api.reply = .candidate(try decode(AddressResult.self, "{\"display_address\":\"x\",\"normalized_address\":\"y\",\"resolution_token\":\" \"}"))
        model.verifyAddress(); await settle()
        check(model.stage == .edit && model.candidate == nil, "blank token cannot confirm")
        api.reply = .candidate(candidate); model.verifyAddress(); await settle()
        model.reviseAddress(); model.changeDraft("כתובת אחרת 2"); let beforeUnverified = api.calls.count
        model.confirmAddress(); await settle()
        check(api.calls.count == beforeUnverified && model.candidate == nil, "edited address cannot use previous token")
        model.stop()
        print("PASS: \(count) Family checks")
    }
}
