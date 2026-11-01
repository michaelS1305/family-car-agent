import SwiftUI
import MapKit

struct VerifiedAddressPreview: View {
    let location: VerifiedLocation?
    var body: some View {
        if let location {
            CandidateMap(location: location).id(location)
        } else {
            Text("תצוגת מפה אינה זמינה").frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(white: 0.95))
        }
    }
}

private struct CandidateMap: View {
    let location: VerifiedLocation
    @State private var failed = false
    var body: some View {
        ZStack {
            ReadOnlyMap(location: location) { failed = true }
            if failed {
                Text("תצוגת מפה אינה זמינה").frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(white: 0.95))
            }
        }
    }
}

private struct ReadOnlyMap: UIViewRepresentable {
    let location: VerifiedLocation
    let failure: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(failure: failure) }
    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.isScrollEnabled = false; map.isZoomEnabled = false
        map.isRotateEnabled = false; map.isPitchEnabled = false
        map.isUserInteractionEnabled = false; map.showsUserLocation = false
        let point = CLLocationCoordinate2D(latitude: location.latitude, longitude: location.longitude)
        let marker = MKPointAnnotation(); marker.coordinate = point
        map.addAnnotation(marker)
        map.setRegion(MKCoordinateRegion(center: point, latitudinalMeters: 500, longitudinalMeters: 500), animated: false)
        return map
    }
    func updateUIView(_ map: MKMapView, context: Context) {}
    static func dismantleUIView(_ map: MKMapView, coordinator: Coordinator) {
        coordinator.active = false; map.delegate = nil
    }
    @MainActor final class Coordinator: NSObject, MKMapViewDelegate {
        var active = true
        let failure: () -> Void
        init(failure: @escaping () -> Void) { self.failure = failure }
        func mapViewDidFailLoadingMap(_ mapView: MKMapView, withError error: Error) {
            // No raw error, coordinate or address logging. Ignore callbacks after disposal.
            guard active else { return }
            failure()
        }
    }
}
