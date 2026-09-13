import importlib
import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.database import Base
from app.models import (
    Assignment,
    AssignmentType,
    Classroom,
    ClassroomMessage,
    Organization,
    OrgRole,
    ReleasePolicyType,
    Submission,
    SubmissionStatus,
    User,
)


def test_registered_tables_in_metadata():
    """Verify that all 9 required tables are registered in Base.metadata."""
    expected_tables = {
        "users",
        "organizations",
        "organization_members",
        "classrooms",
        "classroom_students",
        "assignments",
        "submissions",
        "submission_evaluations",
        "classroom_messages",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}"


def test_enums():
    """Verify enum definitions and values."""
    assert [e.value for e in OrgRole] == ["owner", "admin", "teacher", "student"]
    assert [e.value for e in AssignmentType] == ["code", "questionnaire"]
    assert [e.value for e in ReleasePolicyType] == ["immediate", "on_review"]
    assert [e.value for e in SubmissionStatus] == ["draft", "pending", "awaiting_review", "published"]


def test_primary_keys():
    """Verify primary key columns for all entities."""
    tables = Base.metadata.tables

    assert [c.name for c in tables["users"].primary_key.columns] == ["id"]
    assert [c.name for c in tables["organizations"].primary_key.columns] == ["id"]
    assert sorted([c.name for c in tables["organization_members"].primary_key.columns]) == ["organization_id", "user_id"]
    assert [c.name for c in tables["classrooms"].primary_key.columns] == ["id"]
    assert sorted([c.name for c in tables["classroom_students"].primary_key.columns]) == ["classroom_id", "student_id"]
    assert [c.name for c in tables["assignments"].primary_key.columns] == ["id"]
    assert [c.name for c in tables["submissions"].primary_key.columns] == ["id"]
    assert [c.name for c in tables["submission_evaluations"].primary_key.columns] == ["id"]
    assert [c.name for c in tables["classroom_messages"].primary_key.columns] == ["id"]


def test_foreign_keys_and_ondelete():
    """Verify foreign keys and ondelete behavior according to HLD.md."""
    tables = Base.metadata.tables

    def get_fk_map(table_name: str) -> dict[str, tuple[str, str]]:
        """Return dict: column_name -> (target_table.target_col, ondelete)."""
        fk_map = {}
        for fk in tables[table_name].foreign_keys:
            col_name = fk.parent.name
            target = f"{fk.column.table.name}.{fk.column.name}"
            fk_map[col_name] = (target, (fk.ondelete or "").upper())
        return fk_map

    # organizations.owner_id -> users.id (RESTRICT)
    org_fks = get_fk_map("organizations")
    assert org_fks["owner_id"] == ("users.id", "RESTRICT")

    # organization_members -> CASCADE
    org_members_fks = get_fk_map("organization_members")
    assert org_members_fks["organization_id"] == ("organizations.id", "CASCADE")
    assert org_members_fks["user_id"] == ("users.id", "CASCADE")

    # classrooms: org (CASCADE), teacher (RESTRICT)
    classroom_fks = get_fk_map("classrooms")
    assert classroom_fks["organization_id"] == ("organizations.id", "CASCADE")
    assert classroom_fks["teacher_id"] == ("users.id", "RESTRICT")

    # classroom_students -> CASCADE
    class_students_fks = get_fk_map("classroom_students")
    assert class_students_fks["classroom_id"] == ("classrooms.id", "CASCADE")
    assert class_students_fks["student_id"] == ("users.id", "CASCADE")

    # assignments -> CASCADE
    assignment_fks = get_fk_map("assignments")
    assert assignment_fks["classroom_id"] == ("classrooms.id", "CASCADE")

    # submissions -> CASCADE
    sub_fks = get_fk_map("submissions")
    assert sub_fks["assignment_id"] == ("assignments.id", "CASCADE")
    assert sub_fks["student_id"] == ("users.id", "CASCADE")

    # submission_evaluations -> CASCADE
    eval_fks = get_fk_map("submission_evaluations")
    assert eval_fks["submission_id"] == ("submissions.id", "CASCADE")

    # classroom_messages -> CASCADE
    msg_fks = get_fk_map("classroom_messages")
    assert msg_fks["classroom_id"] == ("classrooms.id", "CASCADE")
    assert msg_fks["sender_id"] == ("users.id", "CASCADE")


def test_unique_constraints():
    """Verify unique constraints."""
    tables = Base.metadata.tables

    # users.email unique
    assert tables["users"].columns["email"].unique is True

    # organizations.slug unique
    assert tables["organizations"].columns["slug"].unique is True

    # organization_members.user_id unique (each user in only 1 org)
    assert tables["organization_members"].columns["user_id"].unique is True

    # submissions uq_assignment_student
    submission_unique_col_sets = [
        {c.name for c in uc.columns} for uc in tables["submissions"].constraints if hasattr(uc, "columns") and uc.__class__.__name__ == "UniqueConstraint"
    ]
    assert {"assignment_id", "student_id"} in submission_unique_col_sets

    # submission_evaluations.submission_id unique
    assert tables["submission_evaluations"].columns["submission_id"].unique is True


