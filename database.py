import os
import logging
from psycopg_pool import ConnectionPool
from psycopg.errors import ForeignKeyViolation, UniqueViolation
import secrets
from datetime import datetime
from dotenv import load_dotenv
from onboarding_rules import (
    NAME_SQL_TRANSLATE_SOURCE,
    NAME_SQL_TRANSLATE_TARGET,
)

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

logger = logging.getLogger(__name__)


class FamilyCodeTakenError(Exception):
    pass


class AuthUserAlreadyMappedError(Exception):
    pass


class AuthUserIdentityNotFoundError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class FamilyAlreadyExistsAtLocationError(Exception):
    pass


class JoinSessionLockedError(Exception):
    def __init__(self, locked_until):
        super().__init__("PWA Join session is locked")
        self.locked_until = locked_until


class InvalidJoinStepError(Exception):
    pass


PWA_FAMILY_CREATION_LOCK_ID = 1178686273

JOIN_SESSION_COLUMNS = """
    auth_user_id,
    step,
    family_name,
    family_id,
    normalized_address,
    resolved_address,
    family_name_attempts,
    address_attempts,
    family_code_attempts,
    locked_until,
    created_at,
    updated_at
"""

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
            telegram_chat_id BIGINT UNIQUE,
            auth_user_id UUID,
            carplay_setup_status TEXT NOT NULL DEFAULT 'pending',
            CONSTRAINT users_auth_user_id_unique
                UNIQUE (auth_user_id),
            CONSTRAINT users_auth_user_id_fkey
                FOREIGN KEY (auth_user_id)
                REFERENCES auth.users(id)
                ON DELETE SET NULL,
            CONSTRAINT users_carplay_setup_status_check
                CHECK (carplay_setup_status IN ('pending', 'completed', 'skipped'))
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

        conn.execute("""
        CREATE TABLE IF NOT EXISTS pwa_join_sessions (
            auth_user_id UUID NOT NULL,
            step TEXT NOT NULL DEFAULT 'family_name',
            family_name TEXT,
            family_id INTEGER,
            normalized_address TEXT,
            resolved_address TEXT,
            family_name_attempts SMALLINT NOT NULL DEFAULT 0,
            address_attempts SMALLINT NOT NULL DEFAULT 0,
            family_code_attempts SMALLINT NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pwa_join_sessions_pkey PRIMARY KEY (auth_user_id),
            CONSTRAINT pwa_join_sessions_auth_user_id_fkey
                FOREIGN KEY (auth_user_id)
                REFERENCES auth.users(id)
                ON DELETE CASCADE,
            CONSTRAINT pwa_join_sessions_family_id_fkey
                FOREIGN KEY (family_id)
                REFERENCES families(id)
                ON DELETE SET NULL,
            CONSTRAINT pwa_join_sessions_step_check
                CHECK (step IN (
                    'family_name',
                    'address',
                    'address_confirmed',
                    'family_code',
                    'user_name',
                    'locked'
                )),
            CONSTRAINT pwa_join_sessions_family_name_attempts_check
                CHECK (family_name_attempts BETWEEN 0 AND 3),
            CONSTRAINT pwa_join_sessions_address_attempts_check
                CHECK (address_attempts BETWEEN 0 AND 3),
            CONSTRAINT pwa_join_sessions_family_code_attempts_check
                CHECK (family_code_attempts BETWEEN 0 AND 3)
        )
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS pwa_join_sessions_locked_until_idx
        ON pwa_join_sessions (locked_until)
        WHERE locked_until IS NOT NULL
        """)




def generate_shortcut_token():
    return secrets.token_urlsafe(32)


