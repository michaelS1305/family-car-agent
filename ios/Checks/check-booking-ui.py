"""Focused source-wiring checks; not a substitute for iPhone layout verification."""
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "Sources/FamilyCarAgent/Booking"
screen = (root / "BookingCenterPreview.swift").read_text(encoding="utf-8")
forms = (root / "BookingForms.swift").read_text(encoding="utf-8")

assert ".presentationDetents([peek, .large]" in screen
assert ".presentationDragIndicator(.visible)" in screen
assert "BookingHeaderHeight.self" in screen and "geometry.size.height" in screen
assert "if detent == .large" in screen
assert '"הרחבה"' not in screen and '"צמצום"' not in screen
assert '"חזרה לדשבורד"' not in screen
cards = screen.split("ForEach(model.dayRows)", 1)[1].split("if model.loaded", 1)[0]
assert "model.canWrite && model.eligible(row)" in cards and ".shadow(" in cards
assert ".disabled(" not in cards and "reservationCard(row).accessibilityElement" in cards
assert "model.sheet != .cancellation ? model.sheet : nil" in screen
prompt = screen.split("private var cancellationPrompt:", 1)[1].split("private func toolbarButton", 1)[0]
assert prompt.count("model.submit()") == 1 and "model.dismiss()" in prompt
assert 'Text("לבטל את ההזמנה?")' in prompt and 'Text("לבטל")' in prompt
assert ".disabled(model.busy)" in prompt and "!model.canWrite" in prompt
assert "vehicleName" not in prompt and "BookingPreviewCalendar.label" not in prompt
editor = forms.split("private var editor:", 1)[1].split("private func dateInput", 1)[0]
assert forms.count('Text("שמירת הזמנה")') == 1
assert editor.index('dateInput(start: false)') < editor.index('Text("שמירת הזמנה")')
assert ".disabled(!model.canSubmitDraft)" in editor and "BookingCapsuleStyle" in editor
assert "if model.busy { ProgressView()" in editor
assert "editorHeader" not in forms and ".safeAreaInset(edge: .top" not in forms
header = forms.split(".navigationTitle", 1)[1].split("}.tint", 1)[0]
assert '"פרטי הזמנה"' in header and '"סינון הזמנות"' in header
assert 'ToolbarItem(placement: .cancellationAction)' in header
assert 'Button("חזרה") { model.dismiss() }.disabled(model.busy)' in header
assert "if sheet != .editor" not in header
assert "בחירת המועד המוצג" not in forms and "מעבר שעון" not in forms
assert "!model.canSubmitDraft" in editor and "יש לבחור רכב זמין וטווח שעות תקין." in editor
assert "DatePicker(start ?" in forms
assert "Toggle(" not in forms
assert "model.filters.start = nil" in forms and "model.filters.end = nil" in forms
assert "model.applyFilters()" in forms and "model.filters = BookingFilters()" in forms
print("PASS: measured peek, expanded-only content, card eligibility, compact confirmation, below-form save, shared navigation and optional filters (static wiring only)")
