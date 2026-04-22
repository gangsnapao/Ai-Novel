from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.utils import new_id
from app.models.character import Character
from app.models.project import Project
from app.models.project_settings import ProjectSettings
from app.models.structured_memory import MemoryEntity, RECOMMENDED_RELATION_TYPES
from app.models.worldbook_entry import WorldBookEntry
from app.schemas.characters_auto_update import CharactersAutoUpdateV1Request
from app.services.characters_auto_update_service import (
    CHARACTERS_AUTO_UPDATE_KIND,
    build_characters_auto_update_prompt_v1,
    _resolve_characters_llm_call,
)
from app.services.graph_auto_update_service import GRAPH_AUTO_UPDATE_KIND, _resolve_graph_llm_call
from app.services.import_ai_enrichment_service import ImportGraphProposal
from app.services.json_repair_service import repair_json_once
from app.services.llm_retry import (
    LlmRetryExhausted,
    call_llm_and_record_with_retries,
    task_llm_max_attempts,
    task_llm_retry_base_seconds,
    task_llm_retry_jitter,
    task_llm_retry_max_seconds,
)
from app.services.output_contracts import contract_for_task
from app.services.output_parsers import extract_json_value, likely_truncated_json
from app.services.worldbook_auto_update_service import (
    WORLDBOOK_AUTO_UPDATE_TASK,
    _build_existing_worldbook_entries_preview_for_prompt,
    _resolve_worldbook_llm_call,
    build_worldbook_auto_update_prompt_v1,
)

logger = logging.getLogger("ainovel")

_MAX_SOURCE_TEXT_CHARS = 40000
_MAX_EXISTING_NAMES = 200
_MAX_EXISTING_ENTITIES = 200


class GraphRelationsImportPreview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary_md: str | None = Field(default=None, max_length=40000)
    entities: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    relations: list[dict[str, Any]] = Field(default_factory=list, max_length=400)


def _truncate(text: str | None, *, limit: int) -> str:
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    return raw[:limit]


def _compact_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _run_json_object_prompt(
    *,
    request_id: str,
    actor_user_id: str,
    project_id: str,
    run_type: str,
    task_key: str,
    api_key: str,
    llm_call: object,
    prompt_system: str,
    prompt_user: str,
    repair_schema: str,
) -> dict[str, Any]:
    llm_attempts: list[dict[str, Any]] = []
    try:
        recorded, llm_attempts = call_llm_and_record_with_retries(
            logger=logger,
            request_id=request_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            run_type=run_type,
            api_key=api_key,
            prompt_system=prompt_system,
            prompt_user=prompt_user,
            llm_call=llm_call,
            max_attempts=task_llm_max_attempts(default=3),
            retry_prompt_system=prompt_system + "\n【重试模式】请输出更短、更保守、严格合法的裸 JSON，不要附带任何解释。",
            llm_call_overrides_by_attempt={2: {"max_tokens": 2400}, 3: {"max_tokens": 1600, "temperature": 0}},
            backoff_base_seconds=task_llm_retry_base_seconds(),
            backoff_max_seconds=task_llm_retry_max_seconds(),
            jitter=task_llm_retry_jitter(),
            run_params_extra_json={"task": task_key},
        )
    except LlmRetryExhausted as exc:
        return {
            "ok": False,
            "reason": "llm_call_failed",
            "error_type": exc.error_type,
            "error_message": exc.error_message,
            "run_id": exc.run_id,
            "attempts": list(exc.attempts or []),
        }

    warnings: list[str] = []
    if len(list(llm_attempts or [])) >= 2:
        warnings.append("llm_retry_used")

    value, raw_json = extract_json_value(recorded.text)
    repair_run_id: str | None = None
    if not isinstance(value, dict):
        if recorded.finish_reason == "length" or likely_truncated_json(recorded.text):
            warnings.append("output_truncated")
        repair_req = f"{request_id}:repair"
        if len(repair_req) > 64:
            repair_req = repair_req[:64]
        repair = repair_json_once(
            request_id=repair_req,
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            api_key=api_key,
            llm_call=llm_call,
            raw_output=recorded.text,
            schema=repair_schema,
            expected_root="object",
            origin_run_id=recorded.run_id,
            origin_task=task_key,
        )
        repair_run_id = str(repair.get("repair_run_id") or "").strip() or None
        warnings.extend(list(repair.get("warnings") or []))
        if not repair.get("ok"):
            return {
                "ok": False,
                "reason": "parse_failed",
                "run_id": recorded.run_id,
                "repair_run_id": repair_run_id,
                "warnings": warnings,
                "parse_error": repair.get("parse_error") or {"code": "AI_IMPORT_PARSE_ERROR", "message": "无法解析模型输出"},
                "attempts": llm_attempts,
            }
        value = repair.get("value")
        raw_json = repair.get("raw_json")

    return {
        "ok": True,
        "value": value,
        "raw_json": raw_json,
        "run_id": recorded.run_id,
        "repair_run_id": repair_run_id,
        "warnings": warnings,
        "attempts": llm_attempts,
        "finish_reason": recorded.finish_reason,
    }


