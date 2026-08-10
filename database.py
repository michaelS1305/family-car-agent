import sqlite3
import os
import psycopg
import secrets
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg.connect(DATABASE_URL)

def init_db():
    conn.execute("""
    CREATE TABLE IF NOT EXISTS car_events (
        id SERIAL PRIMARY KEY,
        driver_name TEXT NOT NULL,
        status TEXT NOT NULL,
        event_time TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        phone_number TEXT UNIQUE,
        shortcut_token TEXT UNIQUE,
        telegram_chat_id BIGINT UNIQUE
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS conversation_messages (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS families (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        family_code TEXT UNIQUE NOT NULL,
        home_address TEXT NOT NULL,
        home_latitude DOUBLE PRECISION,
        home_longitude DOUBLE PRECISION,
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS family_id INTEGER
    REFERENCES families(id)
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS onboarding_sessions (
        telegram_chat_id BIGINT PRIMARY KEY,
        step TEXT NOT NULL,
        data TEXT,
        updated_at TEXT NOT NULL
    )
    """)

    conn.commit()

def generate_shortcut_token():
    return secrets.token_urlsafe(32)

def insert_car_event(driver_name, status):
    event_time = datetime.now().isoformat()

    conn.execute(
        """
        INSERT INTO car_events (driver_name, status, event_time)
        VALUES (%s, %s, %s)
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

def insert_user(
    name,
    phone_number,
    shortcut_token,
    telegram_chat_id,
    family_id
):
    conn.execute(
        """
        INSERT INTO users (
            name,
            phone_number,
            shortcut_token,
            telegram_chat_id,
            family_id
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            name,
            phone_number,
            shortcut_token,
            telegram_chat_id,
            family_id
        )
    )

    conn.commit()

def get_user_by_token(shortcut_token):
    cursor = conn.execute(
        """
        SELECT id, name, telegram_chat_id, family_id
        FROM users
        WHERE shortcut_token = %s
        """,
        (shortcut_token,)
    )

    return cursor.fetchone()

def get_user_by_telegram_chat_id(chat_id):
    cursor = conn.execute(
        """
        SELECT id, name, telegram_chat_id
        FROM users
        WHERE telegram_chat_id = %s
        """,
        (chat_id,)
    )

    return cursor.fetchone()

def get_all_users():
    cursor = conn.execute("""
        SELECT id, name
        FROM users
    """)

    return cursor.fetchall()

def get_last_driver():
    cursor = conn.execute("""
        SELECT driver_name, status, event_time
        FROM car_events
        ORDER BY id DESC
        LIMIT 1
    """)

    return cursor.fetchone()

