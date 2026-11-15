"""Adaptive presentation and Phase C activation wiring (not device rendering)."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'Sources/FamilyCarAgent'
views = {str(p.relative_to(root)).replace('\\', '/'): p.read_text(encoding='utf-8')
         for p in root.rglob('*.swift') if re.search(r': (?:View|UIViewRepresentable|ViewModifier|ButtonStyle)\b', p.read_text(encoding='utf-8'))}
assert len(views) == 19, 'Review newly added views for appearance coverage'
for name, text in views.items():
    assert not re.search(r'Color\(\s*(?:red|white):', text), name
    assert not re.search(r'\.background\(\s*(?:Color\.)?white\b', text), name
    assert '.colorInvert(' not in text and '.renderingMode(.template)' not in text, name

shell = views['AuthenticatedAppShell.swift']
for alias, role in [('background','background'),('ink','text'),('incoming','incomingBubble'),
                    ('selected','selection'),('secondary','secondaryText'),('border','border')]:
    assert f'static let {alias} = FCAColors.color(.{role})' in shell
for text in views.values():
    assert '.background(ChatStyle.ink' not in text, 'Text token used as action surface'

chat = views['Chat/ChatScreen.swift']
for role in ['outgoingText', 'incomingText', 'outgoingBubble', 'input']:
    assert f'FCAColors.color(.{role})' in chat
assert 'LinearGradient(colors: [.clear, .black]' in chat and 'Color.black' in chat, 'Keep alpha mask opaque'
wheel = views['Dashboard/DashboardScreen.swift']
assert r'@Environment(\.colorScheme)' in wheel and 'dark: colorScheme == .dark' in wheel
for role in ['wheelSurface', 'wheelBase', 'wheelHighlight', 'wheelLine']:
    assert f'paint(.{role})' in wheel
booking = views['Booking/BookingCenterPreview.swift']
for role in ['calendarSelection','onCalendarSelection','calendarIndicator','sheet','shadow','scrim']:
    assert f'FCAColors.color(.{role})' in booking
for name in ['Booking/BookingForms.swift', 'Errors/AppErrorDialog.swift', 'Vehicles/AddVehicleScreen.swift']:
    assert 'FCAColors.color(.primaryAction)' in views[name]
    assert 'FCAColors.color(.onPrimaryAction)' in views[name]
assert 'FCAColors.color(.dialog)' in views['Errors/AppErrorDialog.swift']
settings = views['Settings/SettingsScreen.swift']
assert 'FCAColors.appearanceAccent(dark: colorScheme == .dark)' in settings
assert '.background(SettingsPalette.card,' in settings and 'FCAColors.color(.settingsCard)' in settings
app = (root / 'FamilyCarAgentApp.swift').read_text(encoding='utf-8')
for source in [app, settings]:
    assert '@AppStorage(AppAppearance.storageKey) private var appearancePreference = AppAppearance.system.rawValue' in source
    assert 'AppAppearance(storedValue: appearancePreference)' in source
    assert '.id(' not in source, 'Appearance must not reset root or Settings identity'
assert 'ForEach(AppAppearance.allCases, id:' in settings
assert 'Button { appearancePreference = mode.rawValue }' in settings
assert '.accessibilityAddTraits(appearance == mode ? .isSelected : [])' in settings
assert '.accessibilityLabel(mode.title)' in settings and '.frame(minHeight: 44)' in settings
assert '.accessibilityElement(children: .contain)' in settings
assert 'title == "בהיר"' not in settings
assert '.preferredColorScheme(AppAppearance(storedValue: appearancePreference).colorScheme)' in app
assert app.count('ContentView()') == 1 and '@UIApplicationDelegateAdaptor(VehicleSyncAppDelegate.self)' in app
asset = views['AppAsset.swift']
assert 'path == FCABranding.lightWordmark' in asset
assert 'FCABranding.wordmark(dark: colorScheme == .dark) : path' in asset
assert 'content.blendMode(colorScheme == .dark ? .normal : .multiply)' in asset
for name, text in views.items():
    if 'AppAssetImage(path: ChatStyle.wordmark)' in text:
        assert '.modifier(FCAWordmarkBlend())' in text, name
entry = views['EntryScreens.swift']
assert 'style: colorScheme == .dark ? .white : .black' in entry
assert '.id(colorScheme)' in entry and 'button.addTarget(context.coordinator' in entry
assert 'context.environment.colorScheme == .dark ? .dark : .light' in views['VerifiedAddressPreview.swift']

# Only the root sets a presentation preference. Sheets/forms/dialogs inherit it.
sources = {p: p.read_text(encoding='utf-8') for p in root.rglob('*.swift')}
assert [p.name for p, text in sources.items() if '.preferredColorScheme(' in text] == ['FamilyCarAgentApp.swift']
assert not any('UIUserInterfaceStyle' in p.read_text(encoding='utf-8') for p in (root.parents[1] / 'Config').glob('*.plist'))
assert '@StateObject private var model = EntryModel()' in views['ContentView.swift']
assert 'NavigationStack(path: $navigation.path)' in shell
assert '.presentationDetents([peek, .large], selection: $detent)' in booking
assert '.presentationDragIndicator(.visible)' in booking
print('PASS: root-only appearance, shared preference and accessible selector; 19 adaptive view files, inherited sheets, unchanged navigation and branding')

# Explicit monochrome control opt-in, never a global image recolor.
assert 'var monochromeControl = false' in asset
assert '.renderingMode(monochromeControl && colorScheme == .dark ? .template : .original)' in asset
for text in views.values():
    for line in text.splitlines():
        if 'monochromeControl: true' in line:
            assert not any(x in line for x in ['wordmark', 'branding/', 'category.asset', 'VehicleCategory.illustration', 'bluetooth_icon']), line
for file in ['Booking/BookingForms.swift', 'History/HistoryScreen.swift']:
    assert '.scrollContentBackground(colorScheme == .dark ? .hidden : .automatic)' in views[file]
    assert '.listRowBackground(colorScheme == .dark ? FCAColors.color(.surface) : nil)' in views[file]