def analyze_characters_import_text(
    *,
    db: Session,
    project_id: str,
    actor_user_id: str,
    request_id: str,
    source_text: str,
) -> dict[str, Any]:
    project = db.get(Project, str(project_id or "").strip())
    if project is None:
        return {"ok": False, "reason": "project_not_found"}

    existing_chars = [
        {"name": str(row.name or ""), "role": (str(row.role or "").strip() or None)}
        for row in db.execute(
            select(Character).where(Character.project_id == project_id).order_by(Character.updated_at.desc()).limit(_MAX_EXISTING_NAMES)
        )
        .scalars()
        .all()
        if str(row.name or "").strip()
    ]

    resolved = _resolve_characters_llm_call(db=db, project=project, actor_user_id=actor_user_id)
    if resolved is None:
        return {"ok": False, "reason": "llm_preset_missing"}
    llm_call, api_key = resolved

    system, user = build_characters_auto_update_prompt_v1(
        project_id=project_id,
        outline_md=None,
        chapter_content_md=_truncate(source_text, limit=_MAX_SOURCE_TEXT_CHARS),
        existing_characters=existing_chars,
    )

    out = _run_json_object_prompt(
        request_id=request_id,
        actor_user_id=actor_user_id,
        project_id=project_id,
        run_type="characters_ai_import_analyze",
        task_key=CHARACTERS_AUTO_UPDATE_KIND,
        api_key=api_key,
        llm_call=llm_call,
        prompt_system=system,
        prompt_user=user,
        repair_schema=(
            '{'
            '"schema_version":"characters_auto_update_v1",'
            '"title":"string|null",'
            '"summary_md":"string|null",'
            '"ops":[{"op":"upsert","name":"string","patch":{"role":"string|null","profile":"string|null","notes":"string|null"},"merge_mode_profile":"append_missing","merge_mode_notes":"append_missing","reason":"string|null"}]'
            '}'
        ),
    )
    if not out.get("ok"):
        return out

    try:
        preview = CharactersAutoUpdateV1Request.model_validate(out["value"])
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "schema_invalid",
            "run_id": out.get("run_id"),
            "repair_run_id": out.get("repair_run_id"),
            "warnings": out.get("warnings") or [],
            "validation_error": exc.errors(),
            "attempts": out.get("attempts") or [],
        }

    return {
        "ok": True,
        "run_id": out.get("run_id"),
        "repair_run_id": out.get("repair_run_id"),
        "warnings": out.get("warnings") or [],
        "attempts": out.get("attempts") or [],
        "preview": preview.model_dump(),
    }


