from fastapi import FastAPI
from models import CarConnection
from datetime import datetime
from database import conn, insert_car_event, get_latest_event, get_active_driver, init_db
from car_service import connect_user, disconnect_user

app = FastAPI()

init_db()

@app.get("/")
def home():
    return {"message": "Family Car Agent is running"}

@app.post("/car/connect")
def connect_car(connection: CarConnection):
    return connect_user(connection.shortcut_token)

@app.post("/car/disconnect")
def disconnect_car(connection: CarConnection):
    return disconnect_user(connection.shortcut_token)

@app.get("/car/status")
def get_car_status():
    event = get_latest_event()

    if not event:
        return {
            "status": "available",
            "current_driver": None
        }

    driver_name, status, event_time = event

    if status == "connected":
        return {
            "status": "in_use",
            "current_driver": driver_name
        }

    return {
        "status": "available",
        "current_driver": None
    }

