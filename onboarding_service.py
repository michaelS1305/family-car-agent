import json

from onboarding_rules import (
    is_next,
    is_no,
    is_valid_family_code,
    is_yes,
    parse_home_address,
)
from database import (
    create_family_with_first_user,
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
from carplay_config import CONNECT_SHORTCUT_URL, DISCONNECT_SHORTCUT_URL

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

        if not is_valid_family_code(family_code):
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

        shortcut_token = generate_shortcut_token()

        create_family_with_first_user(
            name=data["family_name"],
            family_code=data["family_code"],
            home_address=data["home_address"],
            user_name=user_name,
            shortcut_token=shortcut_token,
            telegram_chat_id=chat_id,
            home_latitude=data["home_latitude"],
            home_longitude=data["home_longitude"]
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
            "עכשיו הזן/י את הקוד המשפחתי בן 6 הספרות.\n"
            "הקוד מופיע בהודעה שקיבל בן או בת המשפחה שיצרו את המשפחה, "
            "יחד עם הקישור להזמנת בני המשפחה לבוט."
        )

    if step == "join_verify_family_code":
        family_code = text.strip()

        family = None
        if is_valid_family_code(family_code):
            family = get_family_by_code(family_code)

        if not family or family[0] != data["family_id"]:
            attempts = data.get("code_attempts", 0) + 1
            data["code_attempts"] = attempts

            if attempts >= 3:
                delete_onboarding_session(chat_id)
                return (
                    "הקוד שהוזן אינו נכון ❌\n\n"
                    "הגעת למספר הניסיונות המרבי, ולכן עצרתי את תהליך ההצטרפות.\n\n"
                    "בדוק/י עם בן או בת המשפחה שיצרו את המשפחה מהו הקוד המשפחתי. "
                    "הקוד מופיע בהודעה שקיבלו יחד עם הקישור להזמנת בני המשפחה לבוט.\n\n"
                    "לאחר שבדקת את הקוד, שלח/י /start כדי להתחיל מחדש."
                )

            save_onboarding_session(
                chat_id,
                step="join_verify_family_code",
                data=json.dumps(data)
            )

            if attempts == 2:
                return (
                    "הקוד שהוזן אינו נכון ❌\n\n"
                    "נותר לך ניסיון אחרון.\n\n"
                    "לפני שתנסה/י שוב, מומלץ לפנות לבן או בת המשפחה שיצרו את המשפחה "
                    "ולבקש מהם לבדוק את הקוד המשפחתי.\n"
                    "הקוד מופיע בהודעה שקיבלו יחד עם הקישור להזמנת בני המשפחה לבוט."
                )

            return (
                "הקוד שהוזן אינו נכון ❌\n\n"
                "נותרו לך 2 ניסיונות."
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
            "ועבור/י ללשונית ״פעולות אוטומטיות״.\n\n"
            "כשהגעת לשם, כתוב/י ״הבא״."
        )

    # -------------------------------------------------
    # CARPLAY CONNECT AUTOMATION
    # -------------------------------------------------

    if step == "carplay_connect_open_automation":
        if not is_next(text):
            return 'כשהגעת ללשונית ״פעולות אוטומטיות״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_trigger"
        )

        return (
            "שלב 2 מתוך 6:\n"
            "לחץ/י על + כדי ליצור פעולה אוטומטית חדשה ובחר/י ״CarPlay״.\n\n"
            "בחר/י רק באפשרות ״מחובר״.\n"
            "לאחר מכן בחר/י למטה באפשרות ״הפעל מיד״.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    if step == "carplay_connect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים/י להגדיר ״מחובר״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_shortcut"
        )

        return (
            "שלב 3 מתוך 6:\n"
            "לחץ/י על ״הבא״.\n"
            "בחלון שייפתח, בחר/י בשורה ״הקיצורים שלי״ ולאחר מכן בחר/י "
            "את הקיצור “Connect to CarPlay” שהתקנת קודם.\n\n"
            "שמור/י את הפעולה האוטומטית.\n\n"
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
            "מצוין ✅\n"
            "אוטומציית החיבור מוכנה.\n"
            "עכשיו נגדיר את הניתוק מהרכב.\n\n"
            "שלב 4 מתוך 6:\n"
            "חזור/י ללשונית ״פעולות אוטומטיות״ ולחץ/י שוב על +.\n"
            "בחר/י ״CarPlay״ והפעם בחר/י רק באפשרות ״מנותק״.\n\n"
            "❤️ חשוב: ודא/י שהאפשרות ״מחובר״ אינה מסומנת. "
            "אם היא מסומנת, בטל/י אותה והשאר/י רק את ״מנותק״.\n\n"
            "בחר/י למטה באפשרות ״הפעל מיד״.\n\n"
            "כשתסיים/י, כתוב/י ״הבא״."
        )

    if step == "carplay_disconnect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים/י להגדיר ״מנותק״, כתוב/י ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_disconnect_choose_shortcut"
        )

        return (
            "שלב 5 מתוך 6:\n"
            "לחץ/י על ״הבא״.\n"
            "בחלון שייפתח, בחר/י בשורה ״הקיצורים שלי״ ולאחר מכן בחר/י "
            "את הקיצור “Disconnect from CarPlay” שהתקנת קודם.\n\n"
            "שמור/י את הפעולה האוטומטית.\n\n"
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
            "זהו, ההגדרה הסתיימה! 🎉\n\n"
            "מעכשיו:\n"
            "🚗 כשהאייפון מתחבר ל-CarPlay, המערכת תדע שלקחת את הרכב.\n\n"
            "🏠 כשמכבים את הרכב ליד הבית, המערכת תשחרר אותו אוטומטית.\n\n"
            "חשוב: בפעם הראשונה שהפעולות האוטומטיות יפעלו, האייפון עשוי "
            "לבקש הרשאה להפעיל את הקיצורים, להשתמש במיקום או להתחבר לשרת.\n\n"
            "יש לאשר את ההרשאות ולבחור באפשרות שמאפשרת אותן גם בעתיד, כאשר היא מופיעה.\n\n"
            "ללא האישורים האלה, החיבור או הניתוק האוטומטי עלולים לא לעבוד.\n\n"
            "לאחר האישור הראשוני, הכול אמור לעבוד אוטומטית בלי שתצטרך/י לעשות דבר. 🚗\n\n"
            "כתוב/י לי ״סיימתי״ כדי לסיים את ההגדרה."
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
        "1. התקנת Connect to CarPlay\n"
        "פתח/י את הקישור המצורף. אפליקציית ״קיצורים״ תיפתח אוטומטית.\n"
        "לחץ/י על ״הוסף קיצור״.\n"
        "לאחר מכן תתבקש/י להזין את קוד החיבור. הדבק/י בתא הריק את הקוד "
        "ששלחתי לך בהודעה הקודמת ולחץ/י שוב על ״הוסף קיצור״.\n"
        f"{CONNECT_SHORTCUT_URL}\n\n"
        "2. התקנת Disconnect from CarPlay\n"
        "עכשיו עשה/י בדיוק אותו דבר עם הקיצור “Disconnect from CarPlay”:\n"
        "פתח/י את הקישור, לחץ/י על ״הוסף קיצור״, הדבק/י את אותו קוד החיבור "
        "בתא הריק ולחץ/י שוב על ״הוסף קיצור״.\n"
        f"{DISCONNECT_SHORTCUT_URL}\n\n"
        "אחרי שהתקנת את שני הקיצורים, כתוב/י לי ״התקנתי״ "
        "ואדריך אותך צעד־צעד בהגדרת הפעולות האוטומטיות של CarPlay."
    )
