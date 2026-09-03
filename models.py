from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class CarConnection(BaseModel):
    shortcut_token: str
    latitude: float | None = None
    longitude: float | None = None


class CarPlaySetupResponse(BaseModel):
    connection_code: str
    connect_shortcut_url: str
    disconnect_shortcut_url: str


class CarPlaySetupStatusRequest(BaseModel):
    status: Literal["completed", "skipped"]


class CarStatusResponse(BaseModel):
    status: Literal["available", "occupied"]


class CreateFamilyAddressRequest(BaseModel):
    home_address: str


class CreateFamilyRequest(BaseModel):
    family_name: str
    family_code: str
    address_resolution_token: str
    user_name: str


class JoinFamilyNameRequest(BaseModel):
    family_name: str


class JoinFamilyAddressRequest(BaseModel):
    home_address: str


class JoinFamilyAddressConfirmationRequest(BaseModel):
    confirmed: bool


class JoinFamilyCodeRequest(BaseModel):
    family_code: str


class JoinFamilyCompleteRequest(BaseModel):
    user_name: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):
        normalized = value.strip()
        if not 1 <= len(normalized) <= 4000:
            raise ValueError("message must contain between 1 and 4000 characters")
        return normalized
