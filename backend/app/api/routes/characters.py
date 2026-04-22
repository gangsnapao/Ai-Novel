from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, UserIdDep, require_character_editor, require_project_editor, require_project_viewer
from app.core.errors import AppError, ok_payload
from app.db.utils import new_id
from app.models.character import Character
from app.schemas.characters import CharacterCreate, CharacterOut, CharacterUpdate
from app.schemas.characters_auto_update import CharactersAutoUpdateV1Request
from app.services.character_growth_service import (
    apply_profile_update,
    dump_text_list_json,
    parse_profile_history_json,
    parse_text_list_json,
)
from app.services.ai_one_click_import_service import analyze_characters_import_text
from app.services.characters_auto_update_service import apply_characters_auto_update_ops
from app.services.search_index_service import schedule_search_rebuild_task

router = APIRouter()


class CharactersAiImportAnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200000)


class CharactersAiImportApplyRequest(BaseModel):
    preview: CharactersAutoUpdateV1Request


def _character_out(row: Character) -> dict:
    return CharacterOut(
        id=str(row.id),
        project_id=str(row.project_id),
        name=str(row.name),
        role=row.role,
        profile=row.profile,
        profile_version=int(getattr(row, "profile_version", 0) or 0),
        profile_history=parse_profile_history_json(getattr(row, "profile_history_json", None)),
        arc_stages=parse_text_list_json(getattr(row, "arc_stages_json", None)),
        voice_samples=parse_text_list_json(getattr(row, "voice_samples_json", None)),
        notes=row.notes,
        updated_at=row.updated_at,
    ).model_dump()


@router.get("/projects/{project_id}/characters")
def list_characters(request: Request, db: DbDep, user_id: UserIdDep, project_id: str) -> dict:
    request_id = request.state.request_id
    require_project_viewer(db, project_id=project_id, user_id=user_id)
    rows = (
        db.execute(select(Character).where(Character.project_id == project_id).order_by(Character.updated_at.desc()))
        .scalars()
        .all()
    )
    return ok_payload(request_id=request_id, data={"characters": [_character_out(r) for r in rows]})


@router.post("/projects/{project_id}/characters")
def create_character(request: Request, db: DbDep, user_id: UserIdDep, project_id: str, body: CharacterCreate) -> dict:
    request_id = request.state.request_id
    require_project_editor(db, project_id=project_id, user_id=user_id)
    row = Character(
        id=new_id(),
        project_id=project_id,
        name=body.name,
        role=body.role,
        profile=None,
        profile_version=0,
        profile_history_json=None,
        arc_stages_json=dump_text_list_json(body.arc_stages),
        voice_samples_json=dump_text_list_json(body.voice_samples),
        notes=body.notes,
    )
    apply_profile_update(row=row, next_profile=body.profile)
    db.add(row)
    db.commit()
    db.refresh(row)
    schedule_search_rebuild_task(db=db, project_id=project_id, actor_user_id=user_id, request_id=request_id, reason="character_create")
    return ok_payload(request_id=request_id, data={"character": _character_out(row)})


@router.put("/characters/{character_id}")
def update_character(request: Request, db: DbDep, user_id: UserIdDep, character_id: str, body: CharacterUpdate) -> dict:
    request_id = request.state.request_id
    row = require_character_editor(db, character_id=character_id, user_id=user_id)

    if body.name is not None:
        row.name = body.name
    if body.role is not None:
        row.role = body.role
    if body.profile is not None:
        apply_profile_update(row=row, next_profile=body.profile, explicit_version=body.profile_version)
    elif body.profile_version is not None:
        row.profile_version = int(body.profile_version)
    if body.arc_stages is not None:
        row.arc_stages_json = dump_text_list_json(body.arc_stages)
    if body.voice_samples is not None:
        row.voice_samples_json = dump_text_list_json(body.voice_samples)
    if body.notes is not None:
        row.notes = body.notes

    db.commit()
    db.refresh(row)
    schedule_search_rebuild_task(
        db=db, project_id=str(row.project_id), actor_user_id=user_id, request_id=request_id, reason="character_update"
    )
    return ok_payload(request_id=request_id, data={"character": _character_out(row)})


@router.delete("/characters/{character_id}")
def delete_character(request: Request, db: DbDep, user_id: UserIdDep, character_id: str) -> dict:
    request_id = request.state.request_id
    row = require_character_editor(db, character_id=character_id, user_id=user_id)
    db.delete(row)
    db.commit()
    schedule_search_rebuild_task(
        db=db, project_id=str(row.project_id), actor_user_id=user_id, request_id=request_id, reason="character_delete"
    )
    return ok_payload(request_id=request_id, data={})


@router.post("/projects/{project_id}/characters/ai_import/analyze")
def analyze_characters_ai_import(
    request: Request,
    db: DbDep,
    user_id: UserIdDep,
    project_id: str,
    body: CharactersAiImportAnalyzeRequest,
) -> dict:
    request_id = request.state.request_id
    require_project_editor(db, project_id=project_id, user_id=user_id)

    result = analyze_characters_import_text(
        db=db,
        project_id=project_id,
        actor_user_id=user_id,
        request_id=request_id,
        source_text=body.text,
    )
    if bool(result.get("ok")):
        return ok_payload(request_id=request_id, data=result)

    reason = str(result.get("reason") or "").strip()
    if reason == "project_not_found":
        raise AppError.not_found(details=result)
    if reason == "llm_preset_missing":
        raise AppError.validation(message="请先在 Prompts 页面配置可用模型", details=result)
    if reason == "llm_call_failed":
        raise AppError(code="CHARACTERS_AI_IMPORT_LLM_FAILED", message="角色 AI 导入分析失败", status_code=502, details=result)
    raise AppError(code="CHARACTERS_AI_IMPORT_ANALYZE_FAILED", message="角色 AI 导入分析失败", status_code=400, details=result)


@router.post("/projects/{project_id}/characters/ai_import/apply")
def apply_characters_ai_import(
    request: Request,
    db: DbDep,
    user_id: UserIdDep,
    project_id: str,
    body: CharactersAiImportApplyRequest,
) -> dict:
    request_id = request.state.request_id
    require_project_editor(db, project_id=project_id, user_id=user_id)

    result = apply_characters_auto_update_ops(
        db=db,
        project_id=project_id,
        ops=[item.model_dump() for item in body.preview.ops],
    )
    db.commit()
    schedule_search_rebuild_task(
        db=db,
        project_id=project_id,
        actor_user_id=user_id,
        request_id=request_id,
        reason="characters_ai_import_apply",
    )
    return ok_payload(request_id=request_id, data=result)
