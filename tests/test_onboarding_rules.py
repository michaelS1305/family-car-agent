import unittest
import unicodedata

from onboarding_rules import (
    is_next,
    is_no,
    is_valid_family_code,
    is_yes,
    normalize_human_name,
    parse_home_address,
)


class ParseHomeAddressTests(unittest.TestCase):
    def test_parses_and_trims_three_address_parts(self):
        self.assertEqual(
            parse_home_address(" תל אביב , דיזנגוף , 120 "),
            ("תל אביב", "דיזנגוף", "120"),
        )

    def test_accepts_supported_house_number_variants(self):
        for house_number in ("12א", "12/3", "א12"):
            with self.subTest(house_number=house_number):
                self.assertEqual(
                    parse_home_address(f"חיפה, הרצל, {house_number}"),
                    ("חיפה", "הרצל", house_number),
                )

    def test_rejects_wrong_part_count(self):
        for address in ("תל אביב, דיזנגוף", "תל אביב, דיזנגוף, 120, א"):
            with self.subTest(address=address):
                self.assertIsNone(parse_home_address(address))

    def test_rejects_empty_parts(self):
        for address in (", דיזנגוף, 120", "תל אביב, , 120", "תל אביב, דיזנגוף, "):
            with self.subTest(address=address):
                self.assertIsNone(parse_home_address(address))

    def test_rejects_house_number_without_a_digit(self):
        self.assertIsNone(parse_home_address("תל אביב, דיזנגוף, א"))


class FamilyCodeTests(unittest.TestCase):
    def test_accepts_exactly_six_digits(self):
        self.assertTrue(is_valid_family_code("482731"))
        self.assertTrue(is_valid_family_code("000000"))

    def test_rejects_non_six_digit_values(self):
        for family_code in ("48273", "4827310", "48273א", " 482731 ", ""):
            with self.subTest(family_code=family_code):
                self.assertFalse(is_valid_family_code(family_code))


class HumanNameTests(unittest.TestCase):
    def test_rejects_numeric_and_alphanumeric_names(self):
        for value in ("111", "Michael1", "כהן2"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_human_name(value))

    def test_accepts_hebrew_english_and_sensible_separators(self):
        expected = {
            "מיכאל כהן": "מיכאל כהן",
            "Michael Cohen": "Michael Cohen",
            "בן-דוד": "בן-דוד",
            "O'Connor": "O'Connor",
            "D’Angelo": "D'Angelo",
            "סנדרוביץ'": "סנדרוביץ'",
            "סנדרוביץ׳": "סנדרוביץ'",
            "סנדרוביץ’": "סנדרוביץ'",
            "Smith‐Jones": "Smith-Jones",
            "Smith‑Jones": "Smith-Jones",
            "Smith‒Jones": "Smith-Jones",
            "Smith–Jones": "Smith-Jones",
            "Smith—Jones": "Smith-Jones",
            "Smith−Jones": "Smith-Jones",
            "משפחת O’Connor": "משפחת O'Connor",
            "  Michael   Cohen  ": "Michael Cohen",
        }
        for value, normalized in expected.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_human_name(value), normalized)

    def test_create_and_join_variants_share_one_canonical_name(self):
        apostrophe_variants = (
            "סנדרוביץ'",
            "סנדרוביץ׳",
            "סנדרוביץ’",
        )
        hyphen_variants = (
            "בן-דוד",
            "בן‐דוד",
            "בן‑דוד",
            "בן‒דוד",
            "בן–דוד",
            "בן—דוד",
            "בן−דוד",
        )

        for create_name in apostrophe_variants:
            for join_name in apostrophe_variants:
                with self.subTest(create=create_name, join=join_name):
                    self.assertEqual(
                        normalize_human_name(create_name),
                        normalize_human_name(join_name),
                    )

        for create_name in hyphen_variants:
            for join_name in hyphen_variants:
                with self.subTest(create=create_name, join=join_name):
                    self.assertEqual(
                        normalize_human_name(create_name),
                        normalize_human_name(join_name),
                    )

    def test_unicode_nfc_and_whitespace_are_canonicalized(self):
        decomposed = unicodedata.normalize("NFD", "José")

        self.assertEqual(normalize_human_name(decomposed), "José")
        self.assertEqual(
            normalize_human_name("  משפחת   O’Connor  "),
            "משפחת O'Connor",
        )

    def test_rejects_unsafe_separator_shapes(self):
        for value in (
            "-כהן",
            "כהן-",
            "'כהן",
            "Michael--Cohen",
            "Michael''Cohen",
            "Michael @ Cohen",
            "'",
            "׳",
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_human_name(value))


class NavigationAnswerTests(unittest.TestCase):
    def test_yes_answers_match_existing_variants(self):
        for answer in ("כן", "כן.", "נכון", "נכון.", "yes", "YES", "y", " Y "):
            with self.subTest(answer=answer):
                self.assertTrue(is_yes(answer))

        self.assertFalse(is_yes("בטח"))

    def test_no_answers_match_existing_variants(self):
        for answer in ("לא", "לא.", "no", "NO", "n", " N "):
            with self.subTest(answer=answer):
                self.assertTrue(is_no(answer))

        self.assertFalse(is_no("ממש לא"))

    def test_next_answers_match_existing_variants_and_remain_case_sensitive(self):
        for answer in ("הבא", "המשך", "סיימתי", "בוצע", "עשיתי", " הבא "):
            with self.subTest(answer=answer):
                self.assertTrue(is_next(answer))

        self.assertFalse(is_next("NEXT"))


if __name__ == "__main__":
    unittest.main()
