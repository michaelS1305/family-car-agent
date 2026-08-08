from pydantic import BaseModel

class CarConnection(BaseModel):
    shortcut_token: str