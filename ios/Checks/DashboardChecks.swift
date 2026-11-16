import Foundation

@main struct DashboardChecks {
    static func main() {
        var count = 0
        func check(_ value: Bool, _ label: String) { precondition(value, label); count += 1 }
        let who = ChatIdentity(owner: UUID(), user: 1, family: 10, generation: 1, version: 1)
        var invitation = FirstVehicleSetupState()
        invitation.activate(who)
        let ready = FirstVehicleSetupSnapshot(identity: who, current: true, loaded: true,
            loading: false, loadError: false, canCreate: true, vehicleCount: 0,
            atRoot: true, hasVehicleDestination: false, blocked: false)
        check(invitation.visible(ready), "authorized administrator / loaded empty family")
        for mutation: (inout FirstVehicleSetupSnapshot) -> Void in [
            { $0.identity = nil }, { $0.current = false }, { $0.loaded = false },
            { $0.loading = true }, { $0.loadError = true }, { $0.canCreate = false },
            { $0.vehicleCount = 1 }, { $0.atRoot = false },
            { $0.hasVehicleDestination = true }, { $0.blocked = true }
        ] {
            var invalid = ready; mutation(&invalid)
            check(!invitation.visible(invalid), "eligibility fails closed")
        }
        var noFamily = ready
        noFamily.identity = ChatIdentity(owner: who.owner, user: 1, family: 0, generation: 1, version: 1)
        check(!invitation.visible(noFamily), "invalid family unavailable")
        var transient = ready; transient.loadError = true
        invitation.observe(transient)
        check(invitation.visible(ready), "failure does not permanently suppress successful reload")
        invitation.handle(who)
        invitation.activate(who); invitation.observe(ready)
        check(!invitation.visible(ready), "dismiss / CTA survives refresh and view recomputation")
        let refreshed = ChatIdentity(owner: who.owner, user: 1, family: 10, generation: 2, version: 2)
        invitation.activate(refreshed)
        check(!invitation.needsCheck(refreshed), "same owner/family refresh keeps acknowledgment")
        let other = ChatIdentity(owner: who.owner, user: 1, family: 11, generation: 2, version: 1)
        invitation.activate(other)
        check(invitation.needsCheck(other) && !invitation.visible(ready), "family change isolates stale data")
        invitation.handle(who)
        check(invitation.needsCheck(other), "old context cannot dismiss new context")
        invitation.activate(who)
        var populated = ready; populated.vehicleCount = 2
        invitation.observe(populated)
        check(!invitation.visible(ready), "successful nonempty family handled even if later empty")
        invitation.activate(nil); invitation.activate(who)
        check(invitation.visible(ready), "new authenticated session re-evaluates")
        let anotherUser = ChatIdentity(owner: UUID(), user: 2, family: 10, generation: 3, version: 1)
        invitation.handle(who); invitation.activate(anotherUser)
        check(invitation.needsCheck(anotherUser), "user change re-evaluates")
        var route = DashboardNavigation(); route.synchronize(who)
        invitation.activate(who); invitation.handle(who); route.open(.vehicles)
        check(route.path == [.vehicles] && invitation.handled, "CTA handled and existing vehicles route")
        route.back(); invitation.handle(who)
        check(route.isRoot && !invitation.visible(ready), "dismiss does not navigate or reopen")
        let categories = DashboardDestination.allCases
        check(categories == [.family, .vehicles, .settings, .history, .bookingCenter], "category order")
        let anchors = [(0.50,0.20),(0.77,0.44),(0.67,0.73),(0.35,0.75),(0.19,0.39)]
        for (item, expected) in zip(categories, anchors) {
            check(item.anchor.x == expected.0 && item.anchor.y == expected.1, "physical anchor")
            check(!item.label.isEmpty && item.asset.hasSuffix("_icon.png"), "category metadata")
        }
        check(DashboardLayout.greeting(" מרק כהן ") == "היי, מרק", "first name")
        check(DashboardLayout.greeting("\u{00A0}דנה\u{2003}לוי") == "היי, דנה", "unicode whitespace")
        check(DashboardLayout.greeting(" \n\t") == "היי", "missing name")
        check(DashboardLayout.startAngle == -126 && DashboardLayout.sweep * 5 == 360, "closed wheel")
        check(DashboardLayout.startAngle + DashboardLayout.sweep / 2 == -90, "family sector is top")
        for width in [320.0, 375, 390, 393, 430] {
            for height in [300.0, 420, 539, 540, 700] {
                let layout = DashboardLayout(width: width, height: height)
                check(layout.diameter <= width - 16 && layout.diameter >= 176, "fits width / usable targets")
                check(layout.logoutHeight >= 70 && layout.contentHeight >= height, "no overlap / compact fallback")
                check(layout.compact == (height < 540), "compact boundary")
                check(DashboardLayout.hub(layout.diameter) < DashboardLayout.radius(layout.diameter), "hub inside wheel")
                for i in 0..<5 {
                    for j in (i+1)..<5 {
                        let a = categories[i].anchor, b = categories[j].anchor
                        let overlapX = abs(a.x-b.x)*layout.diameter < max(44, layout.diameter*0.25)
                        let overlapY = abs(a.y-b.y)*layout.diameter < max(44, layout.diameter*0.28)
                        check(!(overlapX && overlapY), "independent nonoverlapping targets")
                    }
                }
            }
        }
        var nav = DashboardNavigation()
        nav.open(.family); check(nav.isRoot, "no unauthenticated path")
        let identity = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
        nav.synchronize(identity)
        for destination in categories {
            nav.open(destination); check(nav.path == [destination] && !nav.isRoot, "destination hides bar")
            nav.open(.settings); check(nav.path == [destination], "duplicate open ignored")
            nav.back(); check(nav.isRoot, "back returns dashboard")
        }
        nav.open(.history); nav.synchronize(identity)
        check(nav.path == [.history], "unchanged identity retains navigation")
        nav.back(); nav.open(.settings)
        nav.openFromSettings(.family)
        check(nav.path == [.settings, .family] && !nav.vehicleHelpPresented, "Settings opens existing Family")
        nav.back(); check(nav.path == [.settings], "Family returns to Settings")
        nav.openFromSettings(.vehicles)
        check(nav.path == [.settings, .vehicles] && nav.vehicleHelpPresented, "Settings vehicle help")
        nav.vehicleHelpPresented = false
        check(nav.path.last == .vehicles, "dismissing help stays on Vehicles")
        nav.back(); nav.back(); nav.open(.vehicles)
        check(!nav.vehicleHelpPresented, "ordinary Vehicles has no alert")
        nav.synchronize(ChatIdentity(owner: identity.owner, user: 1, family: 3, generation: 0, version: 0))
        check(nav.isRoot, "family change clears navigation")
        nav.open(.vehicles)
        nav.synchronize(ChatIdentity(owner: identity.owner, user: 1, family: 3, generation: 1, version: 0))
        check(nav.isRoot, "new session clears navigation")
        nav.open(.bookingCenter); nav.synchronize(nil)
        check(nav.isRoot, "logout clears navigation")
        print("Dashboard checks passed: \(count). Geometry/state only; no device rendering claims.")
    }
}
