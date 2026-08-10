from pydantic import BaseModel


class CarConnection(BaseModel):
    shortcut_token: str
    latitude: float | None = None
    longitude: float | None = None