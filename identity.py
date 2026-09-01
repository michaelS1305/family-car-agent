from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    name: str
    family_id: int | None
    carplay_setup_status: str = "pending"


@dataclass(frozen=True)
class AuthenticatedSupabaseUser:
    auth_user_id: str
