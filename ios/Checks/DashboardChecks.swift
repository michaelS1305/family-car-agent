import Foundation

@main struct DashboardChecks {
    static func main() {
        var count = 0
        func check(_ value: Bool, _ label: String) { precondition(value, label); count += 1 }
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