def analyze_worldbook_import_text(
    *,
    db: Session,
    project_id: str,
    actor_user_id: str,
    request_id: str,
    source_text: str,
) -> dict[str, Any]:
    project = db.get(Project, str(project_id or "").strip())
    if project is None:
        return {"ok": False, "reason": "project_not_found"}

    settings_row = db.get(ProjectSettings, project_id)
    world_setting = str(getattr(settings_row, "world_setting", "") or "") if settings_row is not None else ""
    existing_titles = [
        str(row.title or "").strip()
        for row in db.execute(select(WorldBookEntry).where(WorldBookEntry.project_id == project_id).order_by(WorldBookEntry.updated_at.desc()))
        .scalars()
        .all()
        if str(row.title or "").strip()
    ]
    existing_preview_rows = db.execute(
        select(WorldBookEntry.title, WorldBookEntry.keywords_json, WorldBookEntry.content_md)
        .where(WorldBookEntry.project_id == project_id)
        .order_by(WorldBookEntry.updated_at.desc())
    ).all()

    resolved = _resolve_worldbook_llm_call(db=db, project=project, actor_user_id=actor_user_id)
    if resolved is None:
        return {"ok": False, "reason": "llm_preset_missing"}
    llm_call, api_key = resolved

    system, user = build_worldbook_auto_update_prompt_v1(
        project_id=project_id,
        world_setting=world_setting,
        chapter_summary_md=None,
        chapter_content_md=_truncate(source_text, limit=_MAX_SOURCE_TEXT_CHARS),
        outline_md=None,
        existing_worldbook_titles=existing_titles,
        existing_worldbook_entries_preview=_build_existing_worldbook_entries_preview_for_prompt(existing_preview_rows),
    )

    llm_attempts: list[dict[str, Any]] = []
    try:
        recorded, llm_attempts = call_llm_and_record_with_retries(
            logger=logger,
            request_id=request_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            run_type="worldbook_ai_import_analyze",
            api_key=api_key,
            prompt_system=system,
            prompt_user=user,
            llm_call=llm_call,
            max_attempts=task_llm_max_attempts(default=3),
            retry_prompt_system=system + "\n【重试模式】请仅保留最确定的设定条目，输出更短、更保守的裸 JSON。",
            llm_call_overrides_by_attempt={2: {"max_tokens": 2400}, 3: {"max_tokens": 1600, "temperature": 0}},
            backoff_base_seconds=task_llm_retry_base_seconds(),
            backoff_max_seconds=task_llm_retry_max_seconds(),
            jitter=task_llm_retry_jitter(),
            run_params_extra_json={"task": WORLDBOOK_AUTO_UPDATE_TASK},
        )
    except LlmRetryExhausted as exc:
        return {
            "ok": False,
            "reason": "llm_call_failed",
            "error_type": exc.error_type,
            "error_message": exc.error_message,
            "run_id": exc.run_id,
            "attempts": list(exc.attempts or []),
        }

    parsed = contract_for_task(WORLDBOOK_AUTO_UPDATE_TASK).parse(recorded.text or "", finish_reason=recorded.finish_reason)
    warnings = list(parsed.warnings or [])
    if len(list(llm_attempts or [])) >= 2:
        warnings.append("llm_retry_used")

    repair_run_id: str | None = None
    if parsed.parse_error is not None:
        repair_req = f"{request_id}:repair"
        if len(repair_req) > 64:
            repair_req = repair_req[:64]
        repair = repair_json_once(
            request_id=repair_req,
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            api_key=api_key,
            llm_call=llm_call,
            raw_output=recorded.text,
            schema=(
                "{\n"
                '  "schema_version": "worldbook_auto_update_v1",\n'
                '  "title": string | null,\n'
                '  "summary_md": string | null,\n'
                '  "ops": [\n'
                '    {\n'
                '      "op": "create" | "update" | "merge" | "dedupe",\n'
                '      "match_title": string,\n'
                '      "entry": {\n'
                '        "title": string,\n'
                '        "content_md": string,\n'
                '        "keywords": [string],\n'
                '        "aliases": [string],\n'
                '        "priority": string\n'
                "      },\n"
                '      "merge_mode": "append_missing" | "append" | "replace",\n'
                '      "canonical_title": string,\n'
                '      "duplicate_titles": [string],\n'
                '      "reason": string | null\n'
                "    }\n"
                "  ]\n"
                "}\n"
            ),
            expected_root="object",
            origin_run_id=recorded.run_id,
            origin_task=WORLDBOOK_AUTO_UPDATE_TASK,
        )
        repair_run_id = str(repair.get("repair_run_id") or "").strip() or None
        warnings.extend(list(repair.get("warnings") or []))
        if not repair.get("ok"):
            return {
                "ok": False,
                "reason": "parse_failed",
                "run_id": recorded.run_id,
                "repair_run_id": repair_run_id,
                "warnings": warnings,
                "parse_error": repair.get("parse_error") or parsed.parse_error,
                "attempts": llm_attempts,
            }
        repaired_text = str(repair.get("raw_json") or "").strip()
        parsed = contract_for_task(WORLDBOOK_AUTO_UPDATE_TASK).parse(
            repaired_text,
            finish_reason=str(repair.get("finish_reason") or "").strip() or None,
        )

    if parsed.parse_error is not None:
        return {
            "ok": False,
            "reason": "parse_failed",
            "run_id": recorded.run_id,
            "repair_run_id": repair_run_id,
            "warnings": warnings,
            "parse_error": parsed.parse_error,
            "attempts": llm_attempts,
        }

    return {
        "ok": True,
        "run_id": recorded.run_id,
        "repair_run_id": repair_run_id,
        "warnings": warnings,
        "attempts": llm_attempts,
        "preview": {
            "schema_version": "worldbook_auto_update_v1",
            "title": parsed.data.get("title"),
            "summary_md": parsed.data.get("summary_md"),
            "ops": list(parsed.data.get("ops") or []),
        },
    }


