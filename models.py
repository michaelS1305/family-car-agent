from typing import Literal

from pydantic import BaseModel


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
