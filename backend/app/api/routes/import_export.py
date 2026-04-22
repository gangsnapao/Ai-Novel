from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, UserIdDep, require_project_editor, require_project_viewer
from app.core.errors import AppError, ok_payload
from app.db.session import SessionLocal
from app.db.utils import new_id
from app.models.project_source_document import ProjectSourceDocument, ProjectSourceDocumentChunk
from app.services.import_ai_enrichment_service import enrich_import_document_and_apply
from app.services.import_export_service import retry_import_task
from app.services.task_queue import get_task_queue
from app.services.vector_kb_service import create_kb as create_vector_kb

router = APIRouter()


def _doc_public(row: ProjectSourceDocument) -> dict[str, object]:
    created_at = getattr(row, "created_at", None)
    updated_at = getattr(row, "updated_at", None)
    return {
        "id": row.id,
        "project_id": row.project_id,
        "actor_user_id": row.actor_user_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "status": row.status,
        "progress": int(row.progress or 0),
        "progress_message": row.progress_message,
        "chunk_count": int(row.chunk_count or 0),
        "kb_id": row.kb_id,
        "error_message": row.error_message,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _safe_json(raw: str | None, default: object) -> object:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


class ImportCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_text: str = Field(min_length=1, max_length=5_000_000)
    content_type: str | None = Field(default=None, max_length=32)


class ImportOneClickApplyRequest(BaseModel):
    requirements: str | None = Field(default=None, max_length=8000)
    apply_worldbook: bool = True
    apply_story_memory: bool = True
    apply_characters: bool = True
    apply_graph: bool = True


@router.get("/projects/{project_id}/imports")
def list_imports(request: Request, db: DbDep, user_id: UserIdDep, project_id: str) -> dict:
    request_id = request.state.request_id
    require_project_viewer(db, project_id=project_id, user_id=user_id)

    rows = (
        db.execute(
            select(ProjectSourceDocument)
            .where(ProjectSourceDocument.project_id == project_id)
            .order_by(ProjectSourceDocument.updated_at.desc(), ProjectSourceDocument.created_at.desc())
        )
        .scalars()
        .all()
    )
    return ok_payload(request_id=request_id, data={"documents": [_doc_public(r) for r in rows]})


@router.post("/projects/{project_id}/imports")
def create_import(request: Request, db: DbDep, user_id: UserIdDep, project_id: str, body: ImportCreateRequest) -> dict:
    request_id = request.state.request_id
    require_project_editor(db, project_id=project_id, user_id=user_id)

    filename = str(body.filename or "").strip()
    if not filename:
        filename = "import.txt"
    content_type = str(body.content_type or "").strip().lower() or None
    if content_type is None:
        lowered = filename.lower()
        if lowered.endswith(".md") or lowered.endswith(".markdown"):
            content_type = "md"
        else:
            content_type = "txt"

    doc = ProjectSourceDocument(
        id=new_id(),
        project_id=project_id,
        actor_user_id=user_id,
        filename=filename,
        content_type=content_type,
        content_text=body.content_text,
        status="queued",
        progress=0,
        progress_message="queued",
    )
    db.add(doc)

    kb_name = f"Import: {filename}".strip()
    kb = create_vector_kb(db, project_id=project_id, name=kb_name[:255], enabled=False, weight=1.0)
    doc.kb_id = kb.kb_id

    db.commit()
    db.refresh(doc)

    job_id: str | None = None
    enqueue_error: str | None = None
    try:
        job_id = get_task_queue().enqueue(kind="import_task", task_id=doc.id)
    except Exception as exc:
        enqueue_error = type(exc).__name__

    if enqueue_error:
        doc.status = "failed"
        doc.progress_message = "enqueue_failed"
        doc.error_message = f"enqueue_failed:{enqueue_error}"
        db.commit()
        db.refresh(doc)

    return ok_payload(request_id=request_id, data={"document": _doc_public(doc), "job_id": job_id})


@router.get("/projects/{project_id}/imports/{document_id}")
def get_import(request: Request, db: DbDep, user_id: UserIdDep, project_id: str, document_id: str) -> dict:
    request_id = request.state.request_id
    require_project_viewer(db, project_id=project_id, user_id=user_id)

    doc_id = str(document_id or "").strip()
    row = db.get(ProjectSourceDocument, doc_id)
    if row is None or str(row.project_id) != str(project_id):
        raise AppError.not_found()

    content_preview = (str(row.content_text or "").strip()[:500].rstrip() + "…") if len(str(row.content_text or "")) > 500 else str(row.content_text or "").strip()

    return ok_payload(
        request_id=request_id,
        data={
            "document": _doc_public(row),
            "content_preview": content_preview,
            "vector_ingest_result": _safe_json(row.vector_ingest_result_json, {}),
            "worldbook_proposal": _safe_json(row.worldbook_proposal_json, {}),
            "story_memory_proposal": _safe_json(row.story_memory_proposal_json, {}),
        },
    )


@router.post("/projects/{project_id}/imports/{document_id}/one_click_apply")
def one_click_apply_import(
    request: Request,
    db: DbDep,
    user_id: UserIdDep,
    project_id: str,
    document_id: str,
    body: ImportOneClickApplyRequest,
) -> dict:
    request_id = request.state.request_id
    require_project_editor(db, project_id=project_id, user_id=user_id)

    if not any((body.apply_worldbook, body.apply_story_memory, body.apply_characters, body.apply_graph)):
        raise AppError.validation(message="请至少选择一种写入目标", details={"reason": "no_apply_targets"})

    result = enrich_import_document_and_apply(
        db=db,
        project_id=project_id,
        document_id=document_id,
        actor_user_id=user_id,
        request_id=request_id,
        import_requirements=(str(body.requirements or "").strip() or None),
        apply_worldbook=bool(body.apply_worldbook),
        apply_story_memory=bool(body.apply_story_memory),
        apply_characters=bool(body.apply_characters),
        apply_graph=bool(body.apply_graph),
    )
    if bool(result.get("ok")):
        return ok_payload(request_id=request_id, data=result)

    reason = str(result.get("reason") or "").strip()
    if reason in {"project_not_found", "document_not_found"}:
        raise AppError.not_found(details=result)
    if reason == "document_not_ready":
        raise AppError.conflict(message="导入文档尚未处理完成", details=result)
    if reason == "llm_preset_missing":
        raise AppError.validation(message="请先在 Prompts 页面配置用于导入整理的 LLM", details=result)
    if reason == "llm_call_failed":
        raise AppError(code="IMPORT_LLM_FAILED", message="一键导入整理调用 LLM 失败", status_code=502, details=result)

    raise AppError(code="IMPORT_ONE_CLICK_FAILED", message="一键导入整理失败", status_code=400, details=result)


@router.get("/projects/{project_id}/imports/{document_id}/chunks")
def list_import_chunks(
    request: Request,
    db: DbDep,
    user_id: UserIdDep,
    project_id: str,
    document_id: str,
    limit: int = Query(default=40, ge=1, le=200),
) -> dict:
    request_id = request.state.request_id
    require_project_viewer(db, project_id=project_id, user_id=user_id)

    doc_id = str(document_id or "").strip()
    doc = db.get(ProjectSourceDocument, doc_id)
    if doc is None or str(doc.project_id) != str(project_id):
        raise AppError.not_found()

    rows = (
        db.execute(
            select(ProjectSourceDocumentChunk)
            .where(ProjectSourceDocumentChunk.document_id == doc_id)
            .order_by(ProjectSourceDocumentChunk.chunk_index.asc())
            .limit(int(limit))
        )
        .scalars()
        .all()
    )

    chunks = []
    for r in rows:
        text = str(r.content_text or "").strip()
        preview = (text[:200].rstrip() + "…") if len(text) > 200 else text
        chunks.append(
            {
                "id": r.id,
                "chunk_index": int(r.chunk_index or 0),
                "preview": preview,
                "vector_chunk_id": r.vector_chunk_id,
            }
        )
    return ok_payload(request_id=request_id, data={"chunks": chunks, "returned": len(chunks)})


@router.post("/projects/{project_id}/imports/{document_id}/retry")
def retry_import(request: Request, user_id: UserIdDep, project_id: str, document_id: str) -> dict:
    request_id = request.state.request_id

    db = SessionLocal()
    try:
        require_project_editor(db, project_id=project_id, user_id=user_id)
        cleanup = retry_import_task(project_id=project_id, document_id=document_id)
        row = db.get(ProjectSourceDocument, str(document_id or "").strip())
        if row is None or str(row.project_id) != str(project_id):
            raise AppError.not_found()
        doc_public = _doc_public(row)
    finally:
        db.close()

    job_id: str | None = None
    enqueue_error: str | None = None
    try:
        job_id = get_task_queue().enqueue(kind="import_task", task_id=str(document_id or "").strip())
    except Exception as exc:
        enqueue_error = type(exc).__name__

    if enqueue_error:
        # Best-effort write back failure.
        db2 = SessionLocal()
        try:
            row2 = db2.get(ProjectSourceDocument, str(document_id or "").strip())
            if row2 is not None:
                row2.status = "failed"
                row2.progress_message = "enqueue_failed"
                row2.error_message = f"enqueue_failed:{enqueue_error}"
                db2.commit()
                doc_public = _doc_public(row2)
        finally:
            db2.close()

    return ok_payload(
        request_id=request_id,
        data={"document": doc_public, "cleanup": cleanup, "job_id": job_id, "enqueue_error": enqueue_error},
    )
