import Foundation

enum OnboardingValidation {
    static func validName(_ value: String) -> Bool {
        guard value.unicodeScalars.count <= 100 else { return false }
        var normalized = value.precomposedStringWithCanonicalMapping.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        for item in ["’", "׳"] { normalized = normalized.replacingOccurrences(of: item, with: "'") }
        for item in ["‐", "‑", "‒", "–", "—", "−"] { normalized = normalized.replacingOccurrences(of: item, with: "-") }
        let letters = Array(normalized.unicodeScalars)
        func letter(_ index: Int) -> Bool { letters.indices.contains(index) && CharacterSet.letters.contains(letters[index]) }
        guard letter(0) else { return false }
        return letters.indices.allSatisfy { index in
            if letter(index) { return true }
            if letters[index] == "'" { return letter(index - 1) && (index == letters.count - 1 || letter(index + 1)) }
            return (letters[index] == " " || letters[index] == "-") && letter(index - 1) && letter(index + 1)
        }
    }
}
