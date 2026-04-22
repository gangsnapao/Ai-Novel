from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.character import Character
from app.models.llm_profile import LLMProfile
from app.models.outline import Outline
from app.models.project import Project
from app.models.story_memory import StoryMemory
from app.models.structured_memory import MemoryEntity, MemoryRelation
from app.models.user import User
from app.models.worldbook_entry import WorldBookEntry
from app.services.import_ai_enrichment_service import (
    ImportGraphEntityProposal,
    ImportGraphProposal,
    ImportGraphRelationProposal,
    apply_import_graph_payload,
    apply_import_story_memories,
    apply_import_worldbook_entries,
)


class TestImportAiEnrichmentService(unittest.TestCase):
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
                LLMProfile.__table__,
                Outline.__table__,
                Project.__table__,
                Character.__table__,
                WorldBookEntry.__table__,
                StoryMemory.__table__,
                MemoryEntity.__table__,
                MemoryRelation.__table__,
            ],
        )
        self.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.SessionLocal() as db:
            db.add(User(id="u1", display_name="User 1", is_admin=False))
            db.add(
                Project(
                    id="p1",
                    owner_user_id="u1",
                    name="Blue Moon",
                    genre="fantasy",
                    logline="test",
                    active_outline_id=None,
                    llm_profile_id=None,
                )
            )
            db.commit()

    def test_apply_import_worldbook_entries_creates_and_updates(self) -> None:
        with self.SessionLocal() as db:
            db.add(
                WorldBookEntry(
                    id="wb1",
                    project_id="p1",
                    title="皇城",
                    content_md="旧内容",
                    enabled=False,
                    constant=False,
                    keywords_json=json.dumps(["旧"], ensure_ascii=False),
                    priority="optional",
                )
            )
            db.commit()

            stats = apply_import_worldbook_entries(
                db=db,
                project_id="p1",
                entries=[
                    {
                        "title": "皇城",
                        "content_md": "新内容",
                        "enabled": True,
                        "constant": True,
                        "keywords": ["都城", "王庭"],
                        "priority": "must",
                    },
                    {
                        "title": "蓝月王朝",
                        "content_md": "北地王朝。",
                        "keywords": ["王朝", "北地"],
                    },
                    {"title": "   ", "content_md": "ignored"},
                ],
            )
            db.commit()

            self.assertEqual(stats, {"created": 1, "updated": 1, "skipped": 1})

            rows = db.execute(select(WorldBookEntry).where(WorldBookEntry.project_id == "p1")).scalars().all()
            self.assertEqual(len(rows), 2)

            updated = db.execute(
                select(WorldBookEntry).where(WorldBookEntry.project_id == "p1", WorldBookEntry.title == "皇城")
            ).scalar_one()
            created = db.execute(
                select(WorldBookEntry).where(WorldBookEntry.project_id == "p1", WorldBookEntry.title == "蓝月王朝")
            ).scalar_one()

            self.assertEqual(updated.content_md, "新内容")
            self.assertTrue(updated.enabled)
            self.assertTrue(updated.constant)
            self.assertEqual(json.loads(updated.keywords_json or "[]"), ["都城", "王庭"])
            self.assertEqual(updated.priority, "must")
            self.assertEqual(created.content_md, "北地王朝。")

    def test_apply_import_story_memories_skips_duplicates(self) -> None:
        with self.SessionLocal() as db:
            db.add(
                StoryMemory(
                    id="sm1",
                    project_id="p1",
                    chapter_id=None,
                    memory_type="fact",
                    title="王朝",
                    content="蓝月王朝已经延续三百年。",
                    full_context_md=None,
                    importance_score=0.4,
                    tags_json=None,
                    story_timeline=0,
                    text_position=-1,
                    text_length=0,
                    is_foreshadow=0,
                    foreshadow_resolved_at_chapter_id=None,
                    metadata_json=None,
                )
            )
            db.commit()

            stats = apply_import_story_memories(
                db=db,
                project_id="p1",
                memories=[
                    {
                        "memory_type": "fact",
                        "title": "王朝",
                        "content": "蓝月王朝已经延续三百年。",
                    },
                    {
                        "memory_type": "fact",
                        "title": "禁忌",
                        "content": "皇族不得在满月夜离宫。",
                        "importance_score": 0.9,
                    },
                    {
                        "memory_type": "fact",
                        "title": "空白",
                        "content": "   ",
                    },
                ],
            )
            db.commit()

            self.assertEqual(stats, {"created": 1, "skipped": 2})

            rows = db.execute(select(StoryMemory).where(StoryMemory.project_id == "p1")).scalars().all()
            self.assertEqual(len(rows), 2)
            contents = {row.content for row in rows}
            self.assertIn("皇族不得在满月夜离宫。", contents)

    def test_apply_import_graph_payload_reuses_and_enriches_entities(self) -> None:
        with self.SessionLocal() as db:
            db.add(
                MemoryEntity(
                    id="e1",
                    project_id="p1",
                    entity_type="generic",
                    name="阿月",
                    summary_md=None,
                    attributes_json=json.dumps({"aliases": ["月王女"]}, ensure_ascii=False),
                    deleted_at=None,
                )
            )
            db.commit()

            stats = apply_import_graph_payload(
                db=db,
                project_id="p1",
                graph=ImportGraphProposal(
                    entities=[
                        ImportGraphEntityProposal(
                            entity_type="person",
                            name="阿月",
                            summary_md="蓝月王朝继承人。",
                            attributes={"aliases": ["月公主"], "tags": ["royal"]},
                        ),
                        ImportGraphEntityProposal(
                            entity_type="organization",
                            name="蓝月近卫",
                            summary_md="守护王庭的精锐军团。",
                            attributes={"tags": ["guard"]},
                        ),
                    ],
                    relations=[
                        ImportGraphRelationProposal(
                            from_entity_name="阿月",
                            to_entity_name="蓝月近卫",
                            relation_type="leader_of",
                            description_md="名义上的最高统领。",
                            attributes={"status": "active"},
                        )
                    ],
                ),
            )
            db.commit()

            self.assertEqual(
                stats,
                {
                    "created_entities": 1,
                    "updated_entities": 1,
                    "created_relations": 1,
                    "updated_relations": 0,
                    "skipped": 0,
                },
            )

            entities = db.execute(select(MemoryEntity).where(MemoryEntity.project_id == "p1")).scalars().all()
            self.assertEqual(len(entities), 2)

            ayue = db.execute(
                select(MemoryEntity).where(MemoryEntity.project_id == "p1", MemoryEntity.name == "阿月")
            ).scalar_one()
            guard = db.execute(
                select(MemoryEntity).where(MemoryEntity.project_id == "p1", MemoryEntity.name == "蓝月近卫")
            ).scalar_one()
            relation = db.execute(select(MemoryRelation).where(MemoryRelation.project_id == "p1")).scalar_one()

            self.assertEqual(ayue.entity_type, "person")
            self.assertEqual(ayue.summary_md, "蓝月王朝继承人。")
            self.assertEqual(sorted(json.loads(ayue.attributes_json or "{}").get("aliases", [])), ["月公主", "月王女"])
            self.assertEqual(guard.entity_type, "organization")
            self.assertEqual(relation.relation_type, "leader_of")
            self.assertEqual(relation.description_md, "名义上的最高统领。")


if __name__ == "__main__":
    unittest.main()
