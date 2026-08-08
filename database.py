import sqlite3
from datetime import datetime

conn = sqlite3.connect("family_car.db", check_same_thread=False)

def init_db():
    conn.execute("""
    CREATE TABLE IF NOT EXISTS car_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_name TEXT NOT NULL,
        status TEXT NOT NULL,
        event_time TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone_number TEXT UNIQUE,
        shortcut_token TEXT UNIQUE
    )
    """)

    conn.commit()

def insert_car_event(driver_name, status):
    event_time = datetime.now().isoformat()

    conn.execute(
        """
        INSERT INTO car_events (driver_name, status, event_time)
        VALUES (?, ?, ?)
        """,
        (driver_name, status, event_time)
    )

    conn.commit()

    return {
        "message": f"Car {status}",
        "user": driver_name,
        "event_time": event_time
    }

def get_latest_event():
    cursor = conn.execute("""
        SELECT driver_name, status, event_time
        FROM car_events c
        WHERE status = 'connected'
        AND NOT EXISTS (
            SELECT 1
            FROM car_events d
            WHERE d.driver_name = c.driver_name
                AND d.status = 'disconnected'
                AND d.id > c.id
        )
        ORDER BY id DESC
        LIMIT 1;
        
    """)

    return cursor.fetchone()

def get_active_driver():
    cursor = conn.execute("""
        SELECT driver_name
        FROM car_events c
        WHERE status = 'connected'
          AND NOT EXISTS (
              SELECT 1
              FROM car_events d
              WHERE d.driver_name = c.driver_name
                AND d.status = 'disconnected'
                AND d.id > c.id
          )
        ORDER BY id DESC
        LIMIT 1
    """)

    return cursor.fetchone()

def insert_user(name, phone_number, shortcut_token):
    conn.execute(
        """
        INSERT INTO users (name, phone_number, shortcut_token)
        VALUES (?, ?, ?)
        """,
        (name, phone_number, shortcut_token)
    )

    conn.commit()

def get_user_by_token(shortcut_token):
    cursor = conn.execute(
        """
        SELECT id, name
        FROM users
        WHERE shortcut_token = ?
        """,
        (shortcut_token,)
    )

    return cursor.fetchone()