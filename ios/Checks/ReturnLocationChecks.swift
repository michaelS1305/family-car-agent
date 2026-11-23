import Foundation

@main struct ReturnLocationChecks {
    static func main() {
        func reason(present: Bool = true, requiresSource: Bool = true, hasSource: Bool = true,
                    simulated: Bool = false, validCoordinates: Bool = true,
                    accuracy: Double = 10, age: Double = 1) -> ReturnLocationReason? {
            ReturnLocationValidation.rejection(present: present, requiresSource: requiresSource,
                hasSource: hasSource, simulated: simulated, validCoordinates: validCoordinates,
                accuracy: accuracy, age: age)
        }
        precondition(reason(present: false) == .missingLocation)
        precondition(reason(hasSource: false) == .missingSource)
        precondition(reason(simulated: true) == .simulated)
        precondition(reason(validCoordinates: false) == .coordinates)
        precondition(reason(accuracy: 0) == .accuracy)
        precondition(reason(accuracy: 100.001) == .accuracy)
        precondition(reason(age: 30.001) == .stale)
        precondition(reason(age: -0.001) == .future)
        precondition(reason(accuracy: 100, age: 30) == nil)
        precondition(reason(age: 0) == nil)
        precondition(reason(requiresSource: false, hasSource: false) == nil)
        precondition(reason(requiresSource: false, hasSource: false, simulated: true) == .simulated)
        precondition(ReturnLocationReason.fallbackUnavailable.rawValue == "fallback_unavailable")
        // Independent oracle: the original Boolean acceptance expression, including
        // absent fallback source information, NaN, infinity and boundary values.
        var checks = 0
        for present in [false, true] {
          for shortcut in [false, true] {
            for source in [false, true] {
              for simulated in [false, true] {
                for coordinates in [false, true] {
                  for accuracy in [-1.0, 0, 0.001, 100, 100.001, .nan, .infinity] {
                    for age in [-Double.infinity, -0.001, 0, 30, 30.001, .nan, .infinity] {
                        let original = present && (!shortcut || source) && !simulated && coordinates
                            && accuracy > 0 && accuracy <= 100 && (0...30).contains(age)
                        let actual = reason(present: present, requiresSource: shortcut, hasSource: source,
                            simulated: simulated, validCoordinates: coordinates, accuracy: accuracy, age: age)
                        precondition((actual == nil) == original)
                        checks += 1
                    }
                  }
                }
              }
            }
          }
        }
        print("PASS: \(checks) original-validator equivalence cases and fixed rejection/boundary checks")
    }
}
