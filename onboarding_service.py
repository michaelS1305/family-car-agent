import json

from database import (
    create_family,
    get_family_by_code,
    insert_user,
    generate_shortcut_token,
    get_onboarding_session,
    save_onboarding_session,
    delete_onboarding_session,
)


CONNECT_SHORTCUT_URL = (
    "https://www.icloud.com/shortcuts/"
    "ff71e78ac7ee4a03a844969db841cf80"
)

DISCONNECT_SHORTCUT_URL = (
    "https://www.icloud.com/shortcuts/"
    "08c79c43d9f5454b803a30d561add06c"
)


def handle_onboarding(chat_id, text):
    session = get_onboarding_session(chat_id)

    # -------------------------------------------------
    # START
    # -------------------------------------------------

    if text == "/start" and not session:
        save_onboarding_session(
            chat_id,
            step="choose_action"
        )

        return (
            "ברוך הבא ל-Family Car Agent 🚗\n\n"
            "הבוט עוזר למשפחה לנהל רכב משותף בצורה אוטומטית.\n"
            "הוא יודע לזהות מי משתמש ברכב, לבדוק אם הוא פנוי, "
            "לנהל הזמנות ולעדכן את בני המשפחה.\n\n"
            "ההרשמה נדרשת רק פעם אחת.\n\n"
            "כדי להתחיל, כתוב:\n"
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

            return "איך תרצה לקרוא למשפחה?"

        if text == "2":
            save_onboarding_session(
                chat_id,
                step="join_family_code"
            )

            return "מה הקוד המשפחתי?"

        return (
            "כתוב 1 כדי ליצור משפחה "
            "או 2 כדי להצטרף למשפחה קיימת."
        )

    # -------------------------------------------------
    # CREATE FAMILY
    # -------------------------------------------------

    if step == "create_family_name":
        data["family_name"] = text

        save_onboarding_session(
            chat_id,
            step="create_family_code",
            data=json.dumps(data)
        )

        return (
            "בחר קוד משפחתי.\n"
            "בני המשפחה האחרים ישתמשו בו כדי להצטרף."
        )

    if step == "create_family_code":
        existing_family = get_family_by_code(text)

        if existing_family:
            return "הקוד הזה כבר תפוס. בחר קוד אחר."

        data["family_code"] = text

        save_onboarding_session(
            chat_id,
            step="create_family_address",
            data=json.dumps(data)
        )

        return "מה כתובת הבית של המשפחה?"

    if step == "create_family_address":
        data["home_address"] = text

        save_onboarding_session(
            chat_id,
            step="create_user_name",
            data=json.dumps(data)
        )

        return "מה השם שלך?"

    if step == "create_user_name":
        user_name = text

        family_id = create_family(
            name=data["family_name"],
            family_code=data["family_code"],
            home_address=data["home_address"]
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

        return build_shortcut_setup_message(
            family_name=data["family_name"],
            user_name=user_name,
            shortcut_token=shortcut_token,
            joined=False
        )

    # -------------------------------------------------
    # JOIN FAMILY
    # -------------------------------------------------

    if step == "join_family_code":
        family = get_family_by_code(text)

        if not family:
            return "לא מצאתי משפחה עם הקוד הזה. נסה שוב."

        data["family_id"] = family[0]
        data["family_name"] = family[1]

        save_onboarding_session(
            chat_id,
            step="join_user_name",
            data=json.dumps(data)
        )

        return (
            f"מצאתי את משפחת {family[1]} ✅\n"
            "מה השם שלך?"
        )

    if step == "join_user_name":
        user_name = text

        shortcut_token = generate_shortcut_token()

        insert_user(
            name=user_name,
            phone_number=None,
            shortcut_token=shortcut_token,
            telegram_chat_id=chat_id,
            family_id=data["family_id"]
        )

        save_onboarding_session(
            chat_id,
            step="waiting_for_shortcuts_install"
        )

        return build_shortcut_setup_message(
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
                "כתוב לי ״התקנתי״."
            )

        save_onboarding_session(
            chat_id,
            step="carplay_connect_open_automation"
        )

        return (
            "מעולה ✅\n"
            "עכשיו נגדיר את CarPlay כך שהכול יעבוד אוטומטית.\n\n"
            "שלב 1 מתוך 6:\n"
            "פתח באייפון את אפליקציית ״קיצורים״ "
            "ועבור ללשונית ״אוטומציה״.\n\n"
            "כשהגעת לשם, כתוב ״הבא״."
        )

    # -------------------------------------------------
    # CARPLAY CONNECT AUTOMATION
    # -------------------------------------------------

    if step == "carplay_connect_open_automation":
        if not is_next(text):
            return 'כשהגעת ללשונית ״אוטומציה״, כתוב ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_trigger"
        )

        return (
            "שלב 2 מתוך 6:\n"
            "לחץ על + ליצירת אוטומציה חדשה "
            "ובחר ״CarPlay״.\n\n"
            "בחר ״מתחבר״.\n"
            "אם מופיעה האפשרות ״הפעל מיד״ — בחר בה.\n\n"
            "כשתסיים, כתוב ״הבא״."
        )

    if step == "carplay_connect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים להגדיר ״מתחבר״, כתוב ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_connect_choose_shortcut"
        )

        return (
            "שלב 3 מתוך 6:\n"
            "בחר פעולה של ״הפעל קיצור״ "
            "ובחר את קיצור ה-Connect שהתקנת קודם.\n\n"
            "שמור את האוטומציה.\n\n"
            "כשתסיים, כתוב ״הבא״."
        )

    # -------------------------------------------------
    # CARPLAY DISCONNECT AUTOMATION
    # -------------------------------------------------

    if step == "carplay_connect_choose_shortcut":
        if not is_next(text):
            return 'אחרי ששמרת את אוטומציית החיבור, כתוב ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_disconnect_choose_trigger"
        )

        return (
            "מצוין ✅ אוטומציית החיבור מוכנה.\n\n"
            "שלב 4 מתוך 6:\n"
            "חזור ללשונית ״אוטומציה״ ולחץ שוב על +.\n"
            "בחר ״CarPlay״ והפעם בחר ״מתנתק״.\n\n"
            "אם מופיעה האפשרות ״הפעל מיד״ — בחר בה.\n\n"
            "כשתסיים, כתוב ״הבא״."
        )

    if step == "carplay_disconnect_choose_trigger":
        if not is_next(text):
            return 'כשתסיים להגדיר ״מתנתק״, כתוב ״הבא״.'

        save_onboarding_session(
            chat_id,
            step="carplay_disconnect_choose_shortcut"
        )

        return (
            "שלב 5 מתוך 6:\n"
            "בחר פעולה של ״הפעל קיצור״ "
            "ובחר את קיצור ה-Disconnect שהתקנת קודם.\n\n"
            "שמור את האוטומציה.\n\n"
            "כשתסיים, כתוב ״הבא״."
        )

    # -------------------------------------------------
    # FINISH
    # -------------------------------------------------

    if step == "carplay_disconnect_choose_shortcut":
        if not is_next(text):
            return 'אחרי ששמרת את אוטומציית הניתוק, כתוב ״הבא״.'

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
            "🏠 כשאתה מכבה את הרכב ליד הבית, "
            "המערכת תשחרר אותו אוטומטית.\n\n"
            "כתוב ״סיימתי״ כדי לסיים את ההגדרה."
        )

    if step == "carplay_setup_complete":
        if text.strip() != "סיימתי":
            return 'כשהכול מוכן, כתוב ״סיימתי״.'

        delete_onboarding_session(chat_id)

        return (
            "הכול מוכן 🎉🚗\n\n"
            "Family Car Agent פעיל עכשיו.\n"
            "מכאן אפשר פשוט לדבר איתי כרגיל.\n\n"
            "לדוגמה:\n"
            "• מי עם הרכב?\n"
            "• הרכב פנוי?\n"
            "• אני צריך את הרכב מחר מ-18:00 עד 20:00\n"
            "• אילו הזמנות יש לי?"
        )

    return (
        "משהו השתבש בתהליך ההגדרה. "
        "נסה שוב או שלח /start."
    )


