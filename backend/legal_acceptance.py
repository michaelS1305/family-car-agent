"""Explicit onboarding acknowledgment; identity and time are never client fields."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator


class LegalAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_accepted: StrictBool
    terms_version: Literal["1.2"]
    privacy_version: Literal["1.2"]

    @field_validator("legal_accepted")
    @classmethod
    def require_acceptance(cls, value):
        if value is not True:
            raise ValueError("Legal acceptance is required")
        return value


def record_legal_acceptance(conn, auth_user_id, acceptance):
    # Validate even internal callers; no default or inferred acceptance.
    value = LegalAcceptance.model_validate(acceptance)
    conn.execute(
        """INSERT INTO legal_acceptances (auth_user_id, terms_version, privacy_version)
           VALUES (%s, %s, %s)
           ON CONFLICT (auth_user_id, terms_version, privacy_version) DO NOTHING""",
        (auth_user_id, value.terms_version, value.privacy_version),
    )
