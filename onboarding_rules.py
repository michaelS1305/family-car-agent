def parse_home_address(text):
    parts = [part.strip() for part in text.split(",")]

    if len(parts) != 3:
        return None

    city, street, house_number = parts

    if not city or not street or not house_number:
        return None

    # Allows values such as 120, 12א, 12/3, etc.,
    # but still requires at least one digit in the house number.
    if not any(char.isdigit() for char in house_number):
        return None

    return city, street, house_number


def is_valid_family_code(family_code):
    return family_code.isdigit() and len(family_code) == 6


NAME_APOSTROPHES = {"'", "’", "׳"}
NAME_INFIX_SEPARATORS = {" ", "-", "‐", "‑"}
NAME_SEPARATORS = NAME_APOSTROPHES | NAME_INFIX_SEPARATORS


def normalize_human_name(value):
    if not isinstance(value, str):
        return None

    normalized = " ".join(value.strip().split())
    if not normalized or any(character.isdigit() for character in normalized):
        return None
    if not any(character.isalpha() for character in normalized):
        return None
    if any(
        not character.isalpha() and character not in NAME_SEPARATORS
        for character in normalized
    ):
        return None
    if not normalized[0].isalpha():
        return None

    for index, character in enumerate(normalized):
        if character.isalpha():
            continue
        if character in NAME_APOSTROPHES:
            if index == 0 or not normalized[index - 1].isalpha():
                return None
            if index < len(normalized) - 1 and not normalized[index + 1].isalpha():
                return None
            continue
        if character in NAME_INFIX_SEPARATORS:
            if (
                index == 0
                or index == len(normalized) - 1
                or not normalized[index - 1].isalpha()
                or not normalized[index + 1].isalpha()
            ):
                return None
    return normalized


def is_yes(text):
    return text.strip().lower() in {
        "כן",
        "כן.",
        "נכון",
        "נכון.",
        "yes",
        "y",
    }


def is_no(text):
    return text.strip().lower() in {
        "לא",
        "לא.",
        "no",
        "n",
    }


def is_next(text):
    return text.strip() in {
        "הבא",
        "המשך",
        "סיימתי",
        "בוצע",
        "עשיתי",
    }