def build_shortcut_setup_message(
    family_name,
    user_name,
    shortcut_token,
    joined
):
    if joined:
        intro = (
            f"הצטרפת בהצלחה למשפחת {family_name} ✅\n"
            f"ברוך הבא, {user_name}!"
        )
    else:
        intro = (
            f"נרשמת בהצלחה ✅\n"
            f"משפחה: {family_name}\n"
            f"שם: {user_name}"
        )

    return (
        f"{intro}\n\n"
        "עכשיו נחבר את האייפון לרכב 🚗\n\n"
        f"קוד החיבור שלך:\n"
        f"{shortcut_token}\n\n"
        "1. התקן את Connect Shortcut:\n"
        f"{CONNECT_SHORTCUT_URL}\n\n"
        "2. התקן את Disconnect Shortcut:\n"
        f"{DISCONNECT_SHORTCUT_URL}\n\n"
        "בשני הקיצורים, כשהם מבקשים קוד חיבור, "
        "הדבק את קוד החיבור שמופיע למעלה.\n\n"
        "אחרי שהתקנת את שני הקיצורים, "
        "כתוב לי ״התקנתי״ "
        "ואדריך אותך צעד־צעד בהגדרת האוטומציות של CarPlay."
    )


def is_next(text):
    return text.strip() in {
        "הבא",
        "המשך",
        "סיימתי",
        "בוצע",
        "עשיתי",
    }