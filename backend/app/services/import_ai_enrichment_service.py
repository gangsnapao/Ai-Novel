from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.utils import new_id, utc_now
from app.models.character import Character
from app.models.llm_preset import LLMPreset
from app.models.project import Project
from app.models.project_settings import ProjectSettings
from app.models.project_source_document import ProjectSourceDocument
from app.models.story_memory import StoryMemory
from app.models.structured_memory import MemoryEntity, MemoryRelation
from app.models.worldbook_entry import WorldBookEntry
from app.schemas.characters_auto_update import CharactersAutoUpdateV1Request
from app.schemas.worldbook import WorldBookImportAllRequest
from app.api.routes.memory import StoryMemoryImportV1Request
from app.services.characters_auto_update_service import apply_characters_auto_update_ops
from app.services.generation_service import prepare_llm_call
from app.services.json_repair_service import repair_json_once
from app.services.llm_key_resolver import resolve_api_key_for_project
from app.services.llm_retry import (
    LlmRetryExhausted,
    call_llm_and_record_with_retries,
    task_llm_max_attempts,
    task_llm_retry_base_seconds,
    task_llm_retry_jitter,
    task_llm_retry_max_seconds,
)
from app.services.llm_task_preset_resolver import resolve_task_llm_config
from app.services.output_parsers import extract_json_value, likely_truncated_json
from app.services.search_index_service import schedule_search_rebuild_task
from app.services.vector_rag_service import schedule_vector_rebuild_task

logger = logging.getLogger("ainovel")

IMPORT_STRUCTURED_INGEST_TASK_KEY = "import_structured_ingest"
IMPORT_STRUCTURED_INGEST_SCHEMA_VERSION = "import_structured_ingest_v1"

_MAX_DOC_CHARS = 40000
_MAX_EXISTING_ITEMS = 120


class ImportGraphEntityProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str = Field(default="generic", max_length=64)
    name: str = Field(min_length=1, max_length=255)
    summary_md: str | None = Field(default=None, max_length=40000)
    attributes: dict[str, Any] | None = None


class ImportGraphRelationProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_entity_name: str = Field(min_length=1, max_length=255)
    to_entity_name: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(default="related_to", max_length=64)
    description_md: str | None = Field(default=None, max_length=40000)
    attributes: dict[str, Any] | None = None


class ImportGraphProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entities: list[ImportGraphEntityProposal] = Field(default_factory=list, max_length=200)
    relations: list[ImportGraphRelationProposal] = Field(default_factory=list, max_length=400)


class ImportStructuredIngestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(default=IMPORT_STRUCTURED_INGEST_SCHEMA_VERSION, max_length=64)
    summary_md: str | None = Field(default=None, max_length=40000)
    worldbook: dict[str, Any] = Field(default_factory=dict)
    story_memory: dict[str, Any] = Field(default_factory=dict)
    characters: dict[str, Any] = Field(default_factory=dict)
    graph: dict[str, Any] = Field(default_factory=dict)


def _compact_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def _truncate(value: str | None, *, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit]


def _resolve_import_llm_call(
    *,
    db: Session,
    project: Project,
    actor_user_id: str,
) -> tuple[object, str] | None:
    missing_key_exc: AppError | None = None
    try:
        resolved = resolve_task_llm_config(
            db,
            project=project,
            user_id=actor_user_id,
            task_key=IMPORT_STRUCTURED_INGEST_TASK_KEY,
            header_api_key=None,
        )
    except OperationalError:
        resolved = None
    except AppError as exc:
        if str(exc.code or "") != "LLM_KEY_MISSING":
            raise
        missing_key_exc = exc
        resolved = None

    if resolved is not None:
        return resolved.llm_call, str(resolved.api_key)

    preset = db.get(LLMPreset, project.id)
    if preset is None:
        if missing_key_exc is not None:
            raise missing_key_exc
        return None
    api_key = resolve_api_key_for_project(db, project=project, user_id=actor_user_id, header_api_key=None)
    return prepare_llm_call(preset), str(api_key)


def build_import_structured_ingest_prompt(
    *,
    project: Project,
    document: ProjectSourceDocument,
    import_requirements: str | None,
    existing_characters: list[dict[str, str | None]],
    existing_worldbook_titles: list[str],
    existing_entities: list[dict[str, str]],
) -> tuple[str, str]:
    requirements = (import_requirements or "").strip()
    doc_text = _truncate(document.content_text or "", limit=_MAX_DOC_CHARS)

    system = (
        "你是小说项目知识导入助手。你的任务是把用户上传的设定/资料文档整理为可直接入库的数据。\n"
        "你必须只输出一个 JSON object；不要输出解释、不要 Markdown 代码块、不要额外文字。\n"
        f"schema_version 必须是 {json.dumps(IMPORT_STRUCTURED_INGEST_SCHEMA_VERSION, ensure_ascii=False)}。\n"
        "输出顶层字段固定为：schema_version, summary_md, worldbook, story_memory, characters, graph。\n"
        "其中：\n"
        "- worldbook 必须兼容 worldbook_export_all_v1，字段为 schema_version + entries。\n"
        "- story_memory 必须兼容 story_memory_import_v1，字段为 schema_version + memories。\n"
        "- characters 必须兼容 characters_auto_update_v1，字段为 schema_version + ops。\n"
        "- graph 只允许输出 entities / relations 两个数组。\n"
        "\n"
        "严格规则：\n"
        "- 优先服从 import_requirements 中的整理要求、字段倾向、详细程度与写作约束。\n"
        "- 只抽取文档中明确存在、适合长期复用的设定；不要编造。\n"
        "- 角色卡重在人物身份、目标、性格、关系、关键设定；避免整段照抄原文。\n"
        "- 世界书重在稳定设定、组织、地点、规则、道具、术语、时间线节点。\n"
        "- story_memory 只保留适合检索/提醒的高价值摘要。\n"
        "- graph 重点抽取实体与明确关系；若关系不确定，宁可少写。\n"
        "- 尽量复用 existing_characters / existing_entities / existing_worldbook_titles，避免重复创建。\n"
        "- 若 import_requirements 指定“只导入人物/地点/阵营/禁忌/世界观”等，必须遵守。\n"
        "\n"
        "graph.relations 字段固定为：from_entity_name, to_entity_name, relation_type, description_md, attributes。\n"
        "graph.entities 字段固定为：entity_type, name, summary_md, attributes。\n"
        "worldbook.entries[].keywords 需要尽量提供便于检索的关键词。\n"
        "characters.ops 建议优先输出 upsert，默认 merge_mode_profile / merge_mode_notes 使用 append_missing。\n"
    )

    user = (
        f"project_id: {str(project.id or '').strip()}\n"
        f"project_name: {str(project.name or '').strip()}\n"
        f"project_genre: {str(project.genre or '').strip()}\n"
        f"project_logline: {str(project.logline or '').strip()}\n\n"
        "=== import_requirements ===\n"
        f"{requirements or '（无额外要求；请按通用小说设定整理）'}\n\n"
        "=== existing_characters ===\n"
        f"{json.dumps(existing_characters[:_MAX_EXISTING_ITEMS], ensure_ascii=False)}\n\n"
        "=== existing_worldbook_titles ===\n"
        f"{json.dumps(existing_worldbook_titles[:_MAX_EXISTING_ITEMS], ensure_ascii=False)}\n\n"
        "=== existing_graph_entities ===\n"
        f"{json.dumps(existing_entities[:_MAX_EXISTING_ITEMS], ensure_ascii=False)}\n\n"
        "=== import_document_meta ===\n"
        f"{json.dumps({'filename': document.filename, 'content_type': document.content_type}, ensure_ascii=False)}\n\n"
        "=== import_document_content ===\n"
        f"{doc_text}\n"
    )
    return system, user


def _merge_attributes(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any] | None:
    old_obj = old if isinstance(old, dict) else {}
    new_obj = new if isinstance(new, dict) else {}
    if not old_obj and not new_obj:
        return None

    merged: dict[str, Any] = dict(old_obj)
    for key, value in new_obj.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
            continue
        if isinstance(merged[key], list) and isinstance(value, list):
            seen: set[str] = set()
            out: list[Any] = []
            for item in [*merged[key], *value]:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                out.append(item)
            merged[key] = out
    return merged or None


