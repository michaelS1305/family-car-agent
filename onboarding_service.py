import json

from database import (
    create_family,
    get_family_by_code,
    get_family_by_name_and_location,
    get_family_by_location,
    insert_user,
    generate_shortcut_token,
    get_onboarding_session,
    save_onboarding_session,
    delete_onboarding_session,
)
from geocoding_service import geocode_address
from telegram_service import send_telegram_message


CONNECT_SHORTCUT_URL = "https://www.icloud.com/shortcuts/7a4ba428c6464f95894564e0f20e6f76"

DISCONNECT_SHORTCUT_URL = "https://www.icloud.com/shortcuts/825de2b3834640f4888b9e265454e22b"

BOT_URL = "https://t.me/family_car_agent_bot"

def handle_onboarding(chat_id, text):
    session = get_onboarding_session(chat_id)

    # -------------------------------------------------
    # START
    # -------------------------------------------------

    if text == "/start":
        if session:
            delete_onboarding_session(chat_id)

        save_onboarding_session(
            chat_id,
            step="choose_action"
        )

        return (
            "ברוך/ה הבא/ה ל-Family Car Agent 🚗\n\n"
            "הבוט עוזר למשפחה לנהל רכב משותף בצורה אוטומטית.\n"
            "הוא יודע לזהות מי משתמש ברכב, לבדוק אם הוא פנוי, "
            "לנהל הזמנות ולעדכן את בני המשפחה.\n\n"
            "ההרשמה נדרשת רק פעם אחת.\n\n"
            "כדי להתחיל, כתוב/י:\n"
            "1 - ליצור משפחה חדשה\n"
            "2 - להצטרף למשפחה קיימת"
        )

    if not session:
        return None

    step, data = session

    if data:
        data = json.loads(data)
    else:
        data = {}

    # -------------------------------------------------
    # CHOOSE CREATE / JOIN
    # -------------------------------------------------

    if step == "choose_action":
        if text == "1":
            save_onboarding_session(
                chat_id,
                step="create_family_name"
            )
            return "איך תרצה/י לקרוא למשפחה?"

        if text == "2":
            save_onboarding_session(
                chat_id,
                step="join_family_code"
            )
            return "מה שם המשפחה שאליה תרצה/י להצטרף?\n\nלדוגמה: כהן"

        return (
            "כתוב/י 1 כדי ליצור משפחה "
            "או 2 כדי להצטרף למשפחה קיימת."
        )

    # -------------------------------------------------
    # CREATE FAMILY
    # -------------------------------------------------

    if step == "create_family_name":
        family_name = text.strip()

        if not family_name:
            return "יש להזין שם למשפחה."

        data["family_name"] = family_name

        save_onboarding_session(
            chat_id,
            step="create_family_code",
            data=json.dumps(data)
        )

        return (
            "בחר/י קוד משפחתי בן 6 ספרות.\n"
            "בני המשפחה האחרים ישתמשו בו פעם אחת כדי להצטרף.\n\n"
            "לדוגמה: 482731"
        )

    if step == "create_family_code":
        family_code = text.strip()

        if not family_code.isdigit() or len(family_code) != 6:
            return (
                "הקוד המשפחתי חייב להכיל בדיוק 6 ספרות.\n"
                "לדוגמה: 482731"
            )

        existing_family = get_family_by_code(family_code)

        if existing_family:
            return "הקוד הזה כבר תפוס. בחר/י קוד אחר."

        data["family_code"] = family_code

        save_onboarding_session(
            chat_id,
            step="create_family_address",
            data=json.dumps(data)
        )

        return (
            "מה כתובת הבית של המשפחה? 🏠\n\n"
            "כתוב/י את הכתובת בפורמט:\n"
            "עיר, רחוב, מספר בית\n\n"
            "לדוגמה:\n"
            "תל אביב, דיזנגוף, 120"
        )

    if step == "create_family_address":
        parsed_address = parse_home_address(text)

        if not parsed_address:
            return (
                "הכתובת לא נראית מלאה.\n\n"
                "נסה/י שוב בפורמט:\n"
                "עיר, רחוב, מספר בית\n\n"
                "לדוגמה:\n"
                "תל אביב, דיזנגוף, 120"
            )

        city, street, house_number = parsed_address

        try:
            location = geocode_address(
                city=city,
                street=street,
                house_number=house_number
            )
        except Exception:
            return (
                "לא הצלחתי לבדוק את הכתובת כרגע.\n"
                "נסה/י שוב בעוד כמה רגעים."
            )

        if not location:
            return (
                "לא הצלחתי למצוא את הכתובת הזאת 📍\n\n"
                "בדוק/י שהעיר, הרחוב ומספר הבית נכונים "
                "ונסה/י שוב.\n\n"
                "לדוגמה:\n"
                "תל אביב, דיזנגוף, 120"
            )

        normalized_address = f"{city}, {street}, {house_number}"

        data["home_address"] = normalized_address
        data["home_latitude"] = location["latitude"]
        data["home_longitude"] = location["longitude"]
        data["geocoded_address"] = location["address"]

        save_onboarding_session(
            chat_id,
            step="confirm_family_address",
            data=json.dumps(data)
        )

        return (
            "מצאתי את הכתובת הבאה 📍\n\n"
            f"{location['address']}\n\n"
            "האם זו כתובת הבית של המשפחה?\n"
            "כתוב/י ״כן״ או ״לא״."
        )

    if step == "confirm_family_address":
        if is_yes(text):
            existing_family = get_family_by_location(
                data["home_latitude"],
                data["home_longitude"]
            )

            if existing_family:
                delete_onboarding_session(chat_id)
                return (
                    "כבר קיימת משפחה הרשומה בכתובת הזאת 🏠\n\n"
                    "אם זו המשפחה שלך, אין צורך ליצור משפחה חדשה.\n"
                    "שלח/י /start ובחר/י ״להצטרף למשפחה קיימת״."
                )

            save_onboarding_session(
                chat_id,
                step="create_user_name",
                data=json.dumps(data)
            )
            return "מעולה ✅\nמה השם שלך?"

        if is_no(text):
            for key in (
                "home_address",
                "home_latitude",
                "home_longitude",
                "geocoded_address",
            ):
                data.pop(key, None)

            save_onboarding_session(
                chat_id,
                step="create_family_address",
                data=json.dumps(data)
            )

            return (
                "אין בעיה.\n"
                "הזן/י שוב את כתובת הבית בפורמט:\n"
                "עיר, רחוב, מספר בית\n\n"
                "לדוגמה:\n"
                "תל אביב, דיזנגוף, 120"
            )

        return "כתוב/י ״כן״ אם הכתובת נכונה או ״לא״ כדי להזין אותה מחדש."

    if step == "create_user_name":
        user_name = text.strip()

        if not user_name:
            return "יש להזין שם."

        family_id = create_family(
            name=data["family_name"],
            family_code=data["family_code"],
            home_address=data["home_address"],
            home_latitude=data["home_latitude"],
            home_longitude=data["home_longitude"]
        )

        shortcut_token = generate_shortcut_token()

        insert_user(
            name=user_name,
            phone_number=None,
            shortcut_token=shortcut_token,
            telegram_chat_id=chat_id,
            family_id=family_id
        )

        save_onboarding_session(
            chat_id,
            step="waiting_for_shortcuts_install"
        )

        send_telegram_message(
            chat_id,
            (
                "קוד המשפחה שלך הוא:\n"
                f"{data['family_code']}\n\n"
                "שמור/י את הקוד הזה. בני המשפחה יצטרכו אותו פעם אחת כדי להצטרף.\n\n"
                "אפשר לשלוח להם גם את הקישור לבוט:\n"
                f"{BOT_URL}"
            )
        )

        return build_shortcut_setup_message(
            chat_id=chat_id,
            family_name=data["family_name"],
            user_name=user_name,
            shortcut_token=shortcut_token,
            joined=False
        )

    # -------------------------------------------------
    # JOIN FAMILY
    # -------------------------------------------------

    if step == "join_family_code":
        family_name = text.strip()

        if not family_name:
            return "יש להזין את שם המשפחה."

        data["family_name"] = family_name
        save_onboarding_session(chat_id, step="join_family_address", data=json.dumps(data))

        return (
            f"מעולה. עכשיו נוודא שזו משפחת {family_name} הנכונה 🏠\n\n"
            "מה כתובת הבית של המשפחה?\n"
            "כתוב/י בפורמט:\nעיר, רחוב, מספר בית\n\n"
            "לדוגמה:\nתל אביב, דיזנגוף, 120"
        )

    if step == "join_family_address":
        parsed_address = parse_home_address(text)
        if not parsed_address:
            return (
                "הכתובת לא נראית מלאה.\n\n"
                "נסה/י שוב בפורמט:\nעיר, רחוב, מספר בית\n\n"
                "לדוגמה:\nתל אביב, דיזנגוף, 120"
            )

        city, street, house_number = parsed_address

        try:
            location = geocode_address(city=city, street=street, house_number=house_number)
        except Exception:
            return "לא הצלחתי לבדוק את הכתובת כרגע.\nנסה/י שוב בעוד כמה רגעים."

        if not location:
            return (
                "לא הצלחתי למצוא את הכתובת הזאת 📍\n\n"
                "בדוק/י שהעיר, הרחוב ומספר הבית נכונים ונסה/י שוב."
            )

        data["join_home_latitude"] = location["latitude"]
        data["join_home_longitude"] = location["longitude"]
        data["join_geocoded_address"] = location["address"]

        save_onboarding_session(
            chat_id,
            step="confirm_join_family_address",
            data=json.dumps(data)
        )

        return (
            "מצאתי את הכתובת הבאה 📍\n\n"
            f"{location['address']}\n\n"
            "האם זו כתובת הבית של המשפחה?\n"
            "כתוב/י ״כן״ או ״לא״."
        )

    if step == "confirm_join_family_address":
        if is_no(text):
            for key in ("join_home_latitude", "join_home_longitude", "join_geocoded_address"):
                data.pop(key, None)

            save_onboarding_session(chat_id, step="join_family_address", data=json.dumps(data))
            return "אין בעיה.\nהזן/י שוב את כתובת הבית בפורמט:\nעיר, רחוב, מספר בית"

        if not is_yes(text):
            return "כתוב/י ״כן״ אם הכתובת נכונה או ״לא״ כדי להזין אותה מחדש."

        family = get_family_by_name_and_location(
            data["family_name"],
            data["join_home_latitude"],
            data["join_home_longitude"]
        )

        if not family:
            return (
                "לא מצאתי משפחה שמתאימה לשם ולכתובת שהזנת.\n\n"
                "בדוק/י את הפרטים עם בן/בת המשפחה שיצרו את המשפחה, "
                "או שלח/י /start כדי להתחיל מחדש."
            )

        data["family_id"] = family[0]
        data["family_name"] = family[1]
        data["code_attempts"] = 0
        save_onboarding_session(chat_id, step="join_verify_family_code", data=json.dumps(data))

        return (
            f"מצאתי את משפחת {family[1]} ✅\n\n"
            "עכשיו הזן/י את הקוד המשפחתי בן 6 הספרות "
            "שקיבלתם בזמן יצירת המשפחה."
        )

    if step == "join_verify_family_code":
        family_code = text.strip()

        if not family_code.isdigit() or len(family_code) != 6:
            return "הקוד המשפחתי חייב להכיל בדיוק 6 ספרות.\nנסה/י שוב."

        family = get_family_by_code(family_code)

        if not family or family[0] != data["family_id"]:
            attempts = data.get("code_attempts", 0) + 1
            data["code_attempts"] = attempts

            if attempts >= 10:
                delete_onboarding_session(chat_id)
                return (
                    "בוצעו 10 ניסיונות עם קוד לא נכון, ולכן עצרתי את ההצטרפות.\n\n"
                    "בדוק/י עם בן/בת המשפחה שיצרו את המשפחה מהו הקוד שקיבלו "
                    "בתהליך ההרשמה, ואז שלח/י /start כדי להתחיל מחדש."
                )

            save_onboarding_session(chat_id, step="join_verify_family_code", data=json.dumps(data))
            return (
                "הקוד המשפחתי שהוזן אינו נכון.\n\n"
                "בקש/י מבן/בת המשפחה שיצרו את המשפחה לבדוק את הקוד "
                "שקיבלו בתהליך ההרשמה ונסה/י שוב.\n\n"
                f"נשארו {10 - attempts} ניסיונות."
            )

        save_onboarding_session(chat_id, step="join_user_name", data=json.dumps(data))
        return "הקוד נכון ✅\nמה השם שלך?"

    if step == "join_user_name":
        user_name = text.strip()
        if not user_name:
            return "יש להזין שם."

        shortcut_token = generate_shortcut_token()
        insert_user(
            name=user_name,
            phone_number=None,
            shortcut_token=shortcut_token,
            telegram_chat_id=chat_id,
            family_id=data["family_id"]
        )

        save_onboarding_session(chat_id, step="waiting_for_shortcuts_install")

        return build_shortcut_setup_message(
            chat_id=chat_id,
            family_name=data["family_name"],
            user_name=user_name,
            shortcut_token=shortcut_token,
            joined=True
        )

    # -------------------------------------------------
    # WAITING FOR SHORTCUT INSTALLATION
    # -------------------------------------------------

    if step == "waiting_for_shortcuts_install":
        if text.strip() != "התקנתי":
            return (
                "אחרי שהתקנת את שני הקיצורים, "
                "כתוב/י לי ״התקנתי״."
            )

        save_onboarding_session(
            chat_id,
            step="carplay_connect_open_automation"
        )

        return (
            "מעולה ✅\n"
            "עכשיו נגדיר את CarPlay כך שהכול יעבוד אוטומטית.\n\n"
            "שלב 1 מתוך 6:\n"
            "פתח/י באייפון את אפליקציית ״קיצורים״ "
            "ועבור/י ללשונית ״אוטומציה״.\n\n"
            "כשהגעת לשם, כתוב/י ״הבא״."
        )

    # -------------------------------------------------
    # CARPLAY CONNECT AUTOMATION
    # -------------------------------------------------

    if step == "carplay_connect_open_automation":
        if not is_next(text):
            return 'כשהגעת ללשונית ״אוטומציה״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_trigger"
        )

        return (
            "שלב 2 מתוך 6:\n"
            "לחץ/י על + ליצירת אוטומציה חדשה "
            "ובחר/י ״CarPlay״.\n\n"
            "בחר/י ״מתחבר״.\n"
            "אם מופיעה האפשרות ״הפעל מיד״ — בחר/י בה.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    if step == "carplay_connect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים/י להגדיר ״מתחבר״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_shortcut"
        )

        return (
            "שלב 3 מתוך 6:\n"
            "בחר/י פעולה של ״הפעל קיצור״ "
            "ובחר/י את קיצור ה-Connect שהותקן קודם.\n\n"
            "שמור/י את האוטומציה.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    # -------------------------------------------------
    # CARPLAY DISCONNECT AUTOMATION
    # -------------------------------------------------

    if step == "carplay_connect_choose_shortcut":
        if not is_next(text):
            return 'אחרי ששמרת את אוטומציית החיבור, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_disconnect_choose_trigger"
        )

        return (
            "מצוין ✅ אוטומציית החיבור מוכנה.\n\n"
            "שלב 4 מתוך 6:\n"
            "חזור/י ללשונית ״אוטומציה״ ולחץ/י שוב על +.\n"
            "בחר/י ״CarPlay״ והפעם בחר/י ״מתנתק״.\n\n"
            "אם מופיעה האפשרות ״הפעל מיד״ — בחר/י בה.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    if step == "carplay_disconnect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים/י להגדיר ״מתנתק״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_disconnect_choose_shortcut"
        )

        return (
            "שלב 5 מתוך 6:\n"
            "בחר/י פעולה של ״הפעל קיצור״ "
            "ובחר/י את קיצור ה-Disconnect שהותקן קודם.\n\n"
            "שמור/י את האוטומציה.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    # -------------------------------------------------
    # FINISH
    # -------------------------------------------------

    if step == "carplay_disconnect_choose_shortcut":
        if not is_next(text):
            return 'אחרי ששמרת את אוטומציית הניתוק, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_setup_complete"
        )

        return (
            "שלב 6 מתוך 6 ✅\n\n"
            "ההגדרה הסתיימה.\n\n"
            "מעכשיו:\n"
            "🚗 כשהאייפון מתחבר ל-CarPlay, "
            "המערכת תדע שלקחת את הרכב.\n\n"
            "🏠 כשמכבים את הרכב ליד הבית, "
            "המערכת תשחרר אותו אוטומטית.\n\n"
            "חשוב: בפעם הראשונה שהאוטומציות פועלות, האייפון עשוי להציג "
            "בקשות הרשאה עבור הקיצורים, המיקום או החיבור לשרת. "
            "יש לאשר את ההרשאות ולאפשר אותן גם להמשך כשמופיעה אפשרות כזאת. "
            "בלי האישור הראשוני, החיבור או הניתוק האוטומטי עלולים לא לעבוד.\n\n"
            "אחרי האישור הראשוני, הכול אמור לעבוד אוטומטית.\n\n"
            "כתוב/י ״סיימתי״ כדי לסיים את ההגדרה."
        )

    if step == "carplay_setup_complete":
        if text.strip() != "סיימתי":
            return 'כשהכול מוכן, כתוב/י ״סיימתי״.'

        delete_onboarding_session(chat_id)

        return (
            "הכול מוכן 🎉🚗\n\n"
            "Family Car Agent פעיל עכשיו.\n"
            "מכאן אפשר פשוט לדבר איתי כרגיל.\n\n"
            "לדוגמה:\n"
            "• מי עם הרכב?\n"
            "• הרכב פנוי?\n"
            "• אני צריך/ה את הרכב מחר מ-18:00 עד 20:00\n"
            "• אילו הזמנות יש לי?"
        )

    return (
        "משהו השתבש בתהליך ההגדרה. "
        "נסה/י שוב או שלח/י /start."
    )


