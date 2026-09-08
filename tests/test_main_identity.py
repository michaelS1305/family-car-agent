import importlib.util
import inspect
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
import fastapi.exceptions
import fastapi.exception_handlers
import fastapi.responses

from identity import AuthenticatedSupabaseUser, CurrentUser


class FakeHTTPException(Exception):
    def __init__(self, status_code, detail, headers=None):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class FakeFastAPI:
    def __init__(self):
        self.routes = {}

    def get(self, path, **options):
        return self._route_decorator("GET", path, options)

    def post(self, path, **options):
        return self._route_decorator("POST", path, options)

    def patch(self, path, **options):
        return self._route_decorator("PATCH", path, options)

    def add_middleware(self, middleware, **options):
        self.middleware = (middleware, options)

    def exception_handler(self, exception_type):
        return lambda handler: handler

    def _route_decorator(self, method, path, options):
        def decorator(function):
            self.routes[(method, path)] = {
                "function": function,
                **options,
            }
            return function

        return decorator


class FakeDependency:
    def __init__(self, dependency):
        self.dependency = dependency


def stub_module(name, **attributes):
    module = types.ModuleType(name)
    for attribute_name, value in attributes.items():
        setattr(module, attribute_name, value)
    return module


fastapi_stub = stub_module(
    "fastapi",
    Depends=lambda dependency: FakeDependency(dependency),
    FastAPI=FakeFastAPI,
    HTTPException=FakeHTTPException,
    Response=type("Response", (), {"__init__": lambda self: setattr(self, "headers", {})}),
)
cors_stub = stub_module("fastapi.middleware.cors", CORSMiddleware=type("CORSMiddleware", (), {}))
dotenv_stub = stub_module("dotenv", load_dotenv=Mock())
models_stub = stub_module(
    "models",
    CarConnection=type("CarConnection", (), {}),
    CarDisconnectRequest=type("CarDisconnectRequest", (), {}),
    CarPlaySetupResponse=type("CarPlaySetupResponse", (), {}),
    CarPlaySetupStatusRequest=type("CarPlaySetupStatusRequest", (), {}),
    CarHistoryResponse=type("CarHistoryResponse", (), {}),
    CarStatusResponse=type("CarStatusResponse", (), {}),
    ChatRequest=type("ChatRequest", (), {}),
    CreateFamilyAddressRequest=type("CreateFamilyAddressRequest", (), {}),
    CreateFamilyRequest=type("CreateFamilyRequest", (), {}),
    FamilyMemberResponse=type("FamilyMemberResponse", (), {}),
    FamilyAddressResolveRequest=type("FamilyAddressResolveRequest", (), {}),
    FamilyAddressResolveResponse=type("FamilyAddressResolveResponse", (), {}),
    FamilyAddressUpdateRequest=type("FamilyAddressUpdateRequest", (), {}),
    FamilyAddressUpdateResponse=type("FamilyAddressUpdateResponse", (), {}),
    FamilyResponse=type("FamilyResponse", (), {}),
    FamilyRoleUpdateRequest=type("FamilyRoleUpdateRequest", (), {}),
    JoinFamilyAddressConfirmationRequest=type("JoinFamilyAddressConfirmationRequest", (), {}),
    JoinFamilyAddressRequest=type("JoinFamilyAddressRequest", (), {}),
    JoinFamilyCodeRequest=type("JoinFamilyCodeRequest", (), {}),
    JoinFamilyCompleteRequest=type("JoinFamilyCompleteRequest", (), {}),
    JoinFamilyNameRequest=type("JoinFamilyNameRequest", (), {}),
    PushConfigResponse=type("PushConfigResponse", (), {}),
    PushSubscriptionRemoveRequest=type("PushSubscriptionRemoveRequest", (), {}),
    PushSubscriptionRequest=type("PushSubscriptionRequest", (), {}),
    ReservationCancelRequest=type("ReservationCancelRequest", (), {}),
    ReservationIntervalRequest=type("ReservationIntervalRequest", (), {}),
    ReservationResponse=type("ReservationResponse", (), {}),
    ReservationUpdateRequest=type("ReservationUpdateRequest", (), {}),
)
database_stub = stub_module(
    "database",
    init_db=Mock(),
)
car_stub = stub_module(
    "car_service",
    CarStatusError=type("CarStatusError", (Exception,), {}),
    connect_user=Mock(),
    disconnect_user=Mock(),
    get_car_status=Mock(return_value="available"),
)


