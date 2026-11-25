"""Read-only current projection snapshots; no event admission or checkpoint advancement."""
from pydantic import BaseModel, ConfigDict, Field, UUID4, model_validator
from uuid import UUID
import vehicle_lifecycle as lifecycle
import vehicle_bindings as bindings
from vehicle_admission import _bounded_connection

class TakeReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID4
    device_sequence: int = Field(strict=True, ge=1, le=9223372036854775807)
    vehicle_ref: UUID

class MetadataRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID4
    takes: list[TakeReference] = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def unique(self):
        if len({x.event_id for x in self.takes}) != len(self.takes) or len({x.device_sequence for x in self.takes}) != len(self.takes):
            raise ValueError('Duplicate event identity')
        return self

def snapshot(conn, user, device_ref, request):
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device=bindings._native(conn,user,device_ref)
        if device[3] is not None:
            bindings.unavailable()
        revision,boundary,observed=conn.execute('SELECT projection_revision,vehicle_finalized_through,clock_timestamp() FROM families WHERE id=%s',(user.family_id,)).fetchone()
        last=conn.execute('SELECT last_processed_sequence FROM registered_devices WHERE id=%s',(device[0],)).fetchone()[0]
        items=[]
        for ref in request.takes:
            item={**ref.model_dump(mode='json'), 'status':'unavailable'}
            # Scope every join; foreign or mismatched IDs never reveal another session.
            row=conn.execute("SELECT e.projection_take_event_id,e.occurred_at,s.session_ref,s.ended_at,s.end_reason,s.end_reconciliation_id "
                "FROM vehicle_events e JOIN vehicles v ON v.id=e.vehicle_id AND v.family_id=e.family_id "
                "JOIN registered_device_vehicle_bindings b ON b.vehicle_id=v.id AND b.device_id=e.device_id "
                "LEFT JOIN vehicle_driver_sessions s ON s.start_event_id=e.projection_take_event_id AND s.family_id=e.family_id AND s.user_id=e.user_id AND s.vehicle_id=e.vehicle_id "
                "WHERE e.event_id=%s AND e.device_sequence=%s AND e.device_id=%s AND e.user_id=%s AND e.family_id=%s "
                "AND v.vehicle_ref=%s AND v.retired_at IS NULL AND e.event_type='take' AND e.admission_outcome='accepted' LIMIT 2",
                (ref.event_id,ref.device_sequence,device[0],user.user_id,user.family_id,ref.vehicle_ref)).fetchall()
            if len(row)==1 and row[0][0] is not None and row[0][2] is not None:
                anchor,occurred,session,ended,reason,operation=row[0]
                item.update(status='accepted',anchor_event_id=str(anchor),session_ref=str(session),
                    session_state='closed' if ended else 'open',closed_at=ended.isoformat() if ended else None,
                    closure_kind=reason,reconciliation_operation_id=str(operation) if operation else None,
                    finality='finalized' if boundary and ended and occurred<=boundary and ended<=boundary else 'provisional')
            items.append(item)
        return dict(request_id=str(request.request_id),device_ref=str(device_ref),projection_revision=revision,
            last_processed_sequence=last,observed_at=observed.isoformat(),items=items)
