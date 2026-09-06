import json
import logging
import os
from urllib.parse import urlparse

from database import (
    PushSubscriptionOwnershipError,
    get_family_push_subscriptions,
    remove_dead_push_subscription,
    remove_push_subscription,
    upsert_push_subscription,
)
from identity import CurrentUser


logger = logging.getLogger(__name__)


class PushServiceError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _enabled():
    return os.getenv("WEB_PUSH_ENABLED", "").strip().lower() == "true"


def _config():
    if not _enabled():
        return None
    public_key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    subject = os.getenv("VAPID_SUBJECT", "").strip()
    if not public_key or not private_key or not subject:
        raise PushServiceError(
            "PUSH_CONFIGURATION_INVALID",
            "Web Push is not configured",
            503,
        )
    parsed_subject = urlparse(subject)
    valid_subject = (
        (parsed_subject.scheme == "mailto" and bool(parsed_subject.path))
        or (parsed_subject.scheme == "https" and bool(parsed_subject.netloc))
    )
    if not valid_subject:
        raise PushServiceError(
            "PUSH_CONFIGURATION_INVALID",
            "Web Push is not configured",
            503,
        )
    return {
        "public_key": public_key,
        "private_key": private_key,
        "subject": subject,
    }


def get_public_push_config(current_user: CurrentUser):
    _require_family(current_user)
    if not _enabled():
        return {"enabled": False, "public_vapid_key": None}
    config = _config()
    return {"enabled": True, "public_vapid_key": config["public_key"]}


def register_push_subscription(current_user: CurrentUser, subscription):
    _require_family(current_user)
    if not _enabled():
        raise PushServiceError("PUSH_DISABLED", "Web Push is disabled", 503)
    _config()
    try:
        upsert_push_subscription(
            current_user.user_id,
            subscription.endpoint,
            subscription.keys.p256dh,
            subscription.keys.auth,
            subscription.expiration_time,
        )
    except PushSubscriptionOwnershipError as error:
        raise PushServiceError(
            "PUSH_SUBSCRIPTION_OWNED_BY_ANOTHER_USER",
            "This push subscription cannot be registered",
            409,
        ) from error
    return {"registered": True}


def unregister_push_subscription(current_user: CurrentUser, endpoint):
    _require_family(current_user)
    remove_push_subscription(current_user.user_id, endpoint)
    return {"removed": True}


def _require_family(current_user):
    if current_user.family_id is None:
        raise PushServiceError(
            "USER_WITHOUT_FAMILY",
            "The mapped user does not belong to a family",
            403,
        )


def _webpush(subscription_info, payload, config):
    from pywebpush import webpush

    return webpush(
        subscription_info=subscription_info,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=config["private_key"],
        vapid_claims={"sub": config["subject"]},
        ttl=300,
        timeout=5,
    )


def _response_status(error):
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def dispatch_car_transition_notification(
    *,
    family_id,
    actor_user_id,
    event_id,
    transition,
    actor_name,
):
    if not _enabled():
        return
    try:
        config = _config()
    except PushServiceError:
        logger.error(
            "operation=push_dispatch event_type=%s car_event_id=%s status=config_error",
            transition,
            event_id,
        )
        return

    body = (
        f"{actor_name} לקח את הרכב"
        if transition == "connected"
        else "הרכב התפנה"
    )
    payload = {
        "title": "Family Car Agent",
        "body": body,
        "url": "/",
        "tag": f"car-event-{event_id}",
    }
    try:
        subscriptions = get_family_push_subscriptions(family_id, actor_user_id)
    except Exception:
        logger.error(
            "operation=push_dispatch event_type=%s car_event_id=%s status=subscription_lookup_failed",
            transition,
            event_id,
        )
        return
    delivered = 0
    failed = 0
    removed = 0
    for subscription in subscriptions:
        try:
            _webpush(
                {
                    "endpoint": subscription["endpoint"],
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth"],
                    },
                },
                payload,
                config,
            )
            delivered += 1
        except Exception as error:
            failed += 1
            status = _response_status(error)
            if status in {404, 410}:
                try:
                    remove_dead_push_subscription(subscription)
                    removed += 1
                except Exception:
                    logger.warning(
                        "operation=push_cleanup event_type=%s car_event_id=%s status=cleanup_failed",
                        transition,
                        event_id,
                    )

    logger.info(
        "operation=push_dispatch event_type=%s car_event_id=%s delivered=%s failed=%s removed=%s",
        transition,
        event_id,
        delivered,
        failed,
        removed,
    )
