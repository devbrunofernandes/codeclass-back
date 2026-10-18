import httpx
import pytest

pytestmark = pytest.mark.live("storage")


async def test_storage_when_attachment_lifecycle_should_preserve_bytes_and_remove_object(
    async_client, tenant, classroom_with_student, live_storage_material
):
    name = live_storage_material
    content = "Material CodeClass — integração real\n".encode()
    base = f"/api/v1/classrooms/{classroom_with_student.id}/attachments"
    teacher = tenant.teacher.auth_headers
    student = tenant.student.auth_headers

    response = await async_client.post(
        base, headers=teacher, files={"file": (name, content, "text/plain")}
    )
    assert response.status_code == 201, response.text
    assert response.json()["size_bytes"] == len(content)
    assert response.json()["file_path"] == (
        f"{tenant.org.id}/{classroom_with_student.id}/{name}"
    )
    listing = await async_client.get(base, headers=student)
    assert listing.status_code == 200
    assert name in [item["file_name"] for item in listing.json()]

    signed = await async_client.get(f"{base}/{name}/download", headers=student)
    assert signed.status_code == 200, signed.text
    url = signed.json()["download_url"]
    async with httpx.AsyncClient(timeout=20) as client:
        downloaded = await client.get(url)
        assert downloaded.status_code == 200
        assert downloaded.content == content

        deleted = await async_client.delete(f"{base}/{name}", headers=teacher)
        assert deleted.status_code == 204, deleted.text
        listing = await async_client.get(base, headers=student)
        assert listing.status_code == 200
        assert name not in [item["file_name"] for item in listing.json()]
        missing = await client.get(url)
        assert missing.status_code in {400, 404}
