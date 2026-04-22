from __future__ import annotations

import unittest
from datetime import timedelta
from typing import Generator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.routes import metrics as metrics_routes
from app.core.errors import AppError
from app.db.base import Base
from app.db.session import get_db
from app.db.utils import utc_now
from app.main import app_error_handler, validation_error_handler
from app.models.generation_run import GenerationRun
from app.models.memory_task import MemoryTask
from app.models.project import Project
from app.models.project_source_document import ProjectSourceDocument
from app.models.project_task import ProjectTask
from app.models.structured_memory import MemoryChangeSet
from app.models.user import User


def _make_test_app(SessionLocal: sessionmaker) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _test_user_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = "rid-test"
        user_id = request.headers.get("X-Test-User")
        request.state.user_id = user_id
        request.state.authenticated_user_id = user_id
        request.state.session_expire_at = None
        request.state.auth_source = "test"
        return await call_next(request)

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(metrics_routes.router, prefix="/api")

    def _override_get_db() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return app


class TestProjectMetricsOverviewEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)

        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Project.__table__,
                GenerationRun.__table__,
                MemoryChangeSet.__table__,
                MemoryTask.__table__,
                ProjectTask.__table__,
                ProjectSourceDocument.__table__,
            ],
        )
        self.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.app = _make_test_app(self.SessionLocal)

        now = utc_now()

        with self.SessionLocal() as db:
            db.add(User(id="u_owner", display_name="owner"))
            db.add(Project(id="p1", owner_user_id="u_owner", name="Project 1", genre=None, logline=None))
            db.add(
                MemoryChangeSet(
                    id="cs1",
                    project_id="p1",
                    actor_user_id="u_owner",
                    generation_run_id=None,
                    request_id="rid-cs1",
                    idempotency_key="cs:1",
                    status="proposed",
                )
            )
            db.add_all(
                [
                    ProjectTask(
                        id="pt-old",
                        project_id="p1",
                        actor_user_id="u_owner",
                        kind="search",
                        status="done",
                        idempotency_key="task:old",
                        created_at=now - timedelta(hours=30),
                        started_at=now - timedelta(hours=30) + timedelta(minutes=5),
                        finished_at=now - timedelta(hours=30) + timedelta(minutes=7),
                    ),
                    ProjectTask(
                        id="pt-queued",
                        project_id="p1",
                        actor_user_id="u_owner",
                        kind="search",
                        status="queued",
                        idempotency_key="task:queued",
                        created_at=now - timedelta(hours=2),
                    ),
                    ProjectTask(
                        id="pt-running",
                        project_id="p1",
                        actor_user_id="u_owner",
                        kind="vector",
                        status="running",
                        idempotency_key="task:running",
                        created_at=now - timedelta(minutes=40),
                        started_at=now - timedelta(minutes=30),
                    ),
                    ProjectTask(
                        id="pt-done",
                        project_id="p1",
                        actor_user_id="u_owner",
                        kind="graph",
                        status="succeeded",
                        idempotency_key="task:done",
                        created_at=now - timedelta(minutes=20),
                        started_at=now - timedelta(minutes=15),
                        finished_at=now - timedelta(minutes=10),
                    ),
                    ProjectTask(
                        id="pt-failed",
                        project_id="p1",
                        actor_user_id="u_owner",
                        kind="worldbook",
                        status="failed",
                        idempotency_key="task:failed",
                        created_at=now - timedelta(minutes=50),
                        started_at=now - timedelta(minutes=45),
                        finished_at=now - timedelta(minutes=40),
                    ),
                    MemoryTask(
                        id="mt-done",
                        project_id="p1",
                        change_set_id="cs1",
                        actor_user_id="u_owner",
                        kind="structured",
                        status="done",
                        created_at=now - timedelta(minutes=35),
                        started_at=now - timedelta(minutes=30),
                        finished_at=now - timedelta(minutes=25),
                    ),
                    MemoryTask(
                        id="mt-failed",
                        project_id="p1",
                        change_set_id="cs1",
                        actor_user_id="u_owner",
                        kind="story_memory",
                        status="failed",
                        created_at=now - timedelta(minutes=25),
                        started_at=now - timedelta(minutes=22),
                        finished_at=now - timedelta(minutes=20),
                    ),
                    ProjectSourceDocument(
                        id="doc-queued",
                        project_id="p1",
                        actor_user_id="u_owner",
                        filename="queued.md",
                        status="queued",
                        created_at=now - timedelta(minutes=12),
                        updated_at=now - timedelta(minutes=12),
                    ),
                    ProjectSourceDocument(
                        id="doc-done",
                        project_id="p1",
                        actor_user_id="u_owner",
                        filename="done.md",
                        status="done",
                        created_at=now - timedelta(minutes=18),
                        updated_at=now - timedelta(minutes=10),
                    ),
                    ProjectSourceDocument(
                        id="doc-failed",
                        project_id="p1",
                        actor_user_id="u_owner",
                        filename="failed.md",
                        status="failed",
                        created_at=now - timedelta(minutes=16),
                        updated_at=now - timedelta(minutes=15),
                    ),
                ]
            )
            db.commit()

    def test_returns_windowed_project_metrics(self) -> None:
        client = TestClient(self.app)

        resp = client.get("/api/projects/p1/metrics/overview?window_hours=24", headers={"X-Test-User": "u_owner"})
        self.assertEqual(resp.status_code, 200)

        data = resp.json().get("data") or {}
        self.assertEqual(data.get("window_hours"), 24)

        project_tasks = data.get("project_tasks") or {}
        self.assertEqual(project_tasks.get("total"), 4)
        self.assertEqual(project_tasks.get("queued"), 1)
        self.assertEqual(project_tasks.get("running"), 1)
        self.assertEqual(project_tasks.get("done"), 1)
        self.assertEqual(project_tasks.get("failed"), 1)
        self.assertEqual(project_tasks.get("avg_queue_ms"), 400000)
        self.assertEqual(project_tasks.get("avg_run_ms"), 300000)
        self.assertEqual(project_tasks.get("success_rate"), 0.5)
        self.assertEqual(
            [item.get("kind") for item in project_tasks.get("kind_breakdown") or []],
            ["worldbook", "vector", "graph", "search"],
        )

        memory_tasks = data.get("memory_tasks") or {}
        self.assertEqual(memory_tasks.get("total"), 2)
        self.assertEqual(memory_tasks.get("done"), 1)
        self.assertEqual(memory_tasks.get("failed"), 1)
        self.assertEqual(memory_tasks.get("avg_queue_ms"), 240000)
        self.assertEqual(memory_tasks.get("avg_run_ms"), 210000)
        self.assertEqual(memory_tasks.get("success_rate"), 0.5)
        self.assertEqual(
            [item.get("kind") for item in memory_tasks.get("kind_breakdown") or []],
            ["story_memory", "structured"],
        )

        imports = data.get("imports") or {}
        self.assertEqual(imports.get("total"), 3)
        self.assertEqual(imports.get("queued"), 1)
        self.assertEqual(imports.get("done"), 1)
        self.assertEqual(imports.get("failed"), 1)
        self.assertIsNone(imports.get("avg_queue_ms"))
        self.assertEqual(imports.get("avg_run_ms"), 180000)
        self.assertEqual(imports.get("success_rate"), 0.5)
