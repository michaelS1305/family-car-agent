import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from models import (
    CarConnection,
    CarPlaySetupResponse,
    CarPlaySetupStatusRequest,
    CarStatusResponse,
    ChatRequest,
    CreateFamilyAddressRequest,
    CreateFamilyRequest,
    JoinFamilyAddressConfirmationRequest,
    JoinFamilyAddressRequest,
    JoinFamilyCodeRequest,
    JoinFamilyCompleteRequest,
    JoinFamilyNameRequest,
)
from database import (
    init_db,
)
from car_service import CarStatusError, connect_user, disconnect_user, get_car_status
from chat_service import ChatError, get_chat_history, process_chat_message
from carplay_setup_service import (
    CarPlaySetupError,
    prepare_carplay_setup,
    update_carplay_setup_status,
)
from auth_service import get_authenticated_supabase_user, get_current_user
from family_creation_service import (
    FamilyCreationError,
    create_family_for_auth_user,
    resolve_create_family_address,
)
from identity import AuthenticatedSupabaseUser, CurrentUser
from join_family_service import (
    JoinFamilyError,
    complete_join_family,
    confirm_join_family_address,
    start_join_family,
    submit_join_family_address,
    submit_join_family_code,
    submit_join_family_name,
)

def _environment_flag_is_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def _cors_allowed_origins() -> list[str]:
    origins = []
    for configured_origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(","):
        origin = configured_origin.strip()
        if not origin:
            continue
        if "*" in origin:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must not contain wildcards")
        if origin not in origins:
            origins.append(origin)
    return origins


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

if _environment_flag_is_true("RUN_DB_INIT"):
    init_db()


@app.get("/")
def home():
    return {"message": "Family Car Agent is running"}


@app.get("/api/me", status_code=200)
def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return {
        "user_id": current_user.user_id,
        "name": current_user.name,
        "family_id": current_user.family_id,
        "carplay_setup_status": current_user.carplay_setup_status,
    }


def _raise_chat_error(error):
    headers = None
    if error.retry_after_seconds is not None:
        headers = {"Retry-After": str(error.retry_after_seconds)}
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail(),
        headers=headers,
    ) from error


@app.post("/api/chat", status_code=200)
def chat(
    request: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return process_chat_message(
            request.request_id,
            request.message,
            current_user,
        )
    except ChatError as error:
        _raise_chat_error(error)


@app.get("/api/chat/history", status_code=200)
def chat_history(
    limit: int = 30,
    current_user: CurrentUser = Depends(get_current_user),
):
    return {"messages": get_chat_history(current_user, limit)}


@app.get("/api/car/status", response_model=CarStatusResponse, status_code=200)
def car_status(
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        status = get_car_status(current_user)
    except CarStatusError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return {"status": status}


@app.post(
    "/api/carplay/setup",
    response_model=CarPlaySetupResponse,
    status_code=200,
)
def setup_carplay(
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        setup = prepare_carplay_setup(current_user)
    except CarPlaySetupError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    return {
        "connection_code": setup.connection_code,
        "connect_shortcut_url": setup.connect_shortcut_url,
        "disconnect_shortcut_url": setup.disconnect_shortcut_url,
    }


@app.post("/api/carplay/setup/status", status_code=200)
def set_carplay_status(
    request: CarPlaySetupStatusRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        setup_status = update_carplay_setup_status(current_user, request.status)
    except CarPlaySetupError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return {"carplay_setup_status": setup_status}


def _raise_family_creation_error(error):
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


def _raise_family_creation_server_error(error):
    raise HTTPException(
        status_code=500,
        detail={
            "code": "SERVER_ERROR",
            "message": "לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.",
        },
    ) from error


def _raise_join_family_error(error):
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail(),
    ) from error


def _raise_join_family_server_error(error):
    raise HTTPException(
        status_code=500,
        detail={
            "code": "SERVER_ERROR",
            "message": "לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.",
        },
    ) from error


@app.post("/api/onboarding/create-family/address", status_code=200)
def resolve_family_address(
    request: CreateFamilyAddressRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        resolved = resolve_create_family_address(
            authenticated_user.auth_user_id,
            request.home_address,
        )
    except FamilyCreationError as error:
        _raise_family_creation_error(error)
    except Exception as error:
        _raise_family_creation_server_error(error)

    return {
        "normalized_address": resolved.normalized_address,
        "display_address": resolved.display_address,
        "resolution_token": resolved.resolution_token,
    }


@app.post("/api/onboarding/create-family", status_code=201)
def create_family(
    request: CreateFamilyRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return create_family_for_auth_user(
            auth_user_id=authenticated_user.auth_user_id,
            family_name=request.family_name,
            family_code=request.family_code,
            address_resolution_token=request.address_resolution_token,
            user_name=request.user_name,
        )
    except FamilyCreationError as error:
        _raise_family_creation_error(error)
    except Exception as error:
        _raise_family_creation_server_error(error)


@app.post("/api/onboarding/join-family/start", status_code=200)
def start_join(
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return start_join_family(authenticated_user.auth_user_id)
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/api/onboarding/join-family/family-name", status_code=200)
def join_family_name(
    request: JoinFamilyNameRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return submit_join_family_name(
            authenticated_user.auth_user_id,
            request.family_name,
        )
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/api/onboarding/join-family/address", status_code=200)
def join_family_address(
    request: JoinFamilyAddressRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return submit_join_family_address(
            authenticated_user.auth_user_id,
            request.home_address,
        )
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/api/onboarding/join-family/address-confirmation", status_code=200)
def join_family_address_confirmation(
    request: JoinFamilyAddressConfirmationRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return confirm_join_family_address(
            authenticated_user.auth_user_id,
            request.confirmed,
        )
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/api/onboarding/join-family/code", status_code=200)
def join_family_code(
    request: JoinFamilyCodeRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return submit_join_family_code(
            authenticated_user.auth_user_id,
            request.family_code,
        )
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/api/onboarding/join-family/complete", status_code=201)
def complete_join(
    request: JoinFamilyCompleteRequest,
    authenticated_user: AuthenticatedSupabaseUser = Depends(
        get_authenticated_supabase_user
    ),
):
    try:
        return complete_join_family(
            authenticated_user.auth_user_id,
            request.user_name,
        )
    except JoinFamilyError as error:
        _raise_join_family_error(error)
    except Exception as error:
        _raise_join_family_server_error(error)


@app.post("/car/connect")
def connect_car(connection: CarConnection):
    return connect_user(connection.shortcut_token)


@app.post("/car/disconnect")
def disconnect_car(connection: CarConnection):
    return disconnect_user(
        connection.shortcut_token,
        connection.latitude,
        connection.longitude,
    )
