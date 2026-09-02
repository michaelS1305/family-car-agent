import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from identity import AuthenticatedSupabaseUser, CurrentUser


class FakeHTTPException(Exception):
    def __init__(self, status_code, detail, headers=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class FakeHTTPAuthorizationCredentials:
    def __init__(self, scheme, credentials):
        self.scheme = scheme
        self.credentials = credentials


class FakeHTTPBearer:
    def __init__(self, auto_error):
        self.auto_error = auto_error


class FakeInvalidTokenError(Exception):
    pass


class FakeExpiredSignatureError(FakeInvalidTokenError):
    pass


class FakePyJWKClient:
    def __init__(self, url):
        self.url = url


def stub_module(name, **attributes):
    module = types.ModuleType(name)
    for attribute_name, value in attributes.items():
        setattr(module, attribute_name, value)
    return module


jwt_decode = Mock(name="jwt_decode")
jwt_stub = stub_module(
    "jwt",
    decode=jwt_decode,
    ExpiredSignatureError=FakeExpiredSignatureError,
    InvalidTokenError=FakeInvalidTokenError,
    PyJWKClient=FakePyJWKClient,
)
fastapi_stub = stub_module(
    "fastapi",
    Depends=lambda dependency: dependency,
    HTTPException=FakeHTTPException,
    status=types.SimpleNamespace(
        HTTP_401_UNAUTHORIZED=401,
        HTTP_403_FORBIDDEN=403,
        HTTP_503_SERVICE_UNAVAILABLE=503,
    ),
)
fastapi_security_stub = stub_module(
    "fastapi.security",
    HTTPAuthorizationCredentials=FakeHTTPAuthorizationCredentials,
    HTTPBearer=FakeHTTPBearer,
)


def load_auth_service_module():
    module_path = Path(__file__).resolve().parents[1] / "auth_service.py"
    spec = importlib.util.spec_from_file_location(
        "auth_service_under_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {
            "jwt": jwt_stub,
            "fastapi": fastapi_stub,
            "fastapi.security": fastapi_security_stub,
        },
    ):
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)

    return module


auth_service = load_auth_service_module()

ISSUER = "https://test-project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


