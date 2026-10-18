"""Compatibilidade entre o SQL do Supabase Storage e seus índices internos."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_storage_schema_when_upsert_planned_should_infer_current_version_index(
    db_session: AsyncSession,
) -> None:
    # EXPLAIN valida o ON CONFLICT usado pelo Storage sem inserir objetos.
    plan = await db_session.scalar(
        text("""
            EXPLAIN (FORMAT JSON)
            INSERT INTO storage.objects (bucket_id, name)
            VALUES ('classroom-materials', 'schema-compatibility-probe')
            ON CONFLICT (bucket_id, name COLLATE "C")
                WHERE archived_at IS NULL
            DO NOTHING
        """)
    )
    assert plan is not None
    assert "idx_objects_current_version" in plan[0]["Plan"]["Conflict Arbiter Indexes"]
