from __future__ import annotations

import json
from datetime import datetime

from app.models.character import Character


def _compact_json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _compact_json_loads(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def normalize_text_list(values: list[str] | None, *, max_items: int = 50, max_chars: int = 500) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[:max_chars].strip()
        marker = text.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def parse_text_list_json(raw: str | None) -> list[str]:
    value = _compact_json_loads(raw)
    if not isinstance(value, list):
        return []
    return normalize_text_list([str(item) for item in value])


def parse_profile_history_json(raw: str | None) -> list[dict[str, object]]:
    value = _compact_json_loads(raw)
    if not isinstance(value, list):
        return []
    out: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        profile = str(item.get("profile") or "").strip()
        if not profile:
            continue
        version_raw = item.get("version")
        version = int(version_raw) if isinstance(version_raw, int) else None
        captured_at = str(item.get("captured_at") or "").strip() or None
        out.append(
            {
                "version": version if version and version > 0 else None,
                "profile": profile,
                "captured_at": captured_at,
            }
        )
    return out[-20:]


def dump_text_list_json(values: list[str] | None) -> str | None:
    normalized = normalize_text_list(values)
    if not normalized:
        return None
    return _compact_json_dumps(normalized)


def dump_profile_history_json(values: list[dict[str, object]] | None) -> str | None:
    normalized = parse_profile_history_json(_compact_json_dumps(values or []))
    if not normalized:
        return None
    return _compact_json_dumps(normalized)


def current_profile_version(row: Character) -> int:
    value = getattr(row, "profile_version", None)
    if isinstance(value, int) and value > 0:
        return value
    return 1 if str(getattr(row, "profile", "") or "").strip() else 0


def apply_profile_update(
    *,
    row: Character,
    next_profile: str | None,
    explicit_version: int | None = None,
    captured_at: datetime | None = None,
) -> None:
    current_profile = str(getattr(row, "profile", "") or "").strip() or None
    next_value = str(next_profile or "").strip() or None
    explicit = int(explicit_version) if isinstance(explicit_version, int) and explicit_version > 0 else None

    if current_profile == next_value:
        if explicit is not None:
            row.profile_version = explicit
        elif next_value and not isinstance(getattr(row, "profile_version", None), int):
            row.profile_version = 1
        elif not next_value and explicit is None:
            row.profile_version = 0
        return

    history = parse_profile_history_json(getattr(row, "profile_history_json", None))
    current_version = current_profile_version(row)
    if current_profile:
        history.append(
            {
                "version": current_version if current_version > 0 else None,
                "profile": current_profile,
                "captured_at": (captured_at or datetime.utcnow()).isoformat() + "Z",
            }
        )

    row.profile = next_value
    row.profile_history_json = _compact_json_dumps(history[-20:]) if history else None
    if next_value:
        row.profile_version = explicit or max(current_version + 1, 1)
    else:
        row.profile_version = explicit or 0
