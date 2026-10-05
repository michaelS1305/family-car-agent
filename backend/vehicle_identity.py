"""Read-only Vehicle Identity primitives; no pool, network or mutation ownership.

Callers supply their connection and authenticated CurrentUser. Future mutations
must keep fencing, resolution and mutation in the SAME outer transaction, and
acquire the appropriate operation/device locks before acting on these snapshots.
These helpers do not provide event admission or concurrency authorization.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from deletion_gate import require_user
from identity import CurrentUser


class VehicleView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vehicle_ref: UUID
    display_name: str
    retired_at: datetime | None


class DeviceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    device_ref: UUID
    platform: Literal["android", "ios"]
    revoked_at: datetime | None


@dataclass(frozen=True)
class VehicleRecord:
    id: int
    vehicle_ref: UUID
    display_name: str
    retired_at: datetime | None

    @property
    def is_active(self):
        return self.retired_at is None

    def public(self):
        return VehicleView(vehicle_ref=self.vehicle_ref, display_name=self.display_name,
                           retired_at=self.retired_at)


@dataclass(frozen=True)
class DeviceRecord:
    id: int
    device_ref: UUID
    platform: str
    revoked_at: datetime | None
    last_processed_sequence: int

    @property
    def is_active(self):
        return self.revoked_at is None

    def public(self):
        return DeviceView(device_ref=self.device_ref, platform=self.platform,
                          revoked_at=self.revoked_at)


class VehicleIdentityError(Exception):
    def __init__(self, code, message, status_code=404):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def _scope(conn, current_user: CurrentUser):
    require_user(conn, current_user.user_id)
    if current_user.family_id is None or not conn.execute(
        "SELECT 1 FROM users WHERE id=%s AND family_id=%s",
        (current_user.user_id, current_user.family_id),
    ).fetchone():
        raise VehicleIdentityError("FAMILY_ACCESS_DENIED", "Family access denied", 403)


def _ref(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def list_vehicles(conn, current_user: CurrentUser):
    _scope(conn, current_user)
    return [VehicleRecord(*row) for row in conn.execute(
        "SELECT id,vehicle_ref,display_name,retired_at FROM vehicles "
        "WHERE family_id=%s ORDER BY id", (current_user.family_id,),
    ).fetchall()]


def resolve_vehicle(conn, current_user: CurrentUser, vehicle_ref, *, active_only=False):
    _scope(conn, current_user)
    ref = _ref(vehicle_ref)
    row = None if ref is None else conn.execute(
        "SELECT id,vehicle_ref,display_name,retired_at FROM vehicles "
        "WHERE family_id=%s AND vehicle_ref=%s",
        (current_user.family_id, ref),
    ).fetchone()
    vehicle = VehicleRecord(*row) if row else None
    if vehicle is None or (active_only and not vehicle.is_active):
        raise VehicleIdentityError("VEHICLE_NOT_FOUND_OR_UNAVAILABLE", "Vehicle unavailable")
    return vehicle


def list_devices(conn, current_user: CurrentUser):
    _scope(conn, current_user)
    return [DeviceRecord(*row) for row in conn.execute(
        "SELECT id,device_ref,platform,revoked_at,last_processed_sequence "
        "FROM registered_devices WHERE user_id=%s ORDER BY id",
        (current_user.user_id,),
    ).fetchall()]


def resolve_device(conn, current_user: CurrentUser, device_ref, *, active_only=True):
    _scope(conn, current_user)
    ref = _ref(device_ref)
    row = None if ref is None else conn.execute(
        "SELECT id,device_ref,platform,revoked_at,last_processed_sequence "
        "FROM registered_devices WHERE user_id=%s AND device_ref=%s",
        (current_user.user_id, ref),
    ).fetchone()
    device = DeviceRecord(*row) if row else None
    if device is None or (active_only and not device.is_active):
        raise VehicleIdentityError("DEVICE_NOT_FOUND_OR_UNAVAILABLE", "Device unavailable")
    return device
