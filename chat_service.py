import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from ai_service import generate_agent_response
from database import (
    _cancel_reservation_on_connection,
    _create_reservation_on_connection,
    _update_reservation_on_connection,
    pool,
)
from identity import CurrentUser


logger = logging.getLogger(__name__)

CHAT_LEASE_SECONDS = 120
CHAT_HISTORY_LIMIT = 30
MODEL_HISTORY_LIMIT = 10
RESERVATION_LOCK_NAMESPACE = 1178686274


class ChatError(Exception):
    def __init__(self, status_code, code, message, retry_after_seconds=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds

    def detail(self):
        detail = {"code": self.code, "message": self.message}
        if self.retry_after_seconds is not None:
            detail["retry_after_seconds"] = self.retry_after_seconds
        return detail


class ChatLeaseLostError(ChatError):
    def __init__(self):
        super().__init__(
            409,
            "CHAT_LEASE_LOST",
            "הבקשה ממשיכה בעיבוד במקום אחר. נסו שוב בעוד רגע.",
            2,
        )


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _claim_request(current_user, request_id, message, lease_token):
    with pool.connection() as conn:
        with conn.transaction():
            created = conn.execute(
                """
                INSERT INTO chat_requests (
                    request_id,
                    user_id,
                    family_id,
                    status,
                    original_message,
                    lease_token,
                    lease_expires_at
                )
                VALUES (
                    %s, %s, %s, 'processing', %s, %s,
                    NOW() + (%s * INTERVAL '1 second')
                )
                ON CONFLICT (user_id, request_id) DO NOTHING
                RETURNING id
                """,
                (
                    request_id,
                    current_user.user_id,
                    current_user.family_id,
                    message,
                    lease_token,
                    CHAT_LEASE_SECONDS,
                ),
            ).fetchone()

            if created:
                created_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO conversation_messages (
                        user_id, role, content, created_at, chat_request_id
                    )
                    VALUES (%s, 'user', %s, %s, %s)
                    """,
                    (
                        current_user.user_id,
                        message,
                        created_at,
                        created[0],
                    ),
                )
                return {"outcome": "claimed", "id": created[0]}

            existing = conn.execute(
                """
                SELECT
                    id,
                    family_id,
                    original_message,
                    status,
                    final_response,
                    error_http_status,
                    error_payload,
                    lease_expires_at <= NOW()
                FROM chat_requests
                WHERE user_id = %s
                  AND request_id = %s
                FOR UPDATE
                """,
                (current_user.user_id, request_id),
            ).fetchone()

            if not existing:
                raise RuntimeError("Chat request conflict could not be loaded")

            (
                database_id,
                stored_family_id,
                stored_message,
                status,
                final_response,
                error_http_status,
                error_payload,
                lease_expired,
            ) = existing

            if stored_family_id != current_user.family_id:
                return {"outcome": "family_mismatch"}
            if stored_message != message:
                return {"outcome": "message_mismatch"}
            if status == "completed":
                return {
                    "outcome": "completed",
                    "response": final_response,
                }
            if status == "failed":
                return {
                    "outcome": "failed",
                    "status_code": error_http_status,
                    "error": error_payload,
                }
            if not lease_expired:
                return {"outcome": "processing"}

            taken_over = conn.execute(
                """
                UPDATE chat_requests
                SET lease_token = %s,
                    lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'processing'
                  AND lease_expires_at <= NOW()
                RETURNING id
                """,
                (lease_token, CHAT_LEASE_SECONDS, database_id),
            ).fetchone()
            if not taken_over:
                return {"outcome": "processing"}
            return {"outcome": "recovered", "id": database_id}


def _renew_lease(chat_request_id, lease_token):
    with pool.connection() as conn:
        renewed = conn.execute(
            """
            UPDATE chat_requests
            SET lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                updated_at = NOW()
            WHERE id = %s
              AND status = 'processing'
              AND lease_token = %s
            RETURNING id
            """,
            (CHAT_LEASE_SECONDS, chat_request_id, lease_token),
        ).fetchone()
    if not renewed:
        raise ChatLeaseLostError()


def _get_completed_action(chat_request_id):
    with pool.connection() as conn:
        row = conn.execute(
            """
            SELECT action_type, result
            FROM chat_tool_actions
            WHERE chat_request_id = %s
              AND status = 'completed'
            """,
            (chat_request_id,),
        ).fetchone()
        if not row:
            return None
        return {"action_type": row[0], "result": row[1]}


def _execute_mutation(
    chat_request_id,
    lease_token,
    current_user,
    action_type,
    arguments,
):
    with pool.connection() as conn:
        with conn.transaction():
            request = conn.execute(
                """
                SELECT id
                FROM chat_requests
                WHERE id = %s
                  AND user_id = %s
                  AND family_id = %s
                  AND status = 'processing'
                  AND lease_token = %s
                FOR UPDATE
                """,
                (
                    chat_request_id,
                    current_user.user_id,
                    current_user.family_id,
                    lease_token,
                ),
            ).fetchone()
            if not request:
                raise ChatLeaseLostError()

            existing = conn.execute(
                """
                SELECT action_type, result
                FROM chat_tool_actions
                WHERE chat_request_id = %s
                FOR UPDATE
                """,
                (chat_request_id,),
            ).fetchone()
            if existing:
                return {
                    "already_executed": True,
                    "action_type": existing[0],
                    "result": existing[1],
                }

            conn.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (RESERVATION_LOCK_NAMESPACE, current_user.family_id),
            )
            action = conn.execute(
                """
                INSERT INTO chat_tool_actions (
                    chat_request_id,
                    action_type,
                    arguments,
                    status,
                    lease_token_at_execution
                )
                VALUES (%s, %s, %s::jsonb, 'processing', %s)
                RETURNING id
                """,
                (
                    chat_request_id,
                    action_type,
                    _json(arguments),
                    lease_token,
                ),
            ).fetchone()

            if action_type == "create_reservation":
                result = _create_reservation_on_connection(
                    conn,
                    current_user.user_id,
                    arguments["start_time"],
                    arguments["end_time"],
                    expected_family_id=current_user.family_id,
                )
            elif action_type == "update_reservation":
                result = _update_reservation_on_connection(
                    conn,
                    arguments["reservation_id"],
                    current_user.user_id,
                    current_user.family_id,
                    arguments["start_time"],
                    arguments["end_time"],
                )
            elif action_type == "cancel_reservation":
                result = _cancel_reservation_on_connection(
                    conn,
                    arguments["reservation_id"],
                    current_user.user_id,
                    current_user.family_id,
                )
            else:
                raise ValueError("Unsupported mutation action")

            conn.execute(
                """
                UPDATE chat_tool_actions
                SET status = 'completed',
                    result = %s::jsonb,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (_json(result), action[0]),
            )
            return {
                "already_executed": False,
                "action_type": action_type,
                "result": result,
            }


