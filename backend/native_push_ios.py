"""Dev APNs content, built only from an authorized server read."""
from datetime import datetime
from zoneinfo import ZoneInfo

TOPIC = 'com.familycaragent.app.dev'


def alert(kind, actor, vehicle, scheduled=None, end=None, description=None):
    if not isinstance(vehicle,str) or not vehicle.strip():
        return None
    vehicle = vehicle.strip()[:120]
    if kind in ('vehicle_taken','vehicle_returned'):
        if not isinstance(actor,str) or not actor.strip():
            return None
        action = 'לקח/ה' if kind == 'vehicle_taken' else 'החזיר/ה'
        body = f'{actor.strip()[:80]} {action} את הרכב {vehicle}'
    elif kind in ('reservation_reminder','maintenance_reminder') and isinstance(scheduled,datetime) and scheduled.tzinfo:
        when = scheduled.astimezone(ZoneInfo('Asia/Jerusalem'))
        body = (f'תזכורת להזמנת הרכב {vehicle} ב־{when:%d/%m/%Y %H:%M}' if kind == 'reservation_reminder'
                else f'תזכורת לטיפול ברכב {vehicle} בתאריך {when:%d/%m/%Y}')
        if kind == 'reservation_reminder' and isinstance(end,datetime) and end.tzinfo and end > scheduled:
            body += f' עד {end.astimezone(ZoneInfo("Asia/Jerusalem")):%d/%m/%Y %H:%M}'
        if kind == 'maintenance_reminder' and isinstance(description,str) and description.strip():
            body += ': ' + description.strip()[:160]
    else:
        return None
    return {'title':'Family Car Agent', 'body':body}
