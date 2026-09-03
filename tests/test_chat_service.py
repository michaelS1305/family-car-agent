import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from identity import CurrentUser


def load_chat_service():
    database_stub = types.ModuleType("database")
    database_stub.pool = Mock()
    database_stub._create_reservation_on_connection = Mock()
    database_stub._update_reservation_on_connection = Mock()
    database_stub._cancel_reservation_on_connection = Mock()
    ai_stub = types.ModuleType("ai_service")
    ai_stub.generate_agent_response = Mock(return_value="תשובה")
    ai_stub.GEMINI_MODEL = "gemini-3.1-flash-lite"
    path = Path(__file__).resolve().parents[1] / "chat_service.py"
    spec = importlib.util.spec_from_file_location("chat_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub, "ai_service": ai_stub}):
        spec.loader.exec_module(module)
    return module


chat = load_chat_service()


class ChatOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.user = CurrentUser(user_id=7, name="מיכאל", family_id=42)
        self.request_id = UUID("0da80a79-74f1-496f-9bd0-dd4ef43d38a7")
        self.cached = {
            "request_id": str(self.request_id),
            "status": "completed",
            "assistant_message": {
                "role": "assistant",
                "content": "cached",
                "created_at": "2026-09-02T12:00:00+00:00",
            },
        }

    def test_completed_request_returns_exact_cached_response(self):
        with patch.object(chat, "_claim_request", return_value={
            "outcome": "completed",
            "response": self.cached,
        }), patch.object(chat, "generate_agent_response") as generate:
            result = chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)

        self.assertIs(result, self.cached)
        generate.assert_not_called()

    def test_active_processing_request_returns_chat_in_progress(self):
        with patch.object(chat, "_claim_request", return_value={"outcome": "processing"}):
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)
        self.assertEqual(raised.exception.code, "CHAT_IN_PROGRESS")
        self.assertEqual(raised.exception.status_code, 409)

    def test_reused_id_with_different_message_is_rejected(self):
        with patch.object(chat, "_claim_request", return_value={"outcome": "message_mismatch"}):
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "הודעה אחרת", self.user)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")

    def test_reused_id_in_different_family_is_rejected(self):
        with patch.object(chat, "_claim_request", return_value={"outcome": "family_mismatch"}):
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)
        self.assertEqual(raised.exception.code, "REQUEST_CONTEXT_CHANGED")

    def test_failed_request_replays_the_stored_failure(self):
        with patch.object(chat, "_claim_request", return_value={
            "outcome": "failed",
            "status_code": 502,
            "error": {"detail": {"code": "AI_UNAVAILABLE", "message": "stored"}},
        }):
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)
        self.assertEqual(raised.exception.code, "AI_UNAVAILABLE")
        self.assertEqual(raised.exception.message, "stored")

    def test_expired_lease_takeover_completes_normally(self):
        with patch.object(chat, "_claim_request", return_value={"outcome": "recovered", "id": 11}), \
             patch.object(chat, "_get_completed_action", return_value=None), \
             patch.object(chat, "_load_model_history", return_value=[]), \
             patch.object(chat, "_renew_lease"), \
             patch.object(chat, "generate_agent_response", return_value="מוכן"), \
             patch.object(chat, "_finalize_request", side_effect=lambda _id, _lease, _user, response: response):
            result = chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)
        self.assertEqual(result["assistant_message"]["content"], "מוכן")

    def test_gemini_failure_before_mutation_is_terminal_and_safe(self):
        with patch.object(chat, "_claim_request", return_value={"outcome": "claimed", "id": 11}), \
             patch.object(chat, "_get_completed_action", return_value=None), \
             patch.object(chat, "_load_model_history", return_value=[]), \
             patch.object(chat, "_renew_lease"), \
             patch.object(chat, "generate_agent_response", side_effect=RuntimeError("provider")), \
             patch.object(chat, "_mark_failed", return_value=True) as mark_failed:
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "מי עם הרכב?", self.user)
        self.assertEqual(raised.exception.code, "AI_UNAVAILABLE")
        mark_failed.assert_called_once()

    def test_chat_request_logs_accumulated_usage_without_message_content(self):
        def generate(
            _message,
            _user,
            _history,
            _dispatcher,
            usage_accumulator=None,
        ):
            usage_accumulator.add_response(types.SimpleNamespace(
                usage_metadata=types.SimpleNamespace(
                    prompt_token_count=12,
                    candidates_token_count=4,
                    total_token_count=16,
                )
            ))
            return "מוכן"

        with patch.object(chat, "_claim_request", return_value={
            "outcome": "claimed",
            "id": 11,
        }), patch.object(chat, "_get_completed_action", return_value=None), \
             patch.object(chat, "_load_model_history", return_value=[]), \
             patch.object(chat, "_renew_lease"), \
             patch.object(chat, "generate_agent_response", side_effect=generate), \
             patch.object(
                 chat,
                 "_finalize_request",
                 side_effect=lambda _id, _lease, _user, response: response,
             ), self.assertLogs(chat.logger, level="INFO") as captured:
            chat.process_chat_message(
                self.request_id,
                "private family message",
                self.user,
            )

        usage_log = next(
            line for line in captured.output if "operation=gemini_usage" in line
        )
        self.assertIn("input_tokens=12", usage_log)
        self.assertIn("output_tokens=4", usage_log)
        self.assertIn("total_tokens=16", usage_log)
        self.assertNotIn("private family message", usage_log)

    def test_failure_after_committed_mutation_uses_deterministic_fallback(self):
        action = {
            "action_type": "create_reservation",
            "result": {"success": True, "code": "RESERVATION_CREATED"},
        }
        with patch.object(chat, "_claim_request", return_value={"outcome": "claimed", "id": 11}), \
             patch.object(chat, "_get_completed_action", side_effect=[None, action]), \
             patch.object(chat, "_load_model_history", return_value=[]), \
             patch.object(chat, "_renew_lease"), \
             patch.object(chat, "generate_agent_response", side_effect=RuntimeError("after tool")), \
             patch.object(chat, "_finalize_request", side_effect=lambda _id, _lease, _user, response: response), \
             patch.object(chat, "_mark_failed") as mark_failed:
            result = chat.process_chat_message(self.request_id, "תזמין", self.user)
        self.assertEqual(result["assistant_message"]["content"], "ההזמנה נוצרה בהצלחה.")
        mark_failed.assert_not_called()

    def test_only_one_mutation_is_dispatched_per_request(self):
        mutation_results = []

        def model(
            _message,
            _user,
            _history,
            dispatcher,
            usage_accumulator=None,
        ):
            mutation_results.append(dispatcher("cancel_reservation", {"reservation_id": 5}))
            mutation_results.append(dispatcher("cancel_reservation", {"reservation_id": 6}))
            return "בוצע"

        with patch.object(chat, "_claim_request", return_value={"outcome": "claimed", "id": 11}), \
             patch.object(chat, "_get_completed_action", return_value=None), \
             patch.object(chat, "_load_model_history", return_value=[]), \
             patch.object(chat, "_renew_lease"), \
             patch.object(chat, "generate_agent_response", side_effect=model), \
             patch.object(chat, "_execute_mutation", return_value={
                 "result": {"success": True, "code": "RESERVATION_CANCELLED"}
             }) as execute, \
             patch.object(chat, "_finalize_request", side_effect=lambda _id, _lease, _user, response: response):
            chat.process_chat_message(self.request_id, "בטל", self.user)
        execute.assert_called_once()
        self.assertEqual(mutation_results[1]["code"], "ONE_MUTATION_PER_MESSAGE")

    def test_user_without_family_fails_closed_before_claim(self):
        with patch.object(chat, "_claim_request") as claim:
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(
                    self.request_id,
                    "מי עם הרכב?",
                    CurrentUser(user_id=7, name="מיכאל", family_id=None),
                )
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "FAMILY_REQUIRED")
        claim.assert_not_called()

    def test_finalization_failure_after_mutation_is_recoverable(self):
        action = {
            "action_type": "update_reservation",
            "result": {"success": True, "code": "RESERVATION_UPDATED"},
        }
        with patch.object(chat, "_claim_request", return_value={"outcome": "recovered", "id": 11}), \
             patch.object(chat, "_get_completed_action", return_value=action), \
             patch.object(chat, "_finalize_request", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(chat.ChatError) as raised:
                chat.process_chat_message(self.request_id, "עדכן", self.user)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.code, "CHAT_RECOVERY_REQUIRED")

    def test_safe_failure_logging_includes_stage_without_credentials(self):
        error = RuntimeError("Authorization: Bearer private-access-token")
        error.chat_stage = "gemini_initial_call"
        error.gemini_model = "gemini-3.1-flash-lite"
        error.gemini_api_key_configured = True

        with self.assertLogs(chat.logger, level="WARNING") as captured:
            chat._log_chat_processing_failure(
                error,
                "finalization",
                self.request_id,
                11,
            )

        log_line = captured.output[0]
        self.assertIn("operation=process_chat_message", log_line)
        self.assertIn("stage=gemini_initial_call", log_line)
        self.assertIn("exception_class=RuntimeError", log_line)
        self.assertIn("request_id=0da80a79-74f1-496f-9bd0-dd4ef43d38a7", log_line)
        self.assertIn("chat_request_id=11", log_line)
        self.assertIn("safe_message=[redacted]", log_line)
        self.assertNotIn("private-access-token", log_line)

    def test_safe_provider_message_keeps_non_sensitive_status(self):
        provider_error_type = type(
            "ClientError",
            (RuntimeError,),
            {"__module__": "google.genai.errors"},
        )
        error = provider_error_type(
            "429 RESOURCE_EXHAUSTED: prepayment credits depleted"
        )

        with self.assertLogs(chat.logger, level="WARNING") as captured:
            chat._log_chat_processing_failure(
                error,
                "gemini_initial_call",
                self.request_id,
                11,
            )

        self.assertIn("RESOURCE_EXHAUSTED", captured.output[0])


