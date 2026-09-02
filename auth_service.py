import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWKClient

from identity import AuthenticatedSupabaseUser, CurrentUser


ALLOWED_ALGORITHMS = ("ES256",)
AUTHENTICATED_AUDIENCE = "authenticated"
AUTHENTICATED_ROLE = "authenticated"

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class SupabaseJWTSettings:
    issuer: str
    jwks_url: str
    audience: str = AUTHENTICATED_AUDIENCE
    algorithms: tuple[str, ...] = ALLOWED_ALGORITHMS

    @classmethod
    def from_environment(cls):
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        if not supabase_url:
            raise RuntimeError("SUPABASE_URL must be configured")

        issuer = f"{supabase_url}/auth/v1"
        jwks_url = f"{issuer}/.well-known/jwks.json"

        return cls(
            issuer=issuer,
            jwks_url=jwks_url,
        )


class SupabaseJWTVerifier:
    def __init__(
        self,
        settings: SupabaseJWTSettings,
        signing_key_resolver: Callable[[str], Any] | None = None,
    ):
        self.settings = settings
        self._jwks_client = None

        if signing_key_resolver is None:
            self._jwks_client = PyJWKClient(settings.jwks_url)
            signing_key_resolver = self._resolve_jwks_signing_key

        self._signing_key_resolver = signing_key_resolver

    def _resolve_jwks_signing_key(self, token):
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def verify(self, token):
        signing_key = self._signing_key_resolver(token)
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=list(self.settings.algorithms),
            issuer=self.settings.issuer,
            audience=self.settings.audience,
            options={
                "require": ["iss", "aud", "exp", "sub", "role"],
            },
        )

        if claims.get("role") != AUTHENTICATED_ROLE:
            raise InvalidTokenError("JWT role is not authenticated")

        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise InvalidTokenError("JWT subject must be a UUID string")

        try:
            auth_user_id = str(UUID(subject))
        except (TypeError, ValueError, AttributeError) as exc:
            raise InvalidTokenError("JWT subject must be a valid UUID") from exc

        return auth_user_id


@lru_cache
def get_jwt_verifier():
    return SupabaseJWTVerifier(SupabaseJWTSettings.from_environment())


def lookup_internal_user(auth_user_id):
    from database import get_user_by_auth_user_id

    return get_user_by_auth_user_id(auth_user_id)


def _unauthorized(detail):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _verify_authenticated_credentials(credentials):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token")

    try:
        verifier = get_jwt_verifier()
        auth_user_id = verifier.verify(credentials.credentials)
    except ExpiredSignatureError as exc:
        raise _unauthorized("Access token has expired") from exc
    except (InvalidTokenError, ValueError, TypeError) as exc:
        raise _unauthorized("Invalid access token") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase JWT verification is not configured",
        ) from exc

    return auth_user_id


def get_authenticated_supabase_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    try:
        auth_user_id = _verify_authenticated_credentials(credentials)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": "UNAUTHORIZED",
                    "message": "יש להתחבר מחדש כדי להמשיך.",
                },
                headers=exc.headers,
            ) from exc
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": "SERVER_ERROR",
                "message": "לא ניתן לאמת את ההתחברות כרגע.",
            },
        ) from exc

    return AuthenticatedSupabaseUser(auth_user_id=auth_user_id)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    auth_user_id = _verify_authenticated_credentials(credentials)

    internal_user = lookup_internal_user(auth_user_id)
    if internal_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user is not registered in the application",
        )
    if internal_user[2] is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user is not assigned to a family",
        )

    return CurrentUser(
        user_id=internal_user[0],
        name=internal_user[1],
        family_id=internal_user[2],
        carplay_setup_status=internal_user[3],
    )