def build_graph_relations_import_prompt(
    *,
    project_id: str,
    source_text: str,
    existing_entities: list[dict[str, str]],
) -> tuple[str, str]:
    system = (
        "你是小说项目人物关系导入助手。你的任务是把用户粘贴的设定文本整理为人物图谱关系草案。\n"
        "你必须只输出一个 JSON object；不要输出解释、不要 Markdown 代码块、不要额外文字。\n"
        "输出格式固定为：\n"
        "{\n"
        '  "summary_md": "可选总结",\n'
        '  "entities": [\n'
        '    {"entity_type":"character","name":"人物名","summary_md":"可选","attributes":{}}\n'
        "  ],\n"
        '  "relations": [\n'
        '    {"from_entity_name":"甲","to_entity_name":"乙","relation_type":"friend","description_md":"可选","attributes":{}}\n'
        "  ]\n"
        "}\n"
        "严格规则：\n"
        "- 只抽取人物实体与人物之间的明确关系；不要输出地点/组织/道具。\n"
        "- entity_type 固定优先使用 character。\n"
        f"- relation_type 优先使用这些值：{', '.join(RECOMMENDED_RELATION_TYPES)}。\n"
        "- 信息不足时宁可少写，不要编造。\n"
        "- 尽量复用 existing_entities 中已有人物名称，避免重复创建同名变体。\n"
        "- 若同一段文本表达了多层关系，只保留最稳定、最明确的那几条。\n"
    )
    user = (
        f"project_id: {project_id}\n\n"
        "=== existing_character_entities ===\n"
        f"{_compact_json_dumps(existing_entities)}\n\n"
        "=== source_text ===\n"
        f"{_truncate(source_text, limit=_MAX_SOURCE_TEXT_CHARS)}\n"
    )
    return system, user


def analyze_graph_relations_import_text(
    *,
    db: Session,
    project_id: str,
    actor_user_id: str,
    request_id: str,
    source_text: str,
) -> dict[str, Any]:
    project = db.get(Project, str(project_id or "").strip())
    if project is None:
        return {"ok": False, "reason": "project_not_found"}

    existing_entities = [
        {"name": str(row.name or "").strip(), "entity_type": str(row.entity_type or "character").strip() or "character"}
        for row in db.execute(
            select(MemoryEntity)
            .where(MemoryEntity.project_id == project_id, MemoryEntity.deleted_at.is_(None), MemoryEntity.entity_type == "character")
            .order_by(MemoryEntity.updated_at.desc())
            .limit(_MAX_EXISTING_ENTITIES)
        )
        .scalars()
        .all()
        if str(row.name or "").strip()
    ]

    if not existing_entities:
        existing_entities = [
            {"name": str(row.name or "").strip(), "entity_type": "character"}
            for row in db.execute(
                select(Character).where(Character.project_id == project_id).order_by(Character.updated_at.desc()).limit(_MAX_EXISTING_ENTITIES)
            )
            .scalars()
            .all()
            if str(row.name or "").strip()
        ]

    resolved = _resolve_graph_llm_call(db=db, project=project, actor_user_id=actor_user_id)
    if resolved is None:
        return {"ok": False, "reason": "llm_preset_missing"}
    llm_call, api_key = resolved

    system, user = build_graph_relations_import_prompt(
        project_id=project_id,
        source_text=source_text,
        existing_entities=existing_entities,
    )

    out = _run_json_object_prompt(
        request_id=request_id,
        actor_user_id=actor_user_id,
        project_id=project_id,
        run_type="graph_relations_ai_import_analyze",
        task_key=GRAPH_AUTO_UPDATE_KIND,
        api_key=api_key,
        llm_call=llm_call,
        prompt_system=system,
        prompt_user=user,
        repair_schema=(
            '{"summary_md":"string|null","entities":[{"entity_type":"character","name":"string","summary_md":"string|null","attributes":{}}],"relations":[{"from_entity_name":"string","to_entity_name":"string","relation_type":"related_to","description_md":"string|null","attributes":{}}]}'
        ),
    )
    if not out.get("ok"):
        return out

    try:
        base = out["value"] if isinstance(out["value"], dict) else {}
        preview = GraphRelationsImportPreview.model_validate(base)
        graph_payload = ImportGraphProposal.model_validate(
            {"entities": preview.entities, "relations": preview.relations},
        )
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "schema_invalid",
            "run_id": out.get("run_id"),
            "repair_run_id": out.get("repair_run_id"),
            "warnings": out.get("warnings") or [],
            "validation_error": exc.errors(),
            "attempts": out.get("attempts") or [],
        }

    return {
        "ok": True,
        "run_id": out.get("run_id"),
        "repair_run_id": out.get("repair_run_id"),
        "warnings": out.get("warnings") or [],
        "attempts": out.get("attempts") or [],
        "preview": {
            "summary_md": preview.summary_md,
            "entities": graph_payload.model_dump().get("entities", []),
            "relations": graph_payload.model_dump().get("relations", []),
        },
    }