def build_shortcut_setup_message(
    chat_id,
    family_name,
    user_name,
    shortcut_token,
    joined
):
    if joined:
        intro = (
            f"הצטרפת בהצלחה למשפחת {family_name} ✅\n"
            f"ברוך/ה הבא/ה, {user_name}!"
        )
    else:
        intro = (
            f"נרשמת בהצלחה ✅\n"
            f"משפחה: {family_name}\n"
            f"שם: {user_name}"
        )

    send_telegram_message(chat_id, shortcut_token)

    return (
        f"{intro}\n\n"
        "עכשיו נחבר את האייפון לרכב 🚗\n\n"
        "שלחתי לך את קוד החיבור בהודעה נפרדת כדי שיהיה קל להעתיק אותו.\n\n"
        "1. פתח/י את הקישור של Connect. ייפתח חלון באפליקציית ״קיצורים״.\n"
        "לחץ/י על ״הוסף קיצור״, ורק אז הדבק/י את קוד החיבור כשמתבקשים.\n"
        f"{CONNECT_SHORTCUT_URL}\n\n"
        "2. עשה/י בדיוק אותו דבר עם Disconnect:\n"
        "פתח/י את הקישור, לחץ/י על ״הוסף קיצור״, ואז הדבק/י את אותו קוד החיבור.\n"
        f"{DISCONNECT_SHORTCUT_URL}\n\n"
        "אחרי שהתקנת את שני הקיצורים, כתוב/י לי ״התקנתי״ "
        "ואדריך אותך צעד־צעד בהגדרת האוטומציות של CarPlay."
    )

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