import Foundation

@main struct LegalLinkCheck {
    static func main() {
        let expected = ["https://familycaragent.com/terms", "https://familycaragent.com/privacy",
                        "https://familycaragent.com/support", "https://familycaragent.com/contact"]
        precondition(PublicWebsiteDestination.allCases.map { $0.url.absoluteString } == expected)
        for value in expected { precondition(PublicWebsiteDestination.allows(URL(string: value)!)) }
        for value in ["http://familycaragent.com/terms", "https://familycaragent.com/terms?token=private",
                      "https://other.example/privacy", "fca-entry-legal://privacy"] {
            precondition(!PublicWebsiteDestination.allows(URL(string: value)!))
        }
        precondition(EntryLegalDocument.terms.url == PublicWebsiteDestination.terms.url)
        precondition(EntryLegalDocument.privacy.url == PublicWebsiteDestination.privacy.url)
        precondition(OnboardingValidation.legalAcceptance == "קראתי ואני מסכים/ה לתנאי השימוש, ואני מאשר/ת שקראתי את מדיניות הפרטיות של Family Car Agent.")
        print("PASS: four canonical destinations, closed URL allowlist and exact approved consent")
    }
}