def test_indexes():
    """Verify explicit indexes defined in HLD.md and valid PostgreSQL DDL compilation."""
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect
    from sqlalchemy.schema import CreateIndex

    tables = Base.metadata.tables

    def get_index_names(table_name: str) -> set[str]:
        return {idx.name for idx in tables[table_name].indexes}

    assert "idx_organizations_owner" in get_index_names("organizations")
    assert "idx_classrooms_org" in get_index_names("classrooms")
    assert "idx_classrooms_teacher" in get_index_names("classrooms")
    assert "idx_classroom_students_student" in get_index_names("classroom_students")
    assert "idx_assignments_class" in get_index_names("assignments")
    assert "idx_submissions_assignment_status" in get_index_names("submissions")
    assert "idx_classroom_messages_room_created" in get_index_names("classroom_messages")
    assert "idx_classroom_messages_sender" in get_index_names("classroom_messages")

    # Verify that all indexes compile to valid PostgreSQL syntax without double parentheses on columns
    dialect = pg_dialect()
    for table in tables.values():
        for index in table.indexes:
            compiled = str(CreateIndex(index).compile(dialect=dialect))
            assert "((" not in compiled, f"Index {index.name} has invalid expression nesting: {compiled}"


def test_model_relationships():
    """Verify ORM relationships are properly configured with bidirectional links and passive_deletes."""
    mapper_user = sa_inspect(User)
    assert "owned_organization" in mapper_user.relationships
    assert mapper_user.relationships["owned_organization"].uselist is False
    assert "membership" in mapper_user.relationships
    assert mapper_user.relationships["membership"].passive_deletes is True
    assert "teaching_classrooms" in mapper_user.relationships
    assert "enrolled_classrooms" in mapper_user.relationships
    assert mapper_user.relationships["enrolled_classrooms"].passive_deletes is True
    assert "submissions" in mapper_user.relationships
    assert mapper_user.relationships["submissions"].passive_deletes is True
    assert "messages" in mapper_user.relationships
    assert mapper_user.relationships["messages"].passive_deletes is True

    mapper_org = sa_inspect(Organization)
    assert "owner" in mapper_org.relationships
    assert "members" in mapper_org.relationships
    assert mapper_org.relationships["members"].passive_deletes is True
    assert "classrooms" in mapper_org.relationships
    assert mapper_org.relationships["classrooms"].passive_deletes is True

    mapper_classroom = sa_inspect(Classroom)
    assert "organization" in mapper_classroom.relationships
    assert "teacher" in mapper_classroom.relationships
    assert "students" in mapper_classroom.relationships
    assert mapper_classroom.relationships["students"].passive_deletes is True
    assert "assignments" in mapper_classroom.relationships
    assert mapper_classroom.relationships["assignments"].passive_deletes is True
    assert "messages" in mapper_classroom.relationships
    assert mapper_classroom.relationships["messages"].passive_deletes is True

    mapper_assignment = sa_inspect(Assignment)
    assert "classroom" in mapper_assignment.relationships
    assert "submissions" in mapper_assignment.relationships
    assert mapper_assignment.relationships["submissions"].passive_deletes is True

    mapper_submission = sa_inspect(Submission)
    assert "assignment" in mapper_submission.relationships
    assert "student" in mapper_submission.relationships
    assert "evaluation" in mapper_submission.relationships
    assert mapper_submission.relationships["evaluation"].passive_deletes is True

    mapper_msg = sa_inspect(ClassroomMessage)
    assert "classroom" in mapper_msg.relationships
    assert "sender" in mapper_msg.relationships


def test_initial_migration_script():
    """Verify that Alembic initial migration script is syntactically valid and has upgrade/downgrade."""
    versions_dir = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*_initial_schema.py"))
    assert migration_files, f"No initial migration file found in {versions_dir}"
    migration_path = migration_files[0]
    
    spec = importlib.util.spec_from_file_location("initial_schema_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert hasattr(migration, "revision")
    assert hasattr(migration, "upgrade")
    assert inspect.isfunction(migration.upgrade)
    assert hasattr(migration, "downgrade")
    assert inspect.isfunction(migration.downgrade)


@pytest.mark.asyncio
async def test_get_db_dependency():
    """Verify get_db dependency is an async generator returning an AsyncSession."""
    gen = get_db()
    assert inspect.isasyncgen(gen)
    session = await anext(gen)
    try:
        assert isinstance(session, AsyncSession)
    finally:
        await gen.aclose()