def get_recent_events(limit=10):
    cursor = conn.execute(
        """
        SELECT driver_name, status, event_time
        FROM car_events
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,)
    )

    return cursor.fetchall()

def get_conflicting_reservation(start_time, end_time):
    cursor = conn.execute(
        """
        SELECT id, user_id, start_time, end_time
        FROM reservations
        WHERE status = 'active'
          AND start_time < %s
          AND end_time > %s
        ORDER BY start_time
        LIMIT 1
        """,
        (end_time, start_time)
    )

    return cursor.fetchone()

def create_reservation(user_id, start_time, end_time):
    conflict = get_conflicting_reservation(start_time, end_time)

    if conflict:
        return {
            "success": False,
            "message": "Car is already reserved for this time"
        }

    created_at = datetime.now().isoformat()

    conn.execute(
        """
        INSERT INTO reservations (
            user_id,
            start_time,
            end_time,
            status,
            created_at
        )
        VALUES (%s, %s, %s, 'active', %s)
        """,
        (user_id, start_time, end_time, created_at)
    )

    conn.commit()

    return {
        "success": True,
        "message": "Reservation created"
    }

def get_user_reservations(user_id):
    cursor = conn.execute(
        """
        SELECT id, start_time, end_time, status
        FROM reservations
        WHERE user_id = %s
        ORDER BY start_time
        """,
        (user_id,)
    )

    return cursor.fetchall()

def get_reservation_by_id(reservation_id):
    cursor = conn.execute(
        """
        SELECT id, user_id, start_time, end_time, status
        FROM reservations
        WHERE id = %s
        """,
        (reservation_id,)
    )

    return cursor.fetchone()

def cancel_reservation(reservation_id, user_id):
    reservation = get_reservation_by_id(reservation_id)

    if not reservation:
        return {
            "success": False,
            "message": "Reservation not found"
        }

    if reservation[1] != user_id:
        return {
            "success": False,
            "message": "You cannot cancel another user's reservation"
        }

    if reservation[4] != "active":
        return {
            "success": False,
            "message": "Reservation is not active"
        }

    conn.execute(
        """
        UPDATE reservations
        SET status = 'cancelled'
        WHERE id = %s
        """,
        (reservation_id,)
    )

    conn.commit()

    return {
        "success": True,
        "message": "Reservation cancelled"
    }

def update_reservation(reservation_id, user_id, start_time, end_time):
    reservation = get_reservation_by_id(reservation_id)

    if not reservation:
        return {
            "success": False,
            "message": "Reservation not found"
        }

    if reservation[1] != user_id:
        return {
            "success": False,
            "message": "You cannot modify another user's reservation"
        }

    if reservation[4] != "active":
        return {
            "success": False,
            "message": "Reservation is not active"
        }

    conflict = conn.execute(
        """
        SELECT id
        FROM reservations
        WHERE status = 'active'
          AND id != %s
          AND start_time < %s
          AND end_time > %s
        LIMIT 1
        """,
        (reservation_id, end_time, start_time)
    ).fetchone()

    if conflict:
        return {
            "success": False,
            "message": "Car is already reserved for this time"
        }

    conn.execute(
        """
        UPDATE reservations
        SET start_time = %s,
            end_time = %s
        WHERE id = %s
        """,
        (start_time, end_time, reservation_id)
    )

    conn.commit()

    return {
        "success": True,
        "message": "Reservation updated"
    }

def save_conversation_message(user_id, role, content):
    conn.execute(
        """
        INSERT INTO conversation_messages (
            user_id,
            role,
            content,
            created_at
        )
        VALUES (%s, %s, %s, %s)
        """,
        (
            user_id,
            role,
            content,
            datetime.now().isoformat()
        )
    )

    conn.commit()

def get_recent_conversation(user_id, limit=10):
    cursor = conn.execute(
        """
        SELECT role, content
        FROM conversation_messages
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (user_id, limit)
    )

    messages = cursor.fetchall()

    return list(reversed(messages))

def create_family(name, family_code, home_address, home_latitude=None, home_longitude=None):
    created_at = datetime.now().isoformat()

    cursor = conn.execute(
        """
        INSERT INTO families (
            name,
            family_code,
            home_address,
            home_latitude,
            home_longitude,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            name,
            family_code,
            home_address,
            home_latitude,
            home_longitude,
            created_at
        )
    )

    family_id = cursor.fetchone()[0]
    conn.commit()

    return family_id

def get_family_by_code(family_code):
    cursor = conn.execute(
        """
        SELECT id, name, home_address, home_latitude, home_longitude
        FROM families
        WHERE family_code = %s
        """,
        (family_code,)
    )

    return cursor.fetchone()

def get_family_by_id(family_id):
    cursor = conn.execute(
        """
        SELECT id, name, home_address, home_latitude, home_longitude
        FROM families
        WHERE id = %s
        """,
        (family_id,)
    )

    return cursor.fetchone()

def get_onboarding_session(chat_id):
    cursor = conn.execute(
        """
        SELECT step, data
        FROM onboarding_sessions
        WHERE telegram_chat_id = %s
        """,
        (chat_id,)
    )

    return cursor.fetchone()

def save_onboarding_session(chat_id, step, data=None):
    conn.execute(
        """
        INSERT INTO onboarding_sessions (
            telegram_chat_id,
            step,
            data,
            updated_at
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (telegram_chat_id)
        DO UPDATE SET
            step = EXCLUDED.step,
            data = EXCLUDED.data,
            updated_at = EXCLUDED.updated_at
        """,
        (
            chat_id,
            step,
            data,
            datetime.now().isoformat()
        )
    )

    conn.commit()

def delete_onboarding_session(chat_id):
    conn.execute(
        """
        DELETE FROM onboarding_sessions
        WHERE telegram_chat_id = %s
        """,
        (chat_id,)
    )

    conn.commit()