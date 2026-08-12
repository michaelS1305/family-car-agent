import os
from psycopg_pool import ConnectionPool
import secrets
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=5,
    open=True,
)

def init_db():
    with pool.connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS car_events (
            id SERIAL PRIMARY KEY,
            driver_name TEXT NOT NULL,
            status TEXT NOT NULL,
            event_time TEXT NOT NULL,
            family_id INTEGER
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
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
        ALTER TABLE car_events
        ADD COLUMN IF NOT EXISTS family_id INTEGER
        REFERENCES families(id)
        """)

        conn.execute("""
        ALTER TABLE car_events
        ADD COLUMN IF NOT EXISTS user_id INTEGER
        REFERENCES users(id)
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_sessions (
            telegram_chat_id BIGINT PRIMARY KEY,
            step TEXT NOT NULL,
            data TEXT,
            updated_at TEXT NOT NULL
        )
        """)




def generate_shortcut_token():
    return secrets.token_urlsafe(32)

def insert_car_event(user_id, driver_name, status, family_id):
    with pool.connection() as conn:
        event_time = datetime.now().isoformat()

        conn.execute(
            """
            INSERT INTO car_events (
                user_id,
                driver_name,
                status,
                event_time,
                family_id
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, driver_name, status, event_time, family_id)
        )

        return {
            "message": f"Car {status}",
            "user": driver_name,
            "event_time": event_time
        }

def get_latest_event(family_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT c.driver_name, c.status, c.event_time, c.user_id
            FROM car_events c
            WHERE c.family_id = %s
              AND c.status = 'connected'
              AND NOT EXISTS (
                  SELECT 1
                  FROM car_events d
                  WHERE d.family_id = c.family_id
                    AND d.status = 'disconnected'
                    AND d.id > c.id
                    AND (
                        (c.user_id IS NOT NULL AND d.user_id = c.user_id)
                        OR
                        (c.user_id IS NULL AND d.driver_name = c.driver_name)
                    )
              )
            ORDER BY c.id DESC
            LIMIT 1
            """,
            (family_id,)
        )

        return cursor.fetchone()


def get_active_driver(family_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT c.driver_name, c.user_id
            FROM car_events c
            WHERE c.family_id = %s
              AND c.status = 'connected'
              AND NOT EXISTS (
                  SELECT 1
                  FROM car_events d
                  WHERE d.family_id = c.family_id
                    AND d.status = 'disconnected'
                    AND d.id > c.id
                    AND (
                        (c.user_id IS NOT NULL AND d.user_id = c.user_id)
                        OR
                        (c.user_id IS NULL AND d.driver_name = c.driver_name)
                    )
              )
            ORDER BY c.id DESC
            LIMIT 1
            """,
            (family_id,)
        )

        return cursor.fetchone()

def insert_user(
    name,
    shortcut_token,
    telegram_chat_id,
    family_id
):
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO users (
                name,
                shortcut_token,
                telegram_chat_id,
                family_id
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                name,
                shortcut_token,
                telegram_chat_id,
                family_id
            )
        )


def get_user_by_token(shortcut_token):
    with pool.connection() as conn:
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
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, telegram_chat_id, family_id
            FROM users
            WHERE telegram_chat_id = %s
            """,
            (chat_id,)
        )

        return cursor.fetchone()

def get_users_by_family_id(family_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, telegram_chat_id
            FROM users
            WHERE family_id = %s
            """,
            (family_id,)
        )

        return cursor.fetchall()

def get_all_users():
    with pool.connection() as conn:
        cursor = conn.execute("""
            SELECT id, name
            FROM users
        """)

        return cursor.fetchall()

def get_last_driver(family_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT driver_name, status, event_time
            FROM car_events
            WHERE family_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (family_id,)
        )

        return cursor.fetchone()

def get_recent_events(family_id, limit=10):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT driver_name, status, event_time
            FROM car_events
            WHERE family_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (family_id, limit)
        )

        return cursor.fetchall()

def _get_conflicting_reservation(
    conn,
    family_id,
    start_time,
    end_time,
    exclude_reservation_id=None
):
    params = [family_id, end_time, start_time]
    exclude_sql = ""

    if exclude_reservation_id is not None:
        exclude_sql = "AND r.id != %s"
        params.append(exclude_reservation_id)

    cursor = conn.execute(
        f"""
        SELECT r.id, r.user_id, r.start_time, r.end_time
        FROM reservations r
        JOIN users u ON u.id = r.user_id
        WHERE u.family_id = %s
          AND r.status = 'active'
          AND r.start_time < %s
          AND r.end_time > %s
          {exclude_sql}
        ORDER BY r.start_time
        LIMIT 1
        """,
        tuple(params)
    )

    return cursor.fetchone()


