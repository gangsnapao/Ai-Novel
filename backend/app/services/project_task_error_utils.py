from __future__ import annotations

import json
from typing import Any

from app.core.secrets import redact_api_keys


def compact_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compact_json_loads(value: str | None) -> Any | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def normalize_user_visible_errors(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip() or None
        message = str(item.get("message") or "").strip() or None
        detail = str(item.get("detail") or "").strip() or None
        severity = str(item.get("severity") or "").strip().lower() or "error"
        code = str(item.get("code") or "").strip() or None
        request_id = str(item.get("request_id") or "").strip() or None
        action = item.get("action")
        action_dict = redact_api_keys(action) if isinstance(action, dict) else None
        if not any((title, message, detail, code, action_dict)):
            continue
        out.append(
            {
                "title": title,
                "message": message,
                "detail": detail,
                "severity": severity,
                "code": code,
                "request_id": request_id,
                "action": action_dict,
            }
        )
    return out


def derive_user_visible_errors(error_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(error_payload, dict):
        return []

    embedded = normalize_user_visible_errors(error_payload.get("user_visible_errors"))
    if embedded:
        return embedded

    details = error_payload.get("details")
    if isinstance(details, dict):
        detail_embedded = normalize_user_visible_errors(details.get("user_visible_errors"))
        if detail_embedded:
            return detail_embedded

    title = (
        str(error_payload.get("friendly_title") or "").strip()
        or str(error_payload.get("code") or "").strip()
        or str(error_payload.get("error_type") or "").strip()
        or "任务失败"
    )
    message = str(error_payload.get("friendly_message") or "").strip() or str(error_payload.get("message") or "").strip() or None
    if not message:
        return []

    detail = None
    if isinstance(details, dict):
        how_to_fix = details.get("how_to_fix")
        if isinstance(how_to_fix, list):
            detail = "\n".join(str(item).strip() for item in how_to_fix if str(item).strip()) or None
        elif isinstance(how_to_fix, str) and how_to_fix.strip():
            detail = how_to_fix.strip()

    request_id = None
    if isinstance(details, dict):
        request_id = str(details.get("request_id") or "").strip() or None

    return [
        {
            "title": title,
            "message": message,
            "detail": detail,
            "severity": "error",
            "code": str(error_payload.get("code") or "").strip() or None,
            "request_id": request_id,
            "action": None,
        }
    ]


def project_task_error_fields(
    error_json: str | None,
    user_visible_errors_json: str | None = None,
) -> tuple[str | None, str | None, list[dict[str, Any]], Any | None]:
    error_payload = compact_json_loads(error_json) if error_json else None
    error_type = None
    error_message = None
    if isinstance(error_payload, dict):
        error_type = str(error_payload.get("error_type") or "").strip() or None
        error_message = str(error_payload.get("message") or "").strip() or None

    explicit_user_visible = normalize_user_visible_errors(compact_json_loads(user_visible_errors_json) if user_visible_errors_json else None)
    user_visible_errors = explicit_user_visible or derive_user_visible_errors(error_payload)
    return error_type, error_message, user_visible_errors, error_payload