def _load_model_history(current_user, limit=MODEL_HISTORY_LIMIT):
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT cm.role, cm.content
            FROM conversation_messages AS cm
            JOIN chat_requests AS cr ON cr.id = cm.chat_request_id
            WHERE cm.user_id = %s
              AND cr.user_id = %s
              AND cr.family_id = %s
              AND cr.status = 'completed'
            ORDER BY cm.id DESC
            LIMIT %s
            """,
            (
                current_user.user_id,
                current_user.user_id,
                current_user.family_id,
                limit,
            ),
        ).fetchall()
    return list(reversed(rows))


def get_chat_history(current_user, limit=CHAT_HISTORY_LIMIT):
    safe_limit = min(max(int(limit), 1), 50)
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                cr.request_id::text,
                cr.status,
                cm.role,
                cm.content,
                cm.created_at
            FROM conversation_messages AS cm
            JOIN chat_requests AS cr ON cr.id = cm.chat_request_id
            WHERE cm.user_id = %s
              AND cr.user_id = %s
              AND cr.family_id = %s
              AND cr.status IN ('completed', 'failed')
            ORDER BY cm.id DESC
            LIMIT %s
            """,
            (
                current_user.user_id,
                current_user.user_id,
                current_user.family_id,
                safe_limit,
            ),
        ).fetchall()
    return [
        {
            "request_id": row[0],
            "request_status": row[1],
            "role": row[2],
            "content": row[3],
            "created_at": row[4],
        }
        for row in reversed(rows)
    ]


