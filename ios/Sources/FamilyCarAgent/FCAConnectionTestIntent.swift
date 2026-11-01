#if DEBUG
import AppIntents

/// Discovery-only proof of concept. No account access or side effects.
struct FCAConnectionTestIntent: AppIntent {
    static let title: LocalizedStringResource = "FCA Test Connection"
    static let description = IntentDescription("Tests FCA Shortcuts integration without connecting to a vehicle.")
    static let openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> & ProvidesDialog {
        .result(value: "FCA test connection succeeded", dialog: "FCA test connection succeeded")
    }
}
#endif
