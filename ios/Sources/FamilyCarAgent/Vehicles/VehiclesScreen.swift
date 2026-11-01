import SwiftUI

struct VehiclesScreen: View {
    @ObservedObject var model: VehiclesModel
    let back: () -> Void
    var body: some View {
        VStack(spacing: 0) {
            VehiclesHeader(back: back)
            GeometryReader { geometry in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        AppAssetImage(path: "icons/archive/vehicles_icon.png")
                            .frame(width: 200, height: 200).offset(y: -15).frame(height: 108)
                            .accessibilityLabel("רכבים")
                        if model.current {
                            if model.loading && !model.loaded { ProgressView("טוען…").padding(24) }
                            if model.loadError {
                                Text("לא ניתן לטעון את הרכבים")
                                Button("נסה שוב", action: model.refresh)
                            }
                            if model.loaded {
                                if model.visibleRows.isEmpty && !model.loading && !model.loadError {
                                    empty.frame(minHeight: max(0, geometry.size.height - 140))
                                } else if !model.visibleRows.isEmpty {
                                    HStack {
                                        Text("הרכבים שלנו").font(.system(size: 21, weight: .bold))
                                        Spacer()
                                        if model.mayAdd {
                                            Button(action: model.add) {
                                                Image(systemName: "plus").font(.system(size: 24))
                                                    .frame(width: 48, height: 48).overlay(Circle().stroke(ChatStyle.border))
                                            }.accessibilityLabel("הוספת רכב")
                                        }
                                    }
                                    ForEach(model.active) { row in card(row) }
                                    if !model.retired.isEmpty {
                                        VStack(alignment: .leading, spacing: 22) {
                                            Divider()
                                            Text("רכבים לא פעילים").font(.system(size: 20, weight: .bold)).foregroundStyle(ChatStyle.secondary)
                                        }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 22).padding(.bottom, 10)
                                        ForEach(model.retired) { row in card(row) }
                                    }
                                    if model.loading { ProgressView("מרענן…") }
                                }
                            }
                        }
                    }.padding(.horizontal, 20).padding(.bottom, 20).frame(maxWidth: 620).frame(maxWidth: .infinity)
                }
            }
        }
        .modifier(VehiclesAppearance())
        .task { model.start() }
        .navigationDestination(item: Binding(get: { model.current ? model.destination : nil }, set: { if $0 == nil { model.pop() } })) { destination in
            switch destination {
            case .add: AddVehicleScreen(model: model)
            case .details(let id): VehicleDetailsScreen(list: model, vehicleID: id).id(id)
            }
        }
    }
    private var empty: some View {
        VStack(spacing: 0) {
            AppAssetImage(path: "icons/archive/no_cars_icon.png").frame(width: 132, height: 132).accessibilityHidden(true)
            Text("אין עדיין רכבים").font(.system(size: 26, weight: .bold)).padding(.top, 24)
            Text(model.mayAdd ? "הוסיפו את הרכב הראשון של המשפחה\nכדי להתחיל לנהל אותו כאן" : "כרגע אין רכבים במשפחה\nרק מנהל המשפחה יכול להוסיף רכבים")
                .font(.system(size: 18)).foregroundStyle(ChatStyle.secondary).multilineTextAlignment(.center).padding(.top, 16)
            if model.mayAdd {
                Button(action: model.add) {
                    HStack { Text("הוספת רכב"); Image(systemName: "plus") }
                        .font(.system(size: 20)).frame(maxWidth: .infinity, minHeight: 56)
                        .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.ink))
                }.padding(.top, 28)
                Text("זמין למנהל המשפחה בלבד").font(.system(size: 14)).foregroundStyle(ChatStyle.secondary).padding(.top, 14)
            }
        }.padding(.horizontal, 4)
    }
    private func card(_ vehicle: ManagedVehicle) -> some View {
        Button { model.select(vehicle.id) } label: {
            HStack(spacing: 0) {
                Image(systemName: "chevron.right").frame(width: 18, height: 18)
                Text(vehicle.name).font(.system(size: 22, weight: .bold))
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16)
                AppAssetImage(path: VehicleCategory.illustration(vehicle.category))
                    .frame(width: 112, height: 64).environment(\.layoutDirection, .leftToRight)
            }.padding(16).frame(minHeight: 94)
                .background(.white.opacity(0.7), in: RoundedRectangle(cornerRadius: 24))
                .overlay(RoundedRectangle(cornerRadius: 24).stroke(ChatStyle.border))
                .opacity(vehicle.retired ? 0.5 : 1)
        }.buttonStyle(.plain).accessibilityLabel(vehicle.name + (vehicle.retired ? ", רכב לא פעיל" : ""))
    }
}

struct VehiclesHeader: View {
    let back: () -> Void
    var body: some View {
        ZStack {
            AppAssetImage(path: ChatStyle.wordmark).frame(width: 220, height: 58).blendMode(.multiply).accessibilityHidden(true)
            HStack {
                Button(action: back) {
                    Image(systemName: "chevron.right").font(.system(size: 22)).frame(width: 46, height: 46)
                        .background(.white.opacity(0.85), in: Circle())
                }.accessibilityLabel("חזרה")
                Spacer()
            }
        }.frame(height: 76).padding(.horizontal, 16)
    }
}
struct VehiclesAppearance: ViewModifier {
    func body(content: Content) -> some View {
        content.background(ChatStyle.background.ignoresSafeArea()).foregroundStyle(ChatStyle.ink)
            .environment(\.layoutDirection, .rightToLeft).preferredColorScheme(.light)
            .toolbar(.hidden, for: .navigationBar).navigationBarBackButtonHidden(true)
    }
}