def _finalize_request(chat_request_id, lease_token, current_user, response):
    assistant = response["assistant_message"]
    with pool.connection() as conn:
        with conn.transaction():
            owned = conn.execute(
                """
                SELECT id
                FROM chat_requests
                WHERE id = %s
                  AND user_id = %s
                  AND family_id = %s
                  AND status = 'processing'
                  AND lease_token = %s
                FOR UPDATE
                """,
                (
                    chat_request_id,
                    current_user.user_id,
                    current_user.family_id,
                    lease_token,
                ),
            ).fetchone()
            if not owned:
                raise ChatLeaseLostError()

            conn.execute(
                """
                INSERT INTO conversation_messages (
                    user_id, role, content, created_at, chat_request_id
                )
                VALUES (%s, 'assistant', %s, %s, %s)
                """,
                (
                    current_user.user_id,
                    assistant["content"],
                    assistant["created_at"],
                    chat_request_id,
                ),
            )
            completed = conn.execute(
                """
                UPDATE chat_requests
                SET status = 'completed',
                    final_response = %s::jsonb,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'processing'
                  AND lease_token = %s
                RETURNING id
                """,
                (_json(response), chat_request_id, lease_token),
            ).fetchone()
            if not completed:
                raise ChatLeaseLostError()
    return response


def _mark_failed(chat_request_id, lease_token, error):
    error_payload = {"detail": error.detail()}
    with pool.connection() as conn:
        failed = conn.execute(
            """
            UPDATE chat_requests AS cr
            SET status = 'failed',
                error_http_status = %s,
                error_payload = %s::jsonb,
                completed_at = NOW(),
                updated_at = NOW()
            WHERE cr.id = %s
              AND cr.status = 'processing'
              AND cr.lease_token = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM chat_tool_actions AS action
                  WHERE action.chat_request_id = cr.id
                    AND action.status = 'completed'
              )
            RETURNING id
            """,
            (
                error.status_code,
                _json(error_payload),
                chat_request_id,
                lease_token,
            ),
        ).fetchone()
    return bool(failed)


def _fallback_for_action(action):
    result = action["result"]
    if result.get("success"):
        messages = {
            "create_reservation": "ההזמנה נוצרה בהצלחה.",
            "update_reservation": "ההזמנה עודכנה בהצלחה.",
            "cancel_reservation": "ההזמנה בוטלה בהצלחה.",
        }
    else:
        messages = {
            "RESERVATION_CONFLICT": "הרכב כבר מוזמן בזמן הזה. ההזמנה לא נוצרה.",
            "RESERVATION_NOT_FOUND_OR_UNAVAILABLE": "לא מצאתי הזמנה זמינה שאפשר לשנות או לבטל.",
            "USER_FAMILY_NOT_FOUND": "לא ניתן לבצע את הפעולה בלי שיוך למשפחה.",
        }
    return messages.get(
        action["action_type"] if result.get("success") else result.get("code"),
        "הפעולה לא הושלמה. אפשר לנסות שוב בהודעה חדשה.",
    )


