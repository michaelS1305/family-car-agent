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


def handle_onboarding(chat_id, text):
    session = get_onboarding_session(chat_id)

    # Start onboarding
    if text == "/start" and not session:
        save_onboarding_session(
            chat_id,
            step="choose_action"
        )

        return (
            "ברוך הבא 👋\n\n"
            "כתוב:\n"
            "1 - ליצור משפחה חדשה\n"
            "2 - להצטרף למשפחה קיימת"
        )

    if not session:
        return "שלח /start כדי להתחיל הרשמה."

    step, data = session

    if data:
        data = json.loads(data)
    else:
        data = {}

    # Choose create/join
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

        return "כתוב 1 כדי ליצור משפחה או 2 כדי להצטרף למשפחה קיימת."

    # -------------------------
    # CREATE FAMILY FLOW
    # -------------------------

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

        delete_onboarding_session(chat_id)

        return (
            f"נרשמת בהצלחה ✅\n"
            f"משפחה: {data['family_name']}\n"
            f"שם: {user_name}\n\n"
            "עכשיו נשאר לחבר את האייפון שלך לרכב."
        )

    # -------------------------
    # JOIN FAMILY FLOW
    # -------------------------

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

        return f"מצאתי את משפחת {family[1]} ✅\nמה השם שלך?"

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

        delete_onboarding_session(chat_id)

        return (
            f"הצטרפת בהצלחה למשפחת {data['family_name']} ✅\n"
            f"ברוך הבא, {user_name}!"
        )

    return "משהו השתבש בתהליך ההרשמה. שלח /start כדי להתחיל מחדש."