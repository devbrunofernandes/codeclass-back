"""Dublês dos contratos para testes de infraestrutura genérica."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_pubsub_broker() -> AsyncMock:
    from app.infrastructure.realtime.pubsub.base import PubSubBroker

    return AsyncMock(spec=PubSubBroker)