def _response(request_id, content):
    return {
        "request_id": str(request_id),
        "status": "completed",
        "assistant_message": {
            "role": "assistant",
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _finalize_completed_action(
    chat_request_id,
    lease_token,
    current_user,
    request_id,
    completed_action,
):
    try:
        return _finalize_request(
            chat_request_id,
            lease_token,
            current_user,
            _response(request_id, _fallback_for_action(completed_action)),
        )
    except ChatError:
        raise
    except Exception as error:
        logger.warning(
            "Chat action recovery finalization failed",
            extra={
                "operation": "finalize_completed_chat_action",
                "exception_type": type(error).__name__,
            },
        )
        raise ChatError(
            503,
            "CHAT_RECOVERY_REQUIRED",
            "הפעולה נשמרה והבקשה עדיין מתאוששת. נסו שוב עם אותו מזהה בעוד רגע.",
            2,
        ) from error


def process_chat_message(request_id, message, current_user: CurrentUser):
    if current_user.family_id is None:
        raise ChatError(403, "FAMILY_REQUIRED", "המשתמש אינו משויך למשפחה.")

    lease_token = str(uuid4())
    claim = _claim_request(current_user, request_id, message, lease_token)
    outcome = claim["outcome"]
    if outcome == "completed":
        return claim["response"]
    if outcome == "failed":
        payload = claim["error"] or {"detail": {}}
        detail = payload.get("detail", {})
        raise ChatError(
            claim["status_code"] or 502,
            detail.get("code", "AI_UNAVAILABLE"),
            detail.get("message", "לא הצלחנו לקבל תשובה כרגע."),
        )
    if outcome == "processing":
        raise ChatError(409, "CHAT_IN_PROGRESS", "ההודעה עדיין בעיבוד.", 2)
    if outcome == "message_mismatch":
        raise ChatError(
            409,
            "IDEMPOTENCY_KEY_REUSED",
            "מזהה הבקשה כבר שייך להודעה אחרת.",
        )
    if outcome == "family_mismatch":
        raise ChatError(
            409,
            "REQUEST_CONTEXT_CHANGED",
            "לא ניתן להשתמש בבקשה הזו בהקשר המשפחתי הנוכחי.",
        )

    chat_request_id = claim["id"]
    completed_action = _get_completed_action(chat_request_id)
    if completed_action:
        return _finalize_completed_action(
            chat_request_id,
            lease_token,
            current_user,
            request_id,
            completed_action,
        )

    history = _load_model_history(current_user)
    mutation_was_executed = False

    def dispatch_mutation(action_type, arguments):
        nonlocal mutation_was_executed
        if mutation_was_executed:
            return {
                "success": False,
                "code": "ONE_MUTATION_PER_MESSAGE",
                "message": "Send another message for an additional action",
            }
        _renew_lease(chat_request_id, lease_token)
        executed = _execute_mutation(
            chat_request_id,
            lease_token,
            current_user,
            action_type,
            arguments,
        )
        mutation_was_executed = True
        return executed["result"]

    try:
        _renew_lease(chat_request_id, lease_token)
        reply = generate_agent_response(
            message,
            current_user,
            history,
            dispatch_mutation,
        )
        _renew_lease(chat_request_id, lease_token)
        return _finalize_request(
            chat_request_id,
            lease_token,
            current_user,
            _response(request_id, reply),
        )
    except ChatError:
        raise
    except Exception as error:
        logger.warning(
            "Chat processing failed",
            extra={
                "operation": "process_chat_message",
                "exception_type": type(error).__name__,
            },
        )
        completed_action = _get_completed_action(chat_request_id)
        if completed_action:
            return _finalize_completed_action(
                chat_request_id,
                lease_token,
                current_user,
                request_id,
                completed_action,
            )
        safe_error = ChatError(
            502,
            "AI_UNAVAILABLE",
            "לא הצלחנו לקבל תשובה כרגע. אפשר לנסות שוב.",
        )
        if not _mark_failed(chat_request_id, lease_token, safe_error):
            raise ChatError(
                503,
                "CHAT_RECOVERY_REQUIRED",
                "הבקשה עדיין מתאוששת. נסו שוב עם אותו מזהה בעוד רגע.",
                2,
            ) from error
        raise safe_error from error
