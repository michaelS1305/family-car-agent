from typing import Literal
from datetime import datetime
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


class FamilyMemberResponse(BaseModel):
    member_ref: UUID
    name: str
    role: Literal["parent", "child"] | None
    is_family_admin: bool


class FamilyResponse(BaseModel):
    name: str
    home_address: str
    family_code: str
    can_edit_roles: bool
    members: list[FamilyMemberResponse]


class FamilyRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["parent", "child"] | None


class ReservationResponse(BaseModel):
    owner_name: str
    start_time: str
    end_time: str
    is_mine: bool


class ReservationIntervalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: datetime
    end_time: datetime


class ReservationUpdateRequest(ReservationIntervalRequest):
    original_start_time: str
    original_end_time: str

    @field_validator("original_start_time", "original_end_time")
    @classmethod
    def validate_original_time(cls, value):
        datetime.fromisoformat(value)
        return value


class ReservationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_start_time: str
    original_end_time: str

    @field_validator("original_start_time", "original_end_time")
    @classmethod
    def validate_original_time(cls, value):
        datetime.fromisoformat(value)
        return value


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