class RecordingTransaction:
    def __init__(self):
        self.rolled_back = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _value, _traceback):
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        return False


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.row or [])


class MutationConnection:
    def __init__(self, lease_valid=True, existing_action=None):
        self.transaction_state = RecordingTransaction()
        self.lease_valid = lease_valid
        self.existing_action = existing_action

    def transaction(self):
        return self.transaction_state

    def execute(self, sql, _parameters=()):
        compact = " ".join(sql.split())
        if "FROM chat_requests" in compact:
            return Cursor((11,) if self.lease_valid else None)
        if "SELECT action_type, result" in compact:
            return Cursor(self.existing_action)
        if "pg_advisory_xact_lock" in compact:
            return Cursor((None,))
        if "INSERT INTO chat_tool_actions" in compact:
            return Cursor((91,))
        if "UPDATE chat_tool_actions" in compact:
            return Cursor()
        raise AssertionError(compact)


class ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, _type, _value, _traceback):
        return False


class HistoryConnection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.parameters = None

    def execute(self, sql, parameters=()):
        self.sql = " ".join(sql.split())
        self.parameters = parameters
        return Cursor(self.rows)


class MutationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.user = CurrentUser(user_id=7, name="מיכאל", family_id=42)

    def test_mutation_and_action_commit_on_the_same_connection(self):
        connection = MutationConnection()
        chat.pool.connection.return_value = ConnectionContext(connection)
        result = {"success": True, "code": "RESERVATION_CREATED", "reservation_id": 55}
        with patch.object(chat, "_create_reservation_on_connection", return_value=result) as create:
            executed = chat._execute_mutation(
                11,
                "lease-token",
                self.user,
                "create_reservation",
                {"start_time": "start", "end_time": "end"},
            )
        self.assertTrue(connection.transaction_state.committed)
        create.assert_called_once_with(
            connection,
            7,
            "start",
            "end",
            expected_family_id=42,
        )
        self.assertEqual(executed["result"], result)

    def test_crash_before_commit_rolls_back_action_and_mutation(self):
        connection = MutationConnection()
        chat.pool.connection.return_value = ConnectionContext(connection)
        with patch.object(chat, "_create_reservation_on_connection", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                chat._execute_mutation(
                    11,
                    "lease-token",
                    self.user,
                    "create_reservation",
                    {"start_time": "start", "end_time": "end"},
                )
        self.assertTrue(connection.transaction_state.rolled_back)

    def test_update_and_cancel_use_connection_aware_scoped_helpers(self):
        cases = (
            (
                "update_reservation",
                {"reservation_id": 5, "start_time": "start", "end_time": "end"},
                "_update_reservation_on_connection",
                (5, 7, 42, "start", "end"),
                {"success": True, "code": "RESERVATION_UPDATED"},
            ),
            (
                "cancel_reservation",
                {"reservation_id": 5},
                "_cancel_reservation_on_connection",
                (5, 7, 42),
                {"success": True, "code": "RESERVATION_CANCELLED"},
            ),
        )
        for action_type, arguments, helper_name, expected_args, result in cases:
            with self.subTest(action_type=action_type):
                connection = MutationConnection()
                chat.pool.connection.return_value = ConnectionContext(connection)
                with patch.object(chat, helper_name, return_value=result) as helper:
                    executed = chat._execute_mutation(
                        11,
                        "lease-token",
                        self.user,
                        action_type,
                        arguments,
                    )
                helper.assert_called_once_with(connection, *expected_args)
                self.assertTrue(connection.transaction_state.committed)
                self.assertEqual(executed["result"], result)

    def test_business_failure_is_committed_as_completed_action(self):
        connection = MutationConnection()
        chat.pool.connection.return_value = ConnectionContext(connection)
        conflict = {"success": False, "code": "RESERVATION_CONFLICT"}
        with patch.object(chat, "_create_reservation_on_connection", return_value=conflict):
            executed = chat._execute_mutation(
                11,
                "lease-token",
                self.user,
                "create_reservation",
                {"start_time": "start", "end_time": "end"},
            )
        self.assertTrue(connection.transaction_state.committed)
        self.assertEqual(executed["result"], conflict)

    def test_completed_action_is_replayed_without_mutation(self):
        stored = {"success": True, "code": "RESERVATION_CANCELLED"}
        connection = MutationConnection(existing_action=("cancel_reservation", stored))
        chat.pool.connection.return_value = ConnectionContext(connection)
        with patch.object(chat, "_cancel_reservation_on_connection") as cancel:
            result = chat._execute_mutation(
                11,
                "lease-token",
                self.user,
                "cancel_reservation",
                {"reservation_id": 5},
            )
        cancel.assert_not_called()
        self.assertTrue(result["already_executed"])
        self.assertEqual(result["result"], stored)

    def test_old_worker_is_fenced_before_mutation(self):
        connection = MutationConnection(lease_valid=False)
        chat.pool.connection.return_value = ConnectionContext(connection)
        with patch.object(chat, "_cancel_reservation_on_connection") as cancel:
            with self.assertRaises(chat.ChatLeaseLostError):
                chat._execute_mutation(
                    11,
                    "old-lease",
                    self.user,
                    "cancel_reservation",
                    {"reservation_id": 5},
                )
        cancel.assert_not_called()

    def test_history_is_scoped_ordered_and_excludes_processing_requests(self):
        rows = [
            ("request-2", "failed", "user", "שאלה שנכשלה", "two"),
            ("request-1", "completed", "assistant", "תשובה", "one"),
        ]
        connection = HistoryConnection(rows)
        chat.pool.connection.return_value = ConnectionContext(connection)

        history = chat.get_chat_history(self.user, 500)

        self.assertEqual(connection.parameters, (7, 7, 42, 50))
        self.assertIn("cr.status IN ('completed', 'failed')", connection.sql)
        self.assertIn("ORDER BY cm.id DESC", connection.sql)
        self.assertEqual(history[0]["request_id"], "request-1")
        self.assertEqual(history[1]["request_status"], "failed")


if __name__ == "__main__":
    unittest.main()