def _safe_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def apply_import_worldbook_entries(
    *,
    db: Session,
    project_id: str,
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    rows = (
        db.execute(select(WorldBookEntry).where(WorldBookEntry.project_id == project_id).order_by(WorldBookEntry.updated_at.desc()))
        .scalars()
        .all()
    )
    by_title: dict[str, list[WorldBookEntry]] = {}
    for row in rows:
        by_title.setdefault(str(row.title or "").strip(), []).append(row)

    created = 0
    updated = 0
    skipped = 0
    for item in entries:
        title = str(item.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        matches = by_title.get(title) or []
        keywords = [str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()]
        keywords_json = json.dumps(keywords, ensure_ascii=False)
        if len(matches) > 1:
            skipped += 1
            continue
        if not matches:
            row = WorldBookEntry(
                id=new_id(),
                project_id=project_id,
                title=title[:255],
                content_md=str(item.get("content_md") or ""),
                enabled=bool(item.get("enabled", True)),
                constant=bool(item.get("constant", False)),
                keywords_json=keywords_json,
                exclude_recursion=bool(item.get("exclude_recursion", False)),
                prevent_recursion=bool(item.get("prevent_recursion", False)),
                char_limit=int(item.get("char_limit") or 12000),
                priority=str(item.get("priority") or "important")[:32] or "important",
            )
            db.add(row)
            by_title[title] = [row]
            created += 1
            continue

        row = matches[0]
        row.content_md = str(item.get("content_md") or "")
        row.enabled = bool(item.get("enabled", True))
        row.constant = bool(item.get("constant", False))
        row.keywords_json = keywords_json
        row.exclude_recursion = bool(item.get("exclude_recursion", False))
        row.prevent_recursion = bool(item.get("prevent_recursion", False))
        row.char_limit = int(item.get("char_limit") or 12000)
        row.priority = str(item.get("priority") or "important")[:32] or "important"
        updated += 1

    return {"created": created, "updated": updated, "skipped": skipped}


def apply_import_story_memories(
    *,
    db: Session,
    project_id: str,
    memories: list[dict[str, Any]],
) -> dict[str, int]:
    rows = (
        db.execute(select(StoryMemory).where(StoryMemory.project_id == project_id).order_by(StoryMemory.updated_at.desc()))
        .scalars()
        .all()
    )
    existing_keys = {
        (
            str(row.memory_type or "").strip(),
            str(row.title or "").strip(),
            str(row.content or "").strip(),
        )
        for row in rows
    }

    created = 0
    skipped = 0
    now = utc_now()
    for item in memories:
        memory_type = str(item.get("memory_type") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not memory_type or not content:
            skipped += 1
            continue
        key = (memory_type, title, content)
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        db.add(
            StoryMemory(
                id=new_id(),
                project_id=project_id,
                chapter_id=None,
                memory_type=memory_type[:64],
                title=title[:255] or None,
                content=content,
                full_context_md=None,
                importance_score=float(item.get("importance_score") or 0.0),
                tags_json=None,
                story_timeline=int(item.get("story_timeline") or 0),
                text_position=-1,
                text_length=0,
                is_foreshadow=int(item.get("is_foreshadow") or 0),
                foreshadow_resolved_at_chapter_id=None,
                metadata_json=json.dumps({"source": "import_ai_enrichment"}, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
        )
        created += 1
    return {"created": created, "skipped": skipped}


def apply_import_graph_payload(
    *,
    db: Session,
    project_id: str,
    graph: ImportGraphProposal,
) -> dict[str, int]:
    entity_rows = (
        db.execute(
            select(MemoryEntity)
            .where(MemoryEntity.project_id == project_id, MemoryEntity.deleted_at.is_(None))
            .order_by(MemoryEntity.updated_at.desc(), MemoryEntity.id.desc())
        )
        .scalars()
        .all()
    )
    entity_by_name: dict[str, MemoryEntity] = {}
    for row in entity_rows:
        key = _normalize_name(row.name)
        if key and key not in entity_by_name:
            entity_by_name[key] = row

    relation_rows = (
        db.execute(
            select(MemoryRelation)
            .where(MemoryRelation.project_id == project_id, MemoryRelation.deleted_at.is_(None))
            .order_by(MemoryRelation.updated_at.desc(), MemoryRelation.id.desc())
        )
        .scalars()
        .all()
    )
    relation_by_key = {
        (str(row.from_entity_id), str(row.to_entity_id), str(row.relation_type or "").strip().lower()): row for row in relation_rows
    }

    created_entities = 0
    updated_entities = 0
    created_relations = 0
    updated_relations = 0
    skipped = 0

    def ensure_entity(name: str, *, entity_type: str = "generic", summary_md: str | None = None, attributes: dict[str, Any] | None = None) -> MemoryEntity:
        nonlocal created_entities, updated_entities
        key = _normalize_name(name)
        row = entity_by_name.get(key)
        if row is None:
            row = MemoryEntity(
                id=new_id(),
                project_id=project_id,
                entity_type=(entity_type or "generic")[:64] or "generic",
                name=name[:255],
                summary_md=(summary_md or "").strip() or None,
                attributes_json=_compact_json_dumps(attributes) if isinstance(attributes, dict) and attributes else None,
                deleted_at=None,
            )
            db.add(row)
            entity_by_name[key] = row
            created_entities += 1
            return row

        changed = False
        if str(row.entity_type or "").strip().lower() == "generic" and str(entity_type or "").strip():
            row.entity_type = str(entity_type)[:64]
            changed = True
        if summary_md and not str(row.summary_md or "").strip():
            row.summary_md = summary_md
            changed = True
        merged_attrs = _merge_attributes(_safe_json_dict(row.attributes_json), attributes)
        if merged_attrs is not None and _compact_json_dumps(merged_attrs) != _compact_json_dumps(_safe_json_dict(row.attributes_json)):
            row.attributes_json = _compact_json_dumps(merged_attrs)
            changed = True
        if changed:
            updated_entities += 1
        return row

    for entity in graph.entities:
        name = str(entity.name or "").strip()
        if not name:
            skipped += 1
            continue
        ensure_entity(
            name,
            entity_type=str(entity.entity_type or "generic"),
            summary_md=(entity.summary_md or "").strip() or None,
            attributes=entity.attributes if isinstance(entity.attributes, dict) else None,
        )

    for relation in graph.relations:
        from_name = str(relation.from_entity_name or "").strip()
        to_name = str(relation.to_entity_name or "").strip()
        relation_type = str(relation.relation_type or "related_to").strip().lower() or "related_to"
        if not from_name or not to_name:
            skipped += 1
            continue
        from_row = ensure_entity(from_name)
        to_row = ensure_entity(to_name)
        key = (str(from_row.id), str(to_row.id), relation_type)
        row = relation_by_key.get(key)
        if row is None:
            row = MemoryRelation(
                id=new_id(),
                project_id=project_id,
                from_entity_id=str(from_row.id),
                to_entity_id=str(to_row.id),
                relation_type=relation_type[:64],
                description_md=(relation.description_md or "").strip() or None,
                attributes_json=_compact_json_dumps(relation.attributes) if isinstance(relation.attributes, dict) and relation.attributes else None,
                deleted_at=None,
            )
            db.add(row)
            relation_by_key[key] = row
            created_relations += 1
            continue

        changed = False
        if relation.description_md and not str(row.description_md or "").strip():
            row.description_md = relation.description_md
            changed = True
        merged_attrs = _merge_attributes(_safe_json_dict(row.attributes_json), relation.attributes if isinstance(relation.attributes, dict) else None)
        if merged_attrs is not None and _compact_json_dumps(merged_attrs) != _compact_json_dumps(_safe_json_dict(row.attributes_json)):
            row.attributes_json = _compact_json_dumps(merged_attrs)
            changed = True
        if changed:
            updated_relations += 1

    return {
        "created_entities": created_entities,
        "updated_entities": updated_entities,
        "created_relations": created_relations,
        "updated_relations": updated_relations,
        "skipped": skipped,
    }


def enrich_import_document_and_apply(
    *,
    db: Session,
    project_id: str,
    document_id: str,
    actor_user_id: str,
    request_id: str,
    import_requirements: str | None,
    apply_worldbook: bool = True,
    apply_story_memory: bool = True,
    apply_characters: bool = True,
    apply_graph: bool = True,
) -> dict[str, Any]:
    project = db.get(Project, str(project_id or "").strip())
    if project is None:
        return {"ok": False, "reason": "project_not_found"}

    document = db.get(ProjectSourceDocument, str(document_id or "").strip())
    if document is None or str(document.project_id) != str(project_id):
        return {"ok": False, "reason": "document_not_found"}
    if str(document.status or "").strip().lower() != "done":
        return {"ok": False, "reason": "document_not_ready"}

    existing_characters = [
        {"name": str(row.name or ""), "role": str(row.role or "").strip() or None}
        for row in db.execute(select(Character).where(Character.project_id == project_id).order_by(Character.updated_at.desc())).scalars().all()
        if str(row.name or "").strip()
    ]
    existing_worldbook_titles = [
        str(row.title or "").strip()
        for row in db.execute(select(WorldBookEntry.title).where(WorldBookEntry.project_id == project_id)).scalars().all()
        if str(row or "").strip()
    ]
    existing_entities = [
        {
            "name": str(row.name or "").strip(),
            "entity_type": str(row.entity_type or "generic").strip() or "generic",
        }
        for row in db.execute(
            select(MemoryEntity)
            .where(MemoryEntity.project_id == project_id, MemoryEntity.deleted_at.is_(None))
            .order_by(MemoryEntity.updated_at.desc())
        ).scalars().all()
        if str(row.name or "").strip()
    ]

    resolved = _resolve_import_llm_call(db=db, project=project, actor_user_id=actor_user_id)
    if resolved is None:
        return {"ok": False, "reason": "llm_preset_missing"}
    llm_call, api_key = resolved

    prompt_system, prompt_user = build_import_structured_ingest_prompt(
        project=project,
        document=document,
        import_requirements=import_requirements,
        existing_characters=existing_characters,
        existing_worldbook_titles=existing_worldbook_titles,
        existing_entities=existing_entities,
    )

    retry_system = (
        prompt_system
        + "\n【重试模式】请输出更短、更保守的 JSON：只保留最确定、最适合长期入库的设定；不要输出空字段。"
    )

    try:
        recorded, attempts = call_llm_and_record_with_retries(
            logger=logger,
            request_id=request_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            run_type="import_structured_ingest",
            api_key=api_key,
            prompt_system=prompt_system,
            prompt_user=prompt_user,
            llm_call=llm_call,
            max_attempts=task_llm_max_attempts(default=3),
            retry_prompt_system=retry_system,
            backoff_base_seconds=task_llm_retry_base_seconds(),
            backoff_max_seconds=task_llm_retry_max_seconds(),
            jitter=task_llm_retry_jitter(),
            llm_call_overrides_by_attempt={2: {"max_tokens": 3200}, 3: {"max_tokens": 2400}},
            run_params_extra_json={
                "task": IMPORT_STRUCTURED_INGEST_TASK_KEY,
                "document_id": document.id,
                "filename": document.filename,
            },
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

    value, raw_json = extract_json_value(recorded.text)
    repaired_run_id: str | None = None
    warnings: list[str] = []
    if not isinstance(value, dict):
        if likely_truncated_json(recorded.text):
            warnings.append("output_truncated")
        repair = repair_json_once(
            request_id=f"{request_id}:repair",
            actor_user_id=actor_user_id,
            project_id=project_id,
            chapter_id=None,
            api_key=api_key,
            llm_call=llm_call,
            raw_output=recorded.text,
            schema=(
                '{"schema_version":"import_structured_ingest_v1","summary_md":"string|null","worldbook":{"schema_version":"worldbook_export_all_v1","entries":[]},"story_memory":{"schema_version":"story_memory_import_v1","memories":[]},"characters":{"schema_version":"characters_auto_update_v1","ops":[]},"graph":{"entities":[],"relations":[]}}'
            ),
            expected_root="object",
            origin_run_id=recorded.run_id,
            origin_task="import_structured_ingest",
        )
        if not repair.get("ok"):
            return {
                "ok": False,
                "reason": "parse_failed",
                "run_id": recorded.run_id,
                "repair_run_id": repair.get("repair_run_id"),
                "warnings": warnings + list(repair.get("warnings") or []),
                "parse_error": repair.get("parse_error") or {"code": "IMPORT_PARSE_ERROR", "message": "无法解析导入整理结果"},
                "attempts": attempts,
            }
        value = repair.get("value")
        raw_json = repair.get("raw_json")
        repaired_run_id = str(repair.get("repair_run_id") or "").strip() or None
        warnings.extend(list(repair.get("warnings") or []))

    try:
        parsed = ImportStructuredIngestResult.model_validate(value or {})
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "schema_invalid",
            "run_id": recorded.run_id,
            "repair_run_id": repaired_run_id,
            "warnings": warnings,
            "validation_error": exc.errors(),
            "attempts": attempts,
        }

    try:
        worldbook_payload = WorldBookImportAllRequest.model_validate(
            parsed.worldbook or {"schema_version": "worldbook_export_all_v1", "entries": []}
        )
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "worldbook_payload_invalid",
            "run_id": recorded.run_id,
            "repair_run_id": repaired_run_id,
            "warnings": warnings,
            "validation_error": exc.errors(),
            "attempts": attempts,
        }

    raw_story_memory = parsed.story_memory if isinstance(parsed.story_memory, dict) else {}
    story_memory_payload: StoryMemoryImportV1Request | None = None
    story_memory_preview: dict[str, Any] = {
        "schema_version": str(raw_story_memory.get("schema_version") or "story_memory_import_v1"),
        "memories": [],
    }
    if raw_story_memory.get("memories"):
        try:
            story_memory_payload = StoryMemoryImportV1Request.model_validate(raw_story_memory)
            story_memory_preview = story_memory_payload.model_dump()
        except ValidationError as exc:
            return {
                "ok": False,
                "reason": "story_memory_payload_invalid",
                "run_id": recorded.run_id,
                "repair_run_id": repaired_run_id,
                "warnings": warnings,
                "validation_error": exc.errors(),
                "attempts": attempts,
            }

    try:
        characters_payload = CharactersAutoUpdateV1Request.model_validate(
            parsed.characters or {"schema_version": "characters_auto_update_v1", "ops": []}
        )
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "characters_payload_invalid",
            "run_id": recorded.run_id,
            "repair_run_id": repaired_run_id,
            "warnings": warnings,
            "validation_error": exc.errors(),
            "attempts": attempts,
        }

    try:
        graph_payload = ImportGraphProposal.model_validate(parsed.graph or {"entities": [], "relations": []})
    except ValidationError as exc:
        return {
            "ok": False,
            "reason": "graph_payload_invalid",
            "run_id": recorded.run_id,
            "repair_run_id": repaired_run_id,
            "warnings": warnings,
            "validation_error": exc.errors(),
            "attempts": attempts,
        }

    worldbook_stats = {"created": 0, "updated": 0, "skipped": 0}
    story_memory_stats = {"created": 0, "skipped": 0}
    characters_stats: dict[str, Any] = {"created": 0, "updated": 0, "deduped": 0, "deleted": 0, "skipped": []}
    graph_stats = {
        "created_entities": 0,
        "updated_entities": 0,
        "created_relations": 0,
        "updated_relations": 0,
        "skipped": 0,
    }

    if apply_worldbook and worldbook_payload.entries:
        worldbook_stats = apply_import_worldbook_entries(
            db=db,
            project_id=project_id,
            entries=[item.model_dump() for item in worldbook_payload.entries],
        )

    if apply_story_memory and story_memory_payload is not None and story_memory_payload.memories:
        story_memory_stats = apply_import_story_memories(
            db=db,
            project_id=project_id,
            memories=[item.model_dump() for item in story_memory_payload.memories],
        )

    if apply_characters and characters_payload.ops:
        characters_stats = apply_characters_auto_update_ops(
            db=db,
            project_id=project_id,
            ops=[item.model_dump() for item in characters_payload.ops],
        )

    if apply_graph and (graph_payload.entities or graph_payload.relations):
        graph_stats = apply_import_graph_payload(db=db, project_id=project_id, graph=graph_payload)

    settings_row = db.get(ProjectSettings, project_id)
    if settings_row is None:
        settings_row = ProjectSettings(project_id=project_id)
        db.add(settings_row)
    if worldbook_stats["created"] or worldbook_stats["updated"] or story_memory_stats["created"]:
        settings_row.vector_index_dirty = True

    db.commit()

    if worldbook_stats["created"] or worldbook_stats["updated"] or story_memory_stats["created"]:
        schedule_vector_rebuild_task(
            db=db,
            project_id=project_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            reason="import_ai_enrichment_apply",
        )
    if (
        worldbook_stats["created"]
        or worldbook_stats["updated"]
        or story_memory_stats["created"]
        or characters_stats.get("created")
        or characters_stats.get("updated")
        or graph_stats["created_entities"]
        or graph_stats["created_relations"]
        or graph_stats["updated_entities"]
        or graph_stats["updated_relations"]
    ):
        schedule_search_rebuild_task(
            db=db,
            project_id=project_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            reason="import_ai_enrichment_apply",
        )

    return {
        "ok": True,
        "document_id": document.id,
        "run_id": recorded.run_id,
        "repair_run_id": repaired_run_id,
        "attempts": attempts,
        "warnings": warnings,
        "summary_md": parsed.summary_md,
        "raw_json": raw_json,
        "applied": {
            "worldbook": worldbook_stats if apply_worldbook else None,
            "story_memory": story_memory_stats if apply_story_memory else None,
            "characters": characters_stats if apply_characters else None,
            "graph": graph_stats if apply_graph else None,
        },
        "preview": {
            "worldbook": worldbook_payload.model_dump(),
            "story_memory": story_memory_preview,
            "characters": characters_payload.model_dump(),
            "graph": graph_payload.model_dump(),
        },
    }