class SupabaseAuthenticationTests(unittest.TestCase):
    def setUp(self):
        jwt_decode.reset_mock(return_value=True, side_effect=True)
        self.auth_user_id = str(uuid4())
        self.key_resolver = Mock(return_value="resolved-public-key")
        settings = auth_service.SupabaseJWTSettings(
            issuer=ISSUER,
            jwks_url="https://unused.test/.well-known/jwks.json",
            audience=AUDIENCE,
        )
        self.verifier = auth_service.SupabaseJWTVerifier(
            settings,
            signing_key_resolver=self.key_resolver,
        )

    @staticmethod
    def credentials(token):
        return FakeHTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

    def authenticate(self, token, internal_user=(17, "מיכאל", 42, "pending")):
        with patch.object(
            auth_service,
            "get_jwt_verifier",
            return_value=self.verifier,
        ), patch.object(
            auth_service,
            "lookup_internal_user",
            return_value=internal_user,
        ) as lookup:
            current_user = auth_service.get_current_user(self.credentials(token))

        return current_user, lookup

    def configure_valid_claims(self, **extra_claims):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": 9999999999,
            "sub": self.auth_user_id,
            "role": "authenticated",
        }
        claims.update(extra_claims)
        jwt_decode.return_value = claims

    def test_verifier_checks_signature_and_required_claims(self):
        self.configure_valid_claims()

        auth_user_id = self.verifier.verify("valid-token")

        self.assertEqual(auth_user_id, self.auth_user_id)
        self.key_resolver.assert_called_once_with("valid-token")
        jwt_decode.assert_called_once_with(
            "valid-token",
            "resolved-public-key",
            algorithms=["ES256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["iss", "aud", "exp", "sub", "role"]},
        )

    def test_settings_derive_es256_jwks_configuration_from_supabase_url(self):
        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://test-project.supabase.co/"},
            clear=True,
        ):
            settings = auth_service.SupabaseJWTSettings.from_environment()

        self.assertEqual(settings.issuer, ISSUER)
        self.assertEqual(
            settings.jwks_url,
            f"{ISSUER}/.well-known/jwks.json",
        )
        self.assertEqual(settings.audience, "authenticated")
        self.assertEqual(settings.algorithms, ("ES256",))

    def test_valid_token_returns_current_user_from_internal_lookup(self):
        self.configure_valid_claims()

        current_user, lookup = self.authenticate("valid-token")

        self.assertEqual(
            current_user,
            CurrentUser(
                user_id=17,
                name="מיכאל",
                family_id=42,
                carplay_setup_status="pending",
            ),
        )
        lookup.assert_called_once_with(self.auth_user_id)

    def test_mapped_user_without_family_fails_closed(self):
        self.configure_valid_claims()

        with self.assertRaises(FakeHTTPException) as raised:
            self.authenticate(
                "valid-token",
                internal_user=(17, "מיכאל", None, "pending"),
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            raised.exception.detail,
            "Authenticated user is not assigned to a family",
        )

    def test_unmapped_dependency_returns_auth_identity_without_internal_lookup(self):
        self.configure_valid_claims()

        with patch.object(
            auth_service,
            "get_jwt_verifier",
            return_value=self.verifier,
        ), patch.object(
            auth_service,
            "lookup_internal_user",
        ) as lookup:
            authenticated_user = auth_service.get_authenticated_supabase_user(
                self.credentials("valid-token")
            )

        self.assertEqual(
            authenticated_user,
            AuthenticatedSupabaseUser(auth_user_id=self.auth_user_id),
        )
        lookup.assert_not_called()

    def test_unmapped_dependency_returns_structured_unauthorized_error(self):
        with self.assertRaises(FakeHTTPException) as raised:
            auth_service.get_authenticated_supabase_user(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.detail,
            {
                "code": "UNAUTHORIZED",
                "message": "יש להתחבר מחדש כדי להמשיך.",
            },
        )

    def test_missing_token_is_rejected(self):
        with self.assertRaises(FakeHTTPException) as raised:
            auth_service.get_current_user(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.headers, {"WWW-Authenticate": "Bearer"})

    def test_invalid_token_is_rejected(self):
        verifier = Mock()
        verifier.verify.side_effect = FakeInvalidTokenError("bad token")

        with patch.object(
            auth_service,
            "get_jwt_verifier",
            return_value=verifier,
        ), patch.object(
            auth_service,
            "lookup_internal_user",
        ) as lookup, self.assertRaises(FakeHTTPException) as raised:
            auth_service.get_current_user(self.credentials("invalid-token"))

        self.assertEqual(raised.exception.status_code, 401)
        lookup.assert_not_called()

    def test_expired_token_is_rejected(self):
        verifier = Mock()
        verifier.verify.side_effect = FakeExpiredSignatureError("expired")

        with patch.object(
            auth_service,
            "get_jwt_verifier",
            return_value=verifier,
        ), patch.object(
            auth_service,
            "lookup_internal_user",
        ) as lookup, self.assertRaises(FakeHTTPException) as raised:
            auth_service.get_current_user(self.credentials("expired-token"))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Access token has expired")
        lookup.assert_not_called()

    def test_auth_user_without_internal_user_is_rejected(self):
        self.configure_valid_claims()

        with patch.object(
            auth_service,
            "get_jwt_verifier",
            return_value=self.verifier,
        ), patch.object(
            auth_service,
            "lookup_internal_user",
            return_value=None,
        ) as lookup, self.assertRaises(FakeHTTPException) as raised:
            auth_service.get_current_user(self.credentials("valid-token"))

        self.assertEqual(raised.exception.status_code, 403)
        lookup.assert_called_once_with(self.auth_user_id)

    def test_client_identity_claims_cannot_override_internal_identity(self):
        self.configure_valid_claims(user_id=9999, family_id=8888)

        current_user, lookup = self.authenticate(
            "valid-token",
            internal_user=(17, "מיכאל", 42, "completed"),
        )

        self.assertEqual(current_user.user_id, 17)
        self.assertEqual(current_user.family_id, 42)
        self.assertEqual(current_user.carplay_setup_status, "completed")
        lookup.assert_called_once_with(self.auth_user_id)


if __name__ == "__main__":
    unittest.main()
