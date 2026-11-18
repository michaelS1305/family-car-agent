import unittest
from onboarding_rules import prepare_address_proposal

class AddressProposalTests(unittest.TestCase):
    def test_supported_formats_and_multiword_names(self):
        for value in ("דימונה, המעפיל, 1209", "המעפיל 1209 דימונה", "דימונה המעפיל 1209", "המעפיל 1209, דימונה", "שדרות בן גוריון 12 תל אביב"):
            self.assertEqual(prepare_address_proposal(value)[1], "1209" if "1209" in value else "12")
    def test_explicit_legacy_fields_allow_numeric_street_names(self):
        self.assertEqual(prepare_address_proposal("עיר, רחוב 2, 12")[1], "12")

    def test_uncertain_numbers_and_invalid_input_require_clarification(self):
        for value in (None, "", "רחוב עיר", "1209", "רחוב 12 דירה 3 עיר", "רחוב 2 12 עיר", "א" * 201):
            self.assertIsNone(prepare_address_proposal(value))
