import asyncio
import json

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

pytestmark = pytest.mark.live("chat")


async def test_chat_when_real_clients_connected_should_broadcast_persist_and_reject_outsider(
    live_chat_server, tenant, classroom_with_student, db_session
):
    from app.models.chat import ClassroomMessage

    base = f"{live_chat_server}/api/v1/classrooms/{classroom_with_student.id}"
    ws = base.replace("http://", "ws://") + "/chat/ws?token="
    async with asyncio.timeout(20):
        with pytest.raises(InvalidStatus) as denied:
            async with connect(ws + tenant.other_student.token):
                pytest.fail("Aluno não matriculado teve acesso ao chat")
        assert denied.value.response.status_code == 403
        async with (
            connect(ws + tenant.teacher.token) as teacher,
            connect(ws + tenant.student.token) as student,
            httpx.AsyncClient(timeout=10) as client,
        ):
            for connection in (teacher, student):
                await connection.send(json.dumps({"type": "ping"}))
                assert json.loads(await connection.recv()) == {"type": "pong"}
            response = await client.post(
                base + "/messages",
                headers=tenant.student.auth_headers,
                json={"content": "Mensagem via rede real"},
            )
            assert response.status_code == 201, response.text
            message = response.json()
            for connection in (teacher, student):
                event = json.loads(await connection.recv())
                assert event["type"] == "new_message"
                assert event["data"]["id"] == message["id"]
                assert event["data"]["content"] == message["content"]
            from uuid import UUID

            persisted = await db_session.get(ClassroomMessage, UUID(message["id"]))
            assert persisted.content == message["content"]
