"""Focused SwiftUI source checks; runtime/model checks run separately. No network."""
from pathlib import Path
import re
root = Path(__file__).resolve().parents[1] / 'Sources/FamilyCarAgent'
legal = (root / 'EntryLegalDocument.swift').read_text(encoding='utf-8')
login = (root / 'EntryScreens.swift').read_text(encoding='utf-8')
flow = (root / 'OnboardingScreens.swift').read_text(encoding='utf-8')
settings = (root / 'Settings/SettingsScreen.swift').read_text(encoding='utf-8')
model = (root / 'Auth/EntryModel.swift').read_text(encoding='utf-8')
validation = (root / 'Auth/OnboardingValidation.swift').read_text(encoding='utf-8')
for target in ('terms', 'privacy', 'support', 'contact'):
    assert f'openPublic(.{target})' in settings
assert 'Button("מרכז התמיכה")' in settings and 'Button("יצירת קשר")' in settings
assert 'openURL(destination.url) { accepted in publicLinkFailed = !accepted }' in settings
assert 'PublicWebsiteDestination.allows(url)' in legal
assert 'openURL(url) { accepted in failed = !accepted }' in legal
assert '.publicWebsiteLinks()' in login and '.publicWebsiteLinks()' in flow
assert 'login(false)' in login and 'AppleProviderButton' in login and 'login(true)' in login
assert 'Text(EntryLegalDocument.linkedNotice)' in login
assert 'document.body' not in login and 'fca-entry-legal://' not in legal
acceptance = legal.split('static var linkedAcceptance:', 1)[1].split('return result', 1)[0]
parts = re.findall(r'AttributedString\("([^"\n]+)"\)|linked\("([^"\n]+)", document:', acceptance)
text = ''.join(a or b for a,b in parts)
expected = 'קראתי ואני מסכים/ה לתנאי השימוש, ואני מאשר/ת שקראתי את מדיניות הפרטיות של Family Car Agent.'
assert text == expected and expected in validation
assert 'linked("תנאי השימוש", document: .terms)' in acceptance
assert 'linked("מדיניות הפרטיות", document: .privacy)' in acceptance
assert 'Text(EntryLegalDocument.linkedAcceptance)' in flow
assert 'Button { model.consent.toggle() }' in flow
assert '}.buttonStyle(.plain).accessibilityLabel(OnboardingValidation.legalAcceptance)' in flow
assert '.frame(minWidth: 44, minHeight: 44)' in flow
assert '@Published var consent = false' in model and 'consent = false; resolutionToken' in model
assert 'let last = route == .create ? 4 : 5' in model
assert 'guard consent else { error = OnboardingValidation.legalAcceptanceRequired; return }' in model
for source in (settings, flow): assert '.rightToLeft' in source
assert 'FCAColors' in login and 'onboardingSecondary' in flow and 'SettingsPalette' in settings
assert 'הצהרת הכשירות' not in model and 'אני עומד/ת בדרישות החוק' not in flow
print('PASS: Settings support/legal actions, pre-auth links, separate checkbox/links, default/mandatory acceptance, RTL/semantic colors (static)')