def get_conflicting_reservation(
    family_id,
    start_time,
    end_time,
    exclude_reservation_id=None
):
    with pool.connection() as conn:
        return _get_conflicting_reservation(
            conn,
            family_id,
            start_time,
            end_time,
            exclude_reservation_id
        )

def create_reservation(user_id, start_time, end_time):
    with pool.connection() as conn:
        user = conn.execute(
            """
            SELECT family_id
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        ).fetchone()

        if not user or user[0] is None:
            return {
                "success": False,
                "message": "User family not found"
            }

        family_id = user[0]
        conflict = _get_conflicting_reservation(
            conn,
            family_id,
            start_time,
            end_time
        )

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

        return {
            "success": True,
            "message": "Reservation created"
        }

def get_family_reservations(family_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT r.id, r.user_id, u.name, r.start_time, r.end_time, r.status
            FROM reservations r
            JOIN users u ON u.id = r.user_id
            WHERE u.family_id = %s
            ORDER BY r.start_time
            """,
            (family_id,)
        )

        return cursor.fetchall()

def get_user_reservations(user_id):
    with pool.connection() as conn:
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

def _get_reservation_by_id(conn, reservation_id):
    cursor = conn.execute(
        """
        SELECT id, user_id, start_time, end_time, status
        FROM reservations
        WHERE id = %s
        """,
        (reservation_id,)
    )

    return cursor.fetchone()


def get_reservation_by_id(reservation_id):
    with pool.connection() as conn:
        return _get_reservation_by_id(conn, reservation_id)

def cancel_reservation(reservation_id, user_id):
    with pool.connection() as conn:
        reservation = _get_reservation_by_id(conn, reservation_id)

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

        return {
            "success": True,
            "message": "Reservation cancelled"
        }


def update_reservation(reservation_id, user_id, start_time, end_time):
    with pool.connection() as conn:
        reservation = _get_reservation_by_id(conn, reservation_id)

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

        family = conn.execute(
            """
            SELECT family_id
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        ).fetchone()

        if not family or family[0] is None:
            return {
                "success": False,
                "message": "User family not found"
            }

        conflict = _get_conflicting_reservation(
            conn,
            family[0],
            start_time,
            end_time,
            exclude_reservation_id=reservation_id
        )

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

        return {
            "success": True,
            "message": "Reservation updated"
        }

def save_conversation_message(user_id, role, content):
    with pool.connection() as conn:
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


def get_recent_conversation(user_id, limit=10):
    with pool.connection() as conn:
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
    with pool.connection() as conn:
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

        return family_id

def get_family_by_code(family_code):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, home_address, home_latitude, home_longitude
            FROM families
            WHERE family_code = %s
            """,
            (family_code,)
        )

        return cursor.fetchone()

def get_family_by_location(latitude, longitude, radius_meters=50):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, home_address, home_latitude, home_longitude
            FROM families
            WHERE home_latitude IS NOT NULL
              AND home_longitude IS NOT NULL
              AND (
                  6371000 * 2 * ASIN(
                      SQRT(
                          POWER(SIN(RADIANS(home_latitude - %s) / 2), 2)
                          + COS(RADIANS(%s))
                          * COS(RADIANS(home_latitude))
                          * POWER(SIN(RADIANS(home_longitude - %s) / 2), 2)
                      )
                  )
              ) <= %s
            ORDER BY (
                POWER(home_latitude - %s, 2)
                + POWER(home_longitude - %s, 2)
            )
            LIMIT 1
            """,
            (
                latitude,
                latitude,
                longitude,
                radius_meters,
                latitude,
                longitude
            )
        )

        return cursor.fetchone()

def get_family_by_name_and_location(name, latitude, longitude, radius_meters=50):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, home_address, home_latitude, home_longitude
            FROM families
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
              AND home_latitude IS NOT NULL
              AND home_longitude IS NOT NULL
              AND (
                  6371000 * 2 * ASIN(
                      SQRT(
                          POWER(SIN(RADIANS(home_latitude - %s) / 2), 2)
                          + COS(RADIANS(%s))
                          * COS(RADIANS(home_latitude))
                          * POWER(SIN(RADIANS(home_longitude - %s) / 2), 2)
                      )
                  )
              ) <= %s
            ORDER BY (
                POWER(home_latitude - %s, 2)
                + POWER(home_longitude - %s, 2)
            )
            LIMIT 1
            """,
            (
                name,
                latitude,
                latitude,
                longitude,
                radius_meters,
                latitude,
                longitude
            )
        )

        return cursor.fetchone()

def get_family_by_id(family_id):
    with pool.connection() as conn:
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
    with pool.connection() as conn:
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
    with pool.connection() as conn:
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


def delete_onboarding_session(chat_id):
    with pool.connection() as conn:
        conn.execute(
            """
            DELETE FROM onboarding_sessions
            WHERE telegram_chat_id = %s
            """,
            (chat_id,)
        )

        conn.commit()