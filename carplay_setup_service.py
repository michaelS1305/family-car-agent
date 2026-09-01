from dataclasses import dataclass

from carplay_config import CONNECT_SHORTCUT_URL, DISCONNECT_SHORTCUT_URL
from database import (
    UserNotFoundError,
    get_or_create_shortcut_token,
    set_carplay_setup_status,
)
from identity import CurrentUser


class CarPlaySetupError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class CarPlaySetup:
    connection_code: str
    connect_shortcut_url: str
    disconnect_shortcut_url: str


def prepare_carplay_setup(current_user: CurrentUser):
    if current_user.family_id is None:
        raise CarPlaySetupError(
            "CARPLAY_SETUP_UNAVAILABLE",
            "יש להשלים תחילה את ההצטרפות למשפחה.",
            409,
        )

    try:
        connection_code = get_or_create_shortcut_token(current_user.user_id)
    except UserNotFoundError as exc:
        raise CarPlaySetupError(
            "AUTH_USER_NOT_FOUND",
            "לא הצלחנו למצוא את חשבון המשתמש. התחבר מחדש ונסה שוב.",
            403,
        ) from exc

    return CarPlaySetup(
        connection_code=connection_code,
        connect_shortcut_url=CONNECT_SHORTCUT_URL,
        disconnect_shortcut_url=DISCONNECT_SHORTCUT_URL,
    )


def update_carplay_setup_status(current_user: CurrentUser, setup_status: str):
    if setup_status not in {"completed", "skipped"}:
        raise CarPlaySetupError(
            "INVALID_CARPLAY_SETUP_STATUS",
            "מצב הגדרת CarPlay אינו תקין.",
            422,
        )
    try:
        return set_carplay_setup_status(current_user.user_id, setup_status)
    except UserNotFoundError as exc:
        raise CarPlaySetupError(
            "AUTH_USER_NOT_FOUND",
            "לא הצלחנו למצוא את חשבון המשתמש. התחבר מחדש ונסה שוב.",
            403,
        ) from exc