def get_or_create_shortcut_token(user_id):
    for _ in range(3):
        try:
            with pool.connection() as conn:
                with conn.transaction():
                    user = conn.execute(
                        """
                        SELECT shortcut_token
                        FROM users
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (user_id,),
                    ).fetchone()

                    if not user:
                        raise UserNotFoundError()
                    if user[0]:
                        return user[0]

                    generated_token = generate_shortcut_token()
                    updated = conn.execute(
                        """
                        UPDATE users
                        SET shortcut_token = %s
                        WHERE id = %s
                        RETURNING shortcut_token
                        """,
                        (generated_token, user_id),
                    ).fetchone()
                    return updated[0]
        except UniqueViolation:
            # A generated collision is extraordinarily unlikely, but retrying keeps
            # the UNIQUE constraint as the final guarantee without exposing details.
            continue

    raise RuntimeError("Could not generate a unique shortcut token")


def set_carplay_setup_status(user_id, setup_status):
    with pool.connection() as conn:
        updated = conn.execute(
            """
            UPDATE users
            SET carplay_setup_status = %s
            WHERE id = %s
            RETURNING carplay_setup_status
            """,
            (setup_status, user_id),
        ).fetchone()
        if not updated:
            raise UserNotFoundError()
        return updated[0]

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


def get_user_by_auth_user_id(auth_user_id):
    with pool.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, name, family_id, carplay_setup_status
            FROM users
            WHERE auth_user_id = %s
            """,
            (auth_user_id,)
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


def create_family_with_first_user(
    name,
    family_code,
    home_address,
    user_name,
    shortcut_token,
    telegram_chat_id,
    home_latitude=None,
    home_longitude=None,
    auth_user_id=None,
    prevent_duplicate_location=False,
):
    try:
        with pool.connection() as conn:
            with conn.transaction():
                if auth_user_id is not None:
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        (PWA_FAMILY_CREATION_LOCK_ID,),
                    )

                    mapped_user = conn.execute(
                        "SELECT id FROM users WHERE auth_user_id = %s",
                        (auth_user_id,),
                    ).fetchone()
                    if mapped_user:
                        raise AuthUserAlreadyMappedError()

                    existing_code = conn.execute(
                        "SELECT id FROM families WHERE family_code = %s",
                        (family_code,),
                    ).fetchone()
                    if existing_code:
                        raise FamilyCodeTakenError()

                    if (
                        prevent_duplicate_location
                        and home_latitude is not None
                        and home_longitude is not None
                        and _get_family_by_location(
                            conn,
                            home_latitude,
                            home_longitude,
                        )
                    ):
                        raise FamilyAlreadyExistsAtLocationError()

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
                        created_at,
                    )
                )

                family_id = cursor.fetchone()[0]

                conn.execute(
                    """
                    INSERT INTO users (
                        name,
                        shortcut_token,
                        telegram_chat_id,
                        family_id,
                        auth_user_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        user_name,
                        shortcut_token,
                        telegram_chat_id,
                        family_id,
                        auth_user_id,
                    )
                )

            return family_id
    except UniqueViolation as exc:
        constraint_name = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if constraint_name == "users_auth_user_id_unique":
            raise AuthUserAlreadyMappedError() from exc
        if constraint_name == "families_family_code_key":
            raise FamilyCodeTakenError() from exc
        raise
    except ForeignKeyViolation as exc:
        constraint_name = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if constraint_name == "users_auth_user_id_fkey":
            logger.warning(
                "database_operation_failed exception_type=%s operation=%s stage=%s error_code=%s",
                type(exc).__name__,
                "create_family_with_first_user",
                "insert_first_user",
                "AUTH_SESSION_INVALID",
            )
            raise AuthUserIdentityNotFoundError() from exc
        raise

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

def _get_family_by_location(conn, latitude, longitude, radius_meters=50):
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


def get_family_by_location(latitude, longitude, radius_meters=50):
    with pool.connection() as conn:
        return _get_family_by_location(
            conn,
            latitude,
            longitude,
            radius_meters,
        )


CANONICAL_FAMILY_NAME_PREDICATE = """
    LOWER(
        BTRIM(
            REGEXP_REPLACE(
                TRANSLATE(NORMALIZE(name, NFC), %s, %s),
                '[[:space:]]+',
                ' ',
                'g'
            )
        )
    ) = LOWER(%s)
"""


def _family_name_exists(conn, name):
    exact_match = conn.execute(
        """
        SELECT 1
        FROM families
        WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if exact_match:
        return True

    canonical_match = conn.execute(
        f"""
        SELECT 1
        FROM families
        WHERE {CANONICAL_FAMILY_NAME_PREDICATE}
        LIMIT 1
        """,
        (NAME_SQL_TRANSLATE_SOURCE, NAME_SQL_TRANSLATE_TARGET, name),
    ).fetchone()
    return canonical_match is not None


def _get_family_by_name_and_location(
    conn,
    name,
    latitude,
    longitude,
    radius_meters=50,
):
    name_predicates = (
        ("LOWER(TRIM(name)) = LOWER(TRIM(%s))", (name,)),
        (
            CANONICAL_FAMILY_NAME_PREDICATE,
            (NAME_SQL_TRANSLATE_SOURCE, NAME_SQL_TRANSLATE_TARGET, name),
        ),
    )

    for name_predicate, name_parameters in name_predicates:
        cursor = conn.execute(
            """
            SELECT id, name, home_address, home_latitude, home_longitude
            FROM families
            WHERE {name_predicate}
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
            """.format(name_predicate=name_predicate),
            (
                *name_parameters,
                latitude,
                latitude,
                longitude,
                radius_meters,
                latitude,
                longitude
            )
        )

        family = cursor.fetchone()
        if family:
            return family

    return None


def get_family_by_name_and_location(name, latitude, longitude, radius_meters=50):
    with pool.connection() as conn:
        return _get_family_by_name_and_location(
            conn,
            name,
            latitude,
            longitude,
            radius_meters,
        )


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


def _join_session_from_row(row, was_reset=False):
    return {
        "auth_user_id": str(row[0]),
        "step": row[1],
        "family_name": row[2],
        "family_id": row[3],
        "normalized_address": row[4],
        "resolved_address": row[5],
        "family_name_attempts": row[6],
        "address_attempts": row[7],
        "family_code_attempts": row[8],
        "locked_until": row[9],
        "created_at": row[10],
        "updated_at": row[11],
        "was_reset": was_reset,
    }


def _lock_pwa_join_session(conn, auth_user_id):
    mapped_user = conn.execute(
        "SELECT id FROM users WHERE auth_user_id = %s",
        (auth_user_id,),
    ).fetchone()
    if mapped_user:
        raise AuthUserAlreadyMappedError()

    conn.execute(
        """
        INSERT INTO pwa_join_sessions (auth_user_id)
        VALUES (%s)
        ON CONFLICT (auth_user_id) DO NOTHING
        """,
        (auth_user_id,),
    )

    reset_row = conn.execute(
        f"""
        UPDATE pwa_join_sessions
        SET step = 'family_name',
            family_name = NULL,
            family_id = NULL,
            normalized_address = NULL,
            resolved_address = NULL,
            family_name_attempts = 0,
            address_attempts = 0,
            family_code_attempts = 0,
            locked_until = NULL,
            updated_at = NOW()
        WHERE auth_user_id = %s
          AND step = 'locked'
          AND locked_until <= NOW()
        RETURNING {JOIN_SESSION_COLUMNS}
        """,
        (auth_user_id,),
    ).fetchone()
    if reset_row:
        return _join_session_from_row(reset_row, was_reset=True)

    row = conn.execute(
        f"""
        SELECT {JOIN_SESSION_COLUMNS}
        FROM pwa_join_sessions
        WHERE auth_user_id = %s
        FOR UPDATE
        """,
        (auth_user_id,),
    ).fetchone()
    if row is None:
        mapped_user = conn.execute(
            "SELECT id FROM users WHERE auth_user_id = %s",
            (auth_user_id,),
        ).fetchone()
        if mapped_user:
            raise AuthUserAlreadyMappedError()
        raise InvalidJoinStepError()

    session = _join_session_from_row(row)
    if session["step"] == "locked":
        raise JoinSessionLockedError(session["locked_until"])
    return session


def start_pwa_join_session(auth_user_id):
    with pool.connection() as conn:
        with conn.transaction():
            return _lock_pwa_join_session(conn, auth_user_id)


def _require_join_step(session, allowed_steps):
    if session["step"] not in allowed_steps:
        raise InvalidJoinStepError()


def _increment_join_failure_locked(conn, session, field):
    columns = {
        "family_name": "family_name_attempts",
        "address": "address_attempts",
        "family_code": "family_code_attempts",
    }
    attempts_column = columns[field]
    next_attempts = session[attempts_column] + 1

    if next_attempts >= 3:
        row = conn.execute(
            f"""
            UPDATE pwa_join_sessions
            SET step = 'locked',
                family_name = NULL,
                family_id = NULL,
                normalized_address = NULL,
                resolved_address = NULL,
                {attempts_column} = 3,
                locked_until = NOW() + INTERVAL '15 minutes',
                updated_at = NOW()
            WHERE auth_user_id = %s
            RETURNING {JOIN_SESSION_COLUMNS}
            """,
            (session["auth_user_id"],),
        ).fetchone()
        locked_session = _join_session_from_row(row)
        return {
            "success": False,
            "attempts_remaining": 0,
            "locked_until": locked_session["locked_until"],
            "session": locked_session,
        }

    row = conn.execute(
        f"""
        UPDATE pwa_join_sessions
        SET {attempts_column} = %s,
            updated_at = NOW()
        WHERE auth_user_id = %s
        RETURNING {JOIN_SESSION_COLUMNS}
        """,
        (next_attempts, session["auth_user_id"]),
    ).fetchone()
    return {
        "success": False,
        "attempts_remaining": 3 - next_attempts,
        "locked_until": None,
        "session": _join_session_from_row(row),
    }


def submit_pwa_join_family_name(auth_user_id, family_name):
    with pool.connection() as conn:
        with conn.transaction():
            session = _lock_pwa_join_session(conn, auth_user_id)
            _require_join_step(
                session,
                {"family_name", "address", "address_confirmed", "family_code"},
            )

            family_exists = _family_name_exists(conn, family_name)
            if not family_exists:
                return _increment_join_failure_locked(
                    conn,
                    session,
                    "family_name",
                )

            row = conn.execute(
                f"""
                UPDATE pwa_join_sessions
                SET step = 'address',
                    family_name = %s,
                    family_id = NULL,
                    normalized_address = NULL,
                    resolved_address = NULL,
                    updated_at = NOW()
                WHERE auth_user_id = %s
                RETURNING {JOIN_SESSION_COLUMNS}
                """,
                (family_name, auth_user_id),
            ).fetchone()
            return {"success": True, "session": _join_session_from_row(row)}


def record_pwa_join_failure(auth_user_id, field, allowed_steps):
    with pool.connection() as conn:
        with conn.transaction():
            session = _lock_pwa_join_session(conn, auth_user_id)
            _require_join_step(session, set(allowed_steps))
            return _increment_join_failure_locked(conn, session, field)


def submit_pwa_join_address(
    auth_user_id,
    normalized_address,
    resolved_address,
    latitude,
    longitude,
):
    with pool.connection() as conn:
        with conn.transaction():
            session = _lock_pwa_join_session(conn, auth_user_id)
            _require_join_step(
                session,
                {"address", "address_confirmed", "family_code"},
            )

            family = _get_family_by_name_and_location(
                conn,
                session["family_name"],
                latitude,
                longitude,
            )
            if not family:
                return _increment_join_failure_locked(conn, session, "address")

            row = conn.execute(
                f"""
                UPDATE pwa_join_sessions
                SET step = 'address_confirmed',
                    family_name = %s,
                    family_id = %s,
                    normalized_address = %s,
                    resolved_address = %s,
                    updated_at = NOW()
                WHERE auth_user_id = %s
                RETURNING {JOIN_SESSION_COLUMNS}
                """,
                (
                    family[1],
                    family[0],
                    normalized_address,
                    resolved_address,
                    auth_user_id,
                ),
            ).fetchone()
            return {"success": True, "session": _join_session_from_row(row)}


def confirm_pwa_join_address(auth_user_id, confirmed):
    with pool.connection() as conn:
        with conn.transaction():
            session = _lock_pwa_join_session(conn, auth_user_id)
            _require_join_step(
                session,
                {"address", "address_confirmed", "family_code"},
            )

            if confirmed:
                if session["step"] == "family_code":
                    return session
                _require_join_step(session, {"address_confirmed"})
                next_step = "family_code"
                family_id = session["family_id"]
            else:
                next_step = "address"
                family_id = None

            row = conn.execute(
                f"""
                UPDATE pwa_join_sessions
                SET step = %s,
                    family_id = %s,
                    normalized_address = CASE WHEN %s THEN normalized_address ELSE NULL END,
                    resolved_address = CASE WHEN %s THEN resolved_address ELSE NULL END,
                    updated_at = NOW()
                WHERE auth_user_id = %s
                RETURNING {JOIN_SESSION_COLUMNS}
                """,
                (next_step, family_id, confirmed, confirmed, auth_user_id),
            ).fetchone()
            return _join_session_from_row(row)


def verify_pwa_join_family_code(auth_user_id, family_code):
    with pool.connection() as conn:
        with conn.transaction():
            session = _lock_pwa_join_session(conn, auth_user_id)
            _require_join_step(session, {"family_code", "user_name"})

            if session["step"] == "user_name":
                return {"success": True, "session": session}

            family_matches = conn.execute(
                """
                SELECT 1
                FROM families
                WHERE id = %s
                  AND family_code = %s
                """,
                (session["family_id"], family_code),
            ).fetchone()
            if not family_matches:
                return _increment_join_failure_locked(
                    conn,
                    session,
                    "family_code",
                )

            row = conn.execute(
                f"""
                UPDATE pwa_join_sessions
                SET step = 'user_name',
                    updated_at = NOW()
                WHERE auth_user_id = %s
                RETURNING {JOIN_SESSION_COLUMNS}
                """,
                (auth_user_id,),
            ).fetchone()
            return {"success": True, "session": _join_session_from_row(row)}


def complete_pwa_join(auth_user_id, user_name):
    try:
        with pool.connection() as conn:
            with conn.transaction():
                session = _lock_pwa_join_session(conn, auth_user_id)

                mapped_user = conn.execute(
                    "SELECT id FROM users WHERE auth_user_id = %s",
                    (auth_user_id,),
                ).fetchone()
                if mapped_user:
                    raise AuthUserAlreadyMappedError()

                _require_join_step(session, {"user_name"})

                family_exists = conn.execute(
                    "SELECT id FROM families WHERE id = %s",
                    (session["family_id"],),
                ).fetchone()
                if not family_exists:
                    raise InvalidJoinStepError()

                user_row = conn.execute(
                    """
                    INSERT INTO users (
                        name,
                        shortcut_token,
                        telegram_chat_id,
                        family_id,
                        auth_user_id
                    )
                    VALUES (%s, NULL, NULL, %s, %s)
                    RETURNING id
                    """,
                    (user_name, session["family_id"], auth_user_id),
                ).fetchone()

                conn.execute(
                    "DELETE FROM pwa_join_sessions WHERE auth_user_id = %s",
                    (auth_user_id,),
                )
                return {
                    "created": True,
                    "user_id": user_row[0],
                    "family_id": session["family_id"],
                }
    except UniqueViolation as exc:
        constraint_name = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if constraint_name == "users_auth_user_id_unique":
            raise AuthUserAlreadyMappedError() from exc
        raise

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
