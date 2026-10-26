from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType

if TYPE_CHECKING:
    from app.services.member_service import MemberService
    from app.services.organization_service import OrganizationService
    from app.services.storage_service import StorageService


@pytest.fixture
def mock_storage_provider() -> MagicMock:
    from app.infrastructure.storage.base import StorageProvider

    provider = MagicMock(spec=StorageProvider)
    provider.upload_file = AsyncMock()
    provider.get_signed_url = AsyncMock(
        return_value="https://storage.example.com/signed"
    )

    async def sign_many(bucket, paths, expires_in=3600):
        return {path: "https://storage.example.com/signed" for path in paths}

    provider.get_signed_urls = AsyncMock(side_effect=sign_many)
    provider.list_files = AsyncMock(return_value=[])
    provider.delete_file = AsyncMock()
    return provider


@pytest.fixture
def storage_service(mock_storage_provider: MagicMock) -> StorageService:
    from app.services.storage_service import StorageService

    return StorageService(provider=mock_storage_provider)


@pytest.fixture
def member_svc() -> MemberService:
    from app.services.member_service import MemberService

    return MemberService()


@pytest.fixture
def dummy_code_assignment() -> Assignment:
    assignment = Assignment(
        title="Busca Binária",
        description="Implemente busca binária recursiva ou iterativa",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "max_grade": 10.0,
            "statement": "Implemente a solução conforme os casos de teste.",
            "languages": [{"name": "python3"}],
            "rubrics": "Complexidade O(log n) e tratamento de lista vazia.",
        },
    )
    return assignment


@pytest.fixture
def dummy_questionnaire_assignment() -> Assignment:
    assignment = Assignment(
        title="Estruturas de Dados",
        description="Questionário misto",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 4.0,
                    "correct_option_id": "b",
                },
                {
                    "id": 2,
                    "type": "open",
                    "points": 6.0,
                    "prompt": "Explique tabelas hash.",
                    "reference_answer": "Estrutura com buckets e encadeamento.",
                },
            ]
        },
    )
    return assignment


@pytest.fixture
def org_svc() -> OrganizationService:
    from app.services.organization_service import OrganizationService

    return OrganizationService()
