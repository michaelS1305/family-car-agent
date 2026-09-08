from typing import Literal
from datetime import datetime
from uuid import UUID
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CarConnection(BaseModel):
    shortcut_token: str
    latitude: float | None = None
    longitude: float | None = None


class CarDisconnectRequest(BaseModel):
    shortcut_token: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class CarPlaySetupResponse(BaseModel):
    connection_code: str
    connect_shortcut_url: str
    disconnect_shortcut_url: str


class CarPlaySetupStatusRequest(BaseModel):
    status: Literal["completed", "skipped"]


class CarStatusResponse(BaseModel):
    status: Literal["available", "occupied"]


def _validate_push_endpoint(value):
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or len(value) > 4096:
        raise ValueError("endpoint must be a valid HTTPS URL")
    return value


class PushConfigResponse(BaseModel):
    enabled: bool
    public_vapid_key: str | None


class PushSubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str
    auth: str

    @field_validator("p256dh", "auth")
    @classmethod
    def validate_key(cls, value):
        if not 1 <= len(value) <= 1024:
            raise ValueError("push subscription key length is invalid")
        return value


class PushSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    expiration_time: int | None = None
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value):
        return _validate_push_endpoint(value)

    @field_validator("expiration_time")
    @classmethod
    def validate_expiration_time(cls, value):
        if value is not None and not 0 <= value <= 253_402_300_799_999:
            raise ValueError("expiration_time is outside the supported range")
        return value


class PushSubscriptionRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value):
        return _validate_push_endpoint(value)


class ActiveCarUsageResponse(BaseModel):
    name: str
    started_at: str


class CompletedCarUsageResponse(BaseModel):
    name: str
    started_at: str
    ended_at: str


class CarHistoryResponse(BaseModel):
    active_usage: ActiveCarUsageResponse | None
    recent_usage: list[CompletedCarUsageResponse]


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


class FamilyAddressResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_address: str


class FamilyAddressResolveResponse(BaseModel):
    normalized_address: str
    display_address: str
    resolution_token: str


class FamilyAddressUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_token: str


class FamilyAddressUpdateResponse(BaseModel):
    home_address: str


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