class FakeCarHistoryError(Exception):
    def __init__(self, code="HISTORY_ERROR", message="History error", status_code=403):
        self.code = code
        self.message = message
        self.status_code = status_code


history_stub = stub_module(
    "history_service",
    CarHistoryError=FakeCarHistoryError,
    get_car_history=Mock(return_value={"active_usage": None, "recent_usage": []}),
)


class FakeChatError(Exception):
    def __init__(self, status_code=409, code="CHAT_ERROR", message="Chat error"):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = None

    def detail(self):
        return {"code": self.code, "message": self.message}


chat_stub = stub_module(
    "chat_service",
    ChatError=FakeChatError,
    get_chat_history=Mock(return_value=[]),
    process_chat_message=Mock(),
)
carplay_setup_value = types.SimpleNamespace(
    connection_code="private-code",
    connect_shortcut_url="https://www.icloud.com/shortcuts/connect",
    disconnect_shortcut_url="https://www.icloud.com/shortcuts/disconnect",
)


class FakeCarPlaySetupError(Exception):
    def __init__(self, code, message, status_code):
        self.code = code
        self.message = message
        self.status_code = status_code


carplay_setup_stub = stub_module(
    "carplay_setup_service",
    CarPlaySetupError=FakeCarPlaySetupError,
    prepare_carplay_setup=Mock(return_value=carplay_setup_value),
    update_carplay_setup_status=Mock(return_value="completed"),
)
auth_stub = stub_module(
    "auth_service",
    get_current_user=Mock(),
    get_authenticated_supabase_user=Mock(),
)


class FakeFamilyCreationError(Exception):
    def __init__(self, code, message, status_code):
        self.code = code
        self.message = message
        self.status_code = status_code


family_creation_stub = stub_module(
    "family_creation_service",
    FamilyCreationError=FakeFamilyCreationError,
    create_family_for_auth_user=Mock(return_value={"created": True}),
    resolve_create_family_address=Mock(),
)


class FakeFamilyProfileError(Exception):
    def __init__(self, code="FAMILY_ERROR", message="Family error", status_code=403):
        self.code = code
        self.message = message
        self.status_code = status_code


family_profile_stub = stub_module(
    "family_service",
    FamilyProfileError=FakeFamilyProfileError,
    get_family_for_current_user=Mock(),
    resolve_family_address_for_current_user=Mock(),
    set_family_member_role=Mock(),
    update_family_address_for_current_user=Mock(),
)


class FakeJoinFamilyError(Exception):
    def __init__(self, code="JOIN_ERROR", message="Join error", status_code=400):
        self.code = code
        self.message = message
        self.status_code = status_code

    def detail(self):
        return {"code": self.code, "message": self.message}


join_family_stub = stub_module(
    "join_family_service",
    JoinFamilyError=FakeJoinFamilyError,
    complete_join_family=Mock(return_value={"created": True}),
    confirm_join_family_address=Mock(),
    start_join_family=Mock(),
    submit_join_family_address=Mock(),
    submit_join_family_code=Mock(),
    submit_join_family_name=Mock(return_value={"step": "address"}),
)


class FakeReservationCenterError(Exception):
    def __init__(self, code="RESERVATION_ERROR", message="Reservation error", status_code=400):
        self.code = code
        self.message = message
        self.status_code = status_code


reservation_stub = stub_module(
    "reservation_service",
    ReservationCenterError=FakeReservationCenterError,
    cancel_reservation_for_current_user=Mock(return_value={"cancelled": True}),
    create_reservation_for_current_user=Mock(),
    list_reservations=Mock(return_value=[]),
    update_reservation_for_current_user=Mock(),
)


class FakePushServiceError(Exception):
    def __init__(self, code="PUSH_ERROR", message="Push error", status_code=400):
        self.code = code
        self.message = message
        self.status_code = status_code


