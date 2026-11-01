import SwiftUI

struct DashboardScreen: View {
    let name: String
    let busy: Bool
    let open: (DashboardDestination) -> Void
    let logout: () -> Void
    var body: some View {
        GeometryReader { geometry in
            let layout = DashboardLayout(width: geometry.size.width, height: geometry.size.height)
            if layout.contentHeight > geometry.size.height {
                ScrollView { content(layout) }
            } else {
                content(layout)
            }
        }
        .background(ChatStyle.background)
    }
    private func content(_ layout: DashboardLayout) -> some View {
        VStack(spacing: 0) {
            AppAssetImage(path: ChatStyle.wordmark)
                .frame(maxWidth: 255).frame(height: layout.headerHeight).scaleEffect(0.9).blendMode(.multiply)
                .accessibilityLabel("Family Car Agent")
            Text(DashboardLayout.greeting(name))
                .font(.system(size: layout.compact ? 24 : 28, weight: .bold))
                .foregroundStyle(ChatStyle.ink).multilineTextAlignment(.center)
                .lineLimit(1).minimumScaleFactor(0.65).frame(height: layout.greetingHeight)
            Color.clear.frame(height: 6)
            DashboardWheel(diameter: layout.diameter, open: open)
            VStack {
                Spacer(minLength: 0)
                Button(action: logout) {
                    HStack(spacing: 4) {
                        AppAssetImage(path: "icons/archive/logout_icon.png").frame(width: 36, height: 36)
                            .accessibilityHidden(true)
                        Text("התנתקות").font(.system(size: 18, weight: .semibold))
                    }.padding(.horizontal, 12).frame(minWidth: 144).frame(height: 48)
                        .background(Color.white.opacity(0.65), in: Capsule())
                        .overlay(Capsule().stroke(.white, lineWidth: 1))
                }.buttonStyle(.plain).disabled(busy).accessibilityLabel("התנתקות")
                Spacer(minLength: 0)
            }.frame(height: layout.logoutHeight)
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .frame(maxWidth: .infinity).frame(height: layout.contentHeight)
    }
}

private struct DashboardWheel: View {
    let diameter: Double
    let open: (DashboardDestination) -> Void
    private let pale = Color(red: 228/255, green: 235/255, blue: 239/255)
    var body: some View {
        ZStack(alignment: .topLeading) {
            Canvas { context, size in
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let radius = DashboardLayout.radius(min(size.width, size.height))
                let hub = radius * 0.23
                func circle(_ r: Double, _ c: CGPoint) -> Path {
                    Path(ellipseIn: CGRect(x: c.x-r, y: c.y-r, width: 2*r, height: 2*r))
                }
                let depthCenter = CGPoint(x: center.x, y: center.y + radius * 0.06)
                context.fill(circle(radius * 1.1, depthCenter), with: .radialGradient(
                    Gradient(colors: [ChatStyle.secondary.opacity(0.16), .clear]),
                    center: depthCenter, startRadius: 0, endRadius: radius * 1.1))
                context.fill(circle(radius, center), with: .linearGradient(
                    Gradient(colors: [.white.opacity(0.9), pale, .white.opacity(0.8)]),
                    startPoint: .zero, endPoint: CGPoint(x: size.width, y: size.height)))
                for index in 0..<5 {
                    let start = DashboardLayout.startAngle + Double(index) * DashboardLayout.sweep
                    var sector = Path()
                    sector.move(to: center)
                    sector.addArc(center: center, radius: radius, startAngle: .degrees(start),
                                  endAngle: .degrees(start + DashboardLayout.sweep), clockwise: false)
                    sector.closeSubpath()
                    context.fill(sector, with: .color(.white.opacity(index.isMultiple(of: 2) ? 0.12 : 0.04)))
                }
                for index in 0..<5 {
                    let angle = (DashboardLayout.startAngle + Double(index) * DashboardLayout.sweep) * .pi / 180
                    var divider = Path()
                    divider.move(to: CGPoint(x: center.x + cos(angle)*hub, y: center.y + sin(angle)*hub))
                    divider.addLine(to: CGPoint(x: center.x + cos(angle)*radius, y: center.y + sin(angle)*radius))
                    context.stroke(divider, with: .color(.white.opacity(0.8)), lineWidth: 1)
                }
                context.stroke(circle(radius, center), with: .color(.white.opacity(0.7)), lineWidth: radius*0.012)
                context.stroke(circle(radius*1.05, center), with: .color(.white.opacity(0.45)), lineWidth: 1)
                context.fill(circle(hub*1.15, CGPoint(x: center.x, y: center.y+hub*0.07)), with: .color(ChatStyle.secondary.opacity(0.1)))
                context.fill(circle(hub, center), with: .linearGradient(Gradient(colors: [.white, pale]),
                    startPoint: CGPoint(x: center.x-hub, y: center.y-hub), endPoint: CGPoint(x: center.x+hub, y: center.y+hub)))
                context.stroke(circle(hub, center), with: .color(.white.opacity(0.85)), lineWidth: hub*0.12)
            }.accessibilityHidden(true)
            ForEach(DashboardDestination.allCases, id: \.self) { destination in
                Button { open(destination) } label: {
                    Color.clear.frame(width: max(44, diameter*0.25), height: max(44, diameter*0.28))
                        .overlay {
                            // The entire square PNG is rendered. Transparent margins may
                            // extend beyond the independent, non-overlapping hit rectangle.
                            AppAssetImage(path: destination.asset)
                                .frame(width: diameter*0.5, height: diameter*0.5)
                                .offset(y: -diameter*0.5*0.07).allowsHitTesting(false)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityLabel(destination.label)
                .position(x: diameter*destination.anchor.x, y: diameter*destination.anchor.y)
            }
        }
        .frame(width: diameter, height: diameter)
        .environment(\.layoutDirection, .leftToRight) // Physical anchors must not mirror in RTL.
    }
}

struct DashboardDestinationPlaceholder: View {
    let destination: DashboardDestination
    let back: () -> Void
    var body: some View {
        VStack(spacing: 16) {
            Text(destination.label).font(.system(size: 26, weight: .semibold))
            Text("בקרוב — מסך זמני").foregroundStyle(ChatStyle.secondary)
            Button("חזרה לדשבורד", action: back)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .foregroundStyle(ChatStyle.ink).background(ChatStyle.background.ignoresSafeArea())
            .navigationTitle(destination.label).navigationBarTitleDisplayMode(.inline)
    }
}