push_stub = stub_module(
    "push_service",
    PushServiceError=FakePushServiceError,
    get_public_push_config=Mock(return_value={"enabled": False, "public_vapid_key": None}),
    register_push_subscription=Mock(return_value={"registered": True}),
    unregister_push_subscription=Mock(return_value={"removed": True}),
)


def load_main_module(environment=None):
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("main_under_test", module_path)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(os.environ, environment or {}, clear=True):
        with patch.dict(
            sys.modules,
            {
                "dotenv": dotenv_stub,
                "fastapi": fastapi_stub,
                "fastapi.middleware.cors": cors_stub,
                "models": models_stub,
                "database": database_stub,
                "car_service": car_stub,
                "history_service": history_stub,
                "chat_service": chat_stub,
                "carplay_setup_service": carplay_setup_stub,
                "auth_service": auth_stub,
                "family_creation_service": family_creation_stub,
                "family_service": family_profile_stub,
                "join_family_service": join_family_stub,
                "reservation_service": reservation_stub,
                "push_service": push_stub,
            },
        ):
            spec.loader.exec_module(module)

    return module


main = load_main_module()


class StartupConfigurationTests(unittest.TestCase):
    def setUp(self):
        database_stub.init_db.reset_mock()

    def test_missing_run_db_init_does_not_initialize_schema(self):
        load_main_module({})

        database_stub.init_db.assert_not_called()

    def test_false_run_db_init_does_not_initialize_schema(self):
        load_main_module({"RUN_DB_INIT": "false"})

        database_stub.init_db.assert_not_called()

    def test_true_run_db_init_initializes_schema(self):
        load_main_module({"RUN_DB_INIT": "true"})

        database_stub.init_db.assert_called_once_with()

    def test_true_run_db_init_is_case_insensitive(self):
        for value in ("TRUE", "True"):
            with self.subTest(value=value):
                database_stub.init_db.reset_mock()

                load_main_module({"RUN_DB_INIT": value})

                database_stub.init_db.assert_called_once_with()

    def test_cors_origins_are_trimmed_deduplicated_and_empty_values_ignored(self):
        configured_main = load_main_module(
            {
                "CORS_ALLOWED_ORIGINS": (
                    " http://localhost:5173, ,http://127.0.0.1:5173,"
                    "https://pwa.example.com,http://localhost:5173 "
                )
            }
        )

        self.assertEqual(
            configured_main.app.middleware[1]["allow_origins"],
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "https://pwa.example.com",
            ],
        )
        self.assertEqual(
            configured_main.app.middleware[1]["allow_methods"],
            ["GET", "POST", "PATCH"],
        )

    def test_cors_wildcard_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "must not contain wildcards"):
            load_main_module({"CORS_ALLOWED_ORIGINS": "https://*.example.com"})


class ApiMeRouteTests(unittest.TestCase):
    def test_route_is_protected_by_get_current_user(self):
        route = main.app.routes[("GET", "/api/me")]
        current_user_parameter = inspect.signature(main.get_me).parameters[
            "current_user"
        ]

        self.assertEqual(route["status_code"], 200)
        self.assertIs(
            current_user_parameter.default.dependency,
            auth_stub.get_current_user,
        )

    def test_route_returns_only_safe_internal_identity(self):
        response = main.get_me(
            CurrentUser(
                user_id=17,
                name="מיכאל",
                family_id=42,
                carplay_setup_status="pending",
            )
        )

        self.assertEqual(
            response,
            {
                "user_id": 17,
                "name": "מיכאל",
                "family_id": 42,
                "carplay_setup_status": "pending",
            },
        )

    def test_route_accepts_no_client_supplied_identity_fields(self):
        parameters = inspect.signature(main.get_me).parameters

        self.assertEqual(tuple(parameters), ("current_user",))
        self.assertNotIn("user_id", parameters)
        self.assertNotIn("family_id", parameters)


class FamilyProfileRouteTests(unittest.TestCase):
    def setUp(self):
        family_profile_stub.get_family_for_current_user.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_profile_stub.set_family_member_role.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_profile_stub.resolve_family_address_for_current_user.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_profile_stub.update_family_address_for_current_user.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_profile_stub.get_family_for_current_user.return_value = {
            "name": "כהן",
            "home_address": "דימונה, המעפיל, 1209",
            "family_code": "482731",
            "can_edit_roles": True,
            "members": [],
        }
        family_profile_stub.set_family_member_role.return_value = {
            "member_ref": "2d6ae768-3d55-4487-aa55-a71ad28259be",
            "name": "נועה",
            "role": "parent",
            "is_family_admin": False,
        }
        family_profile_stub.resolve_family_address_for_current_user.return_value = {
            "normalized_address": "דימונה, המעפיל, 1210",
            "display_address": "המעפיל 1210, דימונה, ישראל",
            "resolution_token": "opaque-address-resolution",
        }
        family_profile_stub.update_family_address_for_current_user.return_value = {
            "home_address": "דימונה, המעפיל, 1210",
        }

    def test_family_read_is_protected_and_scoped_only_by_current_user(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        result = main.get_family(current_user)
        parameters = inspect.signature(main.get_family).parameters

        self.assertEqual(tuple(parameters), ("current_user",))
        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        family_profile_stub.get_family_for_current_user.assert_called_once_with(current_user)
        self.assertNotIn("family_id", result)
        self.assertNotIn("created_by_user_id", result)

    def test_role_patch_uses_current_user_and_public_member_reference(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        member_ref = "2d6ae768-3d55-4487-aa55-a71ad28259be"
        request = types.SimpleNamespace(role="parent", user_id=999, family_id=888)

        result = main.set_family_role(member_ref, request, current_user)
        parameters = inspect.signature(main.set_family_role).parameters

        self.assertEqual(tuple(parameters), ("member_ref", "request", "current_user"))
        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        family_profile_stub.set_family_member_role.assert_called_once_with(
            current_user,
            member_ref,
            "parent",
        )
        self.assertEqual(result["role"], "parent")

    def test_address_resolution_is_authenticated_and_accepts_no_browser_identity(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        request = types.SimpleNamespace(
            home_address="דימונה, המעפיל, 1210",
            user_id=999,
            family_id=888,
        )

        result = main.resolve_current_family_address(request, current_user)
        parameters = inspect.signature(main.resolve_current_family_address).parameters

        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        family_profile_stub.resolve_family_address_for_current_user.assert_called_once_with(
            current_user,
            "דימונה, המעפיל, 1210",
        )
        self.assertNotIn("user_id", result)
        self.assertNotIn("family_id", result)

    def test_address_update_is_authenticated_and_accepts_only_resolution_token(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        request = types.SimpleNamespace(
            resolution_token="opaque-address-resolution",
            user_id=999,
            family_id=888,
            latitude=1.0,
            longitude=2.0,
        )

        result = main.update_current_family_address(request, current_user)
        parameters = inspect.signature(main.update_current_family_address).parameters

        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        family_profile_stub.update_family_address_for_current_user.assert_called_once_with(
            current_user,
            "opaque-address-resolution",
        )
        self.assertEqual(result, {"home_address": "דימונה, המעפיל, 1210"})


class ReservationCenterRouteTests(unittest.TestCase):
    def setUp(self):
        reservation_stub.list_reservations.reset_mock(return_value=True, side_effect=True)
        reservation_stub.create_reservation_for_current_user.reset_mock(return_value=True, side_effect=True)
        reservation_stub.update_reservation_for_current_user.reset_mock(return_value=True, side_effect=True)
        reservation_stub.cancel_reservation_for_current_user.reset_mock(return_value=True, side_effect=True)
        reservation_stub.list_reservations.return_value = []
        reservation_stub.create_reservation_for_current_user.return_value = {"created": True}
        reservation_stub.update_reservation_for_current_user.return_value = {"updated": True}
        reservation_stub.cancel_reservation_for_current_user.return_value = {"cancelled": True}

    def test_list_is_authenticated_and_passes_only_filters_and_current_user(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        result = main.get_reservations("future", "all", current_user)
        parameters = inspect.signature(main.get_reservations).parameters

        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        reservation_stub.list_reservations.assert_called_once_with(current_user, "future", "all")
        self.assertEqual(result, [])

    def test_create_cannot_receive_browser_identity(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        request = types.SimpleNamespace(
            start_time="start",
            end_time="end",
            user_id=999,
            family_id=888,
        )
        main.create_reservation_route(request, current_user)

        reservation_stub.create_reservation_for_current_user.assert_called_once_with(
            current_user,
            "start",
            "end",
        )

    def test_update_and_cancel_use_current_user_and_time_locator(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        update_request = types.SimpleNamespace(
            original_start_time="old-start",
            original_end_time="old-end",
            start_time="new-start",
            end_time="new-end",
        )
        cancel_request = types.SimpleNamespace(
            original_start_time="old-start",
            original_end_time="old-end",
        )

        main.update_reservation_route(update_request, current_user)
        main.cancel_reservation_route(cancel_request, current_user)

        reservation_stub.update_reservation_for_current_user.assert_called_once_with(
            current_user,
            "old-start",
            "old-end",
            "new-start",
            "new-end",
        )
        reservation_stub.cancel_reservation_for_current_user.assert_called_once_with(
            current_user,
            "old-start",
            "old-end",
        )


class ChatRouteTests(unittest.TestCase):
    def setUp(self):
        chat_stub.process_chat_message.reset_mock(return_value=True, side_effect=True)
        chat_stub.process_chat_message.return_value = {
            "request_id": "request-id",
            "status": "completed",
            "assistant_message": {
                "role": "assistant",
                "content": "תשובה",
                "created_at": "2026-09-02T12:00:00+00:00",
            },
        }
        chat_stub.get_chat_history.reset_mock(return_value=True, side_effect=True)
        chat_stub.get_chat_history.return_value = []

    def test_chat_route_uses_current_user_and_accepts_no_identity_fields(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        request = types.SimpleNamespace(
            request_id="request-id",
            message="מי עם הרכב?",
            user_id=999,
            family_id=888,
            auth_user_id="forged",
        )

        response = main.chat(request, current_user)
        parameters = inspect.signature(main.chat).parameters

        self.assertEqual(tuple(parameters), ("request", "current_user"))
        self.assertIs(
            parameters["current_user"].default.dependency,
            auth_stub.get_current_user,
        )
        chat_stub.process_chat_message.assert_called_once_with(
            "request-id",
            "מי עם הרכב?",
            current_user,
        )
        self.assertEqual(response["status"], "completed")

    def test_history_route_is_scoped_to_current_user(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        response = main.chat_history(30, current_user)
        parameters = inspect.signature(main.chat_history).parameters

        self.assertIs(
            parameters["current_user"].default.dependency,
            auth_stub.get_current_user,
        )
        chat_stub.get_chat_history.assert_called_once_with(current_user, 30)
        self.assertEqual(response, {"messages": []})


class CarStatusRouteTests(unittest.TestCase):
    def setUp(self):
        car_stub.get_car_status.reset_mock(return_value=True, side_effect=True)
        car_stub.get_car_status.return_value = "available"

    def test_route_is_protected_scoped_and_not_cached(self):
        response = fastapi_stub.Response()
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        result = main.car_status(response, current_user)
        parameters = inspect.signature(main.car_status).parameters

        self.assertEqual(tuple(parameters), ("response", "current_user"))
        self.assertIs(
            parameters["current_user"].default.dependency,
            auth_stub.get_current_user,
        )
        self.assertEqual(result, {"status": "available"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        car_stub.get_car_status.assert_called_once_with(current_user)


class PushRouteTests(unittest.TestCase):
    def setUp(self):
        push_stub.get_public_push_config.reset_mock(return_value=True, side_effect=True)
        push_stub.register_push_subscription.reset_mock(return_value=True, side_effect=True)
        push_stub.unregister_push_subscription.reset_mock(return_value=True, side_effect=True)
        push_stub.get_public_push_config.return_value = {
            "enabled": False,
            "public_vapid_key": None,
        }
        push_stub.register_push_subscription.return_value = {"registered": True}
        push_stub.unregister_push_subscription.return_value = {"removed": True}

    def test_all_push_routes_are_protected_by_current_user(self):
        for function, parameter_name in (
            (main.push_config, "current_user"),
            (main.register_push, "current_user"),
            (main.unregister_push, "current_user"),
        ):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters[parameter_name]
                self.assertIs(parameter.default.dependency, auth_stub.get_current_user)

    def test_registration_and_removal_cannot_choose_browser_identity(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        registration = types.SimpleNamespace(
            endpoint="https://push.example/device",
            keys=types.SimpleNamespace(p256dh="key", auth="auth"),
            user_id=999,
            family_id=888,
        )
        removal = types.SimpleNamespace(
            endpoint="https://push.example/device",
            user_id=999,
            family_id=888,
        )

        main.register_push(registration, current_user)
        main.unregister_push(removal, current_user)

        push_stub.register_push_subscription.assert_called_once_with(current_user, registration)
        push_stub.unregister_push_subscription.assert_called_once_with(
            current_user, "https://push.example/device"
        )


class CarHistoryRouteTests(unittest.TestCase):
    def setUp(self):
        history_stub.get_car_history.reset_mock(return_value=True, side_effect=True)
        history_stub.get_car_history.return_value = {
            "active_usage": None,
            "recent_usage": [],
        }

    def test_route_is_protected_family_scoped_and_not_cached(self):
        response = fastapi_stub.Response()
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        result = main.car_history(response, current_user)
        parameters = inspect.signature(main.car_history).parameters

        self.assertEqual(tuple(parameters), ("response", "current_user"))
        self.assertIs(parameters["current_user"].default.dependency, auth_stub.get_current_user)
        history_stub.get_car_history.assert_called_once_with(current_user)
        self.assertEqual(result, {"active_usage": None, "recent_usage": []})
        self.assertEqual(response.headers["Cache-Control"], "no-store")


class CarPlaySetupRouteTests(unittest.TestCase):
    def setUp(self):
        carplay_setup_stub.prepare_carplay_setup.reset_mock(
            return_value=True,
            side_effect=True,
        )
        carplay_setup_stub.prepare_carplay_setup.return_value = carplay_setup_value
        carplay_setup_stub.update_carplay_setup_status.reset_mock(
            return_value=True,
            side_effect=True,
        )
        carplay_setup_stub.update_carplay_setup_status.return_value = "completed"

    def test_route_uses_mapped_identity_and_accepts_no_client_fields(self):
        response = fastapi_stub.Response()
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        result = main.setup_carplay(response, current_user)
        parameters = inspect.signature(main.setup_carplay).parameters
        dependency = parameters["current_user"].default

        self.assertIs(dependency.dependency, auth_stub.get_current_user)
        self.assertEqual(tuple(parameters), ("response", "current_user"))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(result["connection_code"], "private-code")
        carplay_setup_stub.prepare_carplay_setup.assert_called_once_with(current_user)

    def test_status_route_uses_current_user_and_accepts_only_status_request(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)
        request = types.SimpleNamespace(
            status="completed",
            user_id=999,
            family_id=888,
        )

        result = main.set_carplay_status(request, current_user)
        parameters = inspect.signature(main.set_carplay_status).parameters

        self.assertEqual(tuple(parameters), ("request", "current_user"))
        self.assertIs(
            parameters["current_user"].default.dependency,
            auth_stub.get_current_user,
        )
        self.assertEqual(result, {"carplay_setup_status": "completed"})
        carplay_setup_stub.update_carplay_setup_status.assert_called_once_with(
            current_user,
            "completed",
        )


class CreateFamilyRouteTests(unittest.TestCase):
    def setUp(self):
        family_creation_stub.create_family_for_auth_user.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_creation_stub.create_family_for_auth_user.return_value = {"created": True}
        family_creation_stub.resolve_create_family_address.reset_mock(
            return_value=True,
            side_effect=True,
        )
        family_creation_stub.resolve_create_family_address.return_value = (
            types.SimpleNamespace(
                normalized_address="תל אביב, דיזנגוף, 120",
                display_address="דיזנגוף 120, תל אביב, ישראל",
                resolution_token="opaque-resolution-token",
            )
        )

    def test_address_resolution_returns_opaque_token_without_coordinates(self):
        request = types.SimpleNamespace(home_address="תל אביב, דיזנגוף, 120")

        response = main.resolve_family_address(
            request,
            AuthenticatedSupabaseUser(auth_user_id="verified-auth-user"),
        )

        self.assertEqual(response, {
            "normalized_address": "תל אביב, דיזנגוף, 120",
            "display_address": "דיזנגוף 120, תל אביב, ישראל",
            "resolution_token": "opaque-resolution-token",
        })
        self.assertNotIn("latitude", response)
        self.assertNotIn("longitude", response)

    def test_route_uses_unmapped_auth_dependency_and_token_identity(self):
        route = main.app.routes[("POST", "/api/onboarding/create-family")]
        dependency = inspect.signature(main.create_family).parameters[
            "authenticated_user"
        ].default
        request = types.SimpleNamespace(
            family_name="כהן",
            family_code="482731",
            address_resolution_token="opaque-resolution-token",
            user_name="מיכאל",
            auth_user_id="forged",
            user_id=999,
            family_id=888,
        )

        response = main.create_family(
            request,
            AuthenticatedSupabaseUser(auth_user_id="verified-auth-user"),
        )

        self.assertEqual(route["status_code"], 201)
        self.assertIs(
            dependency.dependency,
            auth_stub.get_authenticated_supabase_user,
        )
        self.assertEqual(response, {"created": True})
        family_creation_stub.create_family_for_auth_user.assert_called_once_with(
            auth_user_id="verified-auth-user",
            family_name="כהן",
            family_code="482731",
            address_resolution_token="opaque-resolution-token",
            user_name="מיכאל",
        )

    def test_unexpected_create_failure_returns_structured_server_error(self):
        family_creation_stub.create_family_for_auth_user.side_effect = RuntimeError(
            "database unavailable"
        )
        request = types.SimpleNamespace(
            family_name="כהן",
            family_code="482731",
            address_resolution_token="opaque-resolution-token",
            user_name="מיכאל",
        )

        with self.assertRaises(FakeHTTPException) as raised:
            main.create_family(
                request,
                AuthenticatedSupabaseUser(auth_user_id="verified-auth-user"),
            )

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            {
                "code": "SERVER_ERROR",
                "message": "לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.",
            },
        )

    def test_missing_auth_user_returns_structured_session_error(self):
        family_creation_stub.create_family_for_auth_user.side_effect = (
            FakeFamilyCreationError(
                "AUTH_SESSION_INVALID",
                "ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.",
                401,
            )
        )
        request = types.SimpleNamespace(
            family_name="כהן",
            family_code="482731",
            address_resolution_token="opaque-resolution-token",
            user_name="מיכאל",
        )

        with self.assertRaises(FakeHTTPException) as raised:
            main.create_family(
                request,
                AuthenticatedSupabaseUser(auth_user_id="deleted-auth-user"),
            )

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.detail,
            {
                "code": "AUTH_SESSION_INVALID",
                "message": "ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.",
            },
        )


class JoinFamilyRouteTests(unittest.TestCase):
    def setUp(self):
        join_family_stub.submit_join_family_name.reset_mock(
            return_value=True,
            side_effect=True,
        )
        join_family_stub.submit_join_family_name.return_value = {"step": "address"}

    def test_join_name_uses_verified_auth_identity_and_ignores_forged_ids(self):
        dependency = inspect.signature(main.join_family_name).parameters[
            "authenticated_user"
        ].default
        request = types.SimpleNamespace(
            family_name="כהן",
            auth_user_id="forged",
            user_id=999,
            family_id=888,
        )

        response = main.join_family_name(
            request,
            AuthenticatedSupabaseUser(auth_user_id="verified-auth-user"),
        )

        self.assertIs(
            dependency.dependency,
            auth_stub.get_authenticated_supabase_user,
        )
        self.assertEqual(response, {"step": "address"})
        join_family_stub.submit_join_family_name.assert_called_once_with(
            "verified-auth-user",
            "כהן",
        )


if __name__ == "__main__":
    unittest.main()
