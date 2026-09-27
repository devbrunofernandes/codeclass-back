from typing import Annotated

from fastapi import APIRouter, Depends, Response, UploadFile, status

from app.api.deps import ClassroomContext, require_classroom_permission
from app.schemas.classroom import (
    ClassroomAttachmentDownloadResponse,
    ClassroomAttachmentResponse,
)
from app.services.storage_service import storage_service

router = APIRouter()


@router.post(
    "/{classroom_id}/attachments",
    response_model=ClassroomAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload em streaming de material didático (máx. 30MB)",
)
async def upload_attachment(
    file: UploadFile,
    context: Annotated[
        ClassroomContext,
        Depends(require_classroom_permission(can_manage_attachments=True)),
    ],
) -> ClassroomAttachmentResponse:
    data = await storage_service.upload_classroom_material(
        organization_id=context.classroom.organization_id,
        classroom_id=context.classroom.id,
        file=file,
    )

    return ClassroomAttachmentResponse(
        file_name=data["file_name"],
        file_path=data["file_path"],
        size_bytes=data["size_bytes"],
        content_type=data["content_type"],
    )


@router.get(
    "/{classroom_id}/attachments",
    response_model=list[ClassroomAttachmentResponse],
    summary="Lista metadados dos materiais anexados no Supabase Storage",
)
async def list_attachments(
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
) -> list[ClassroomAttachmentResponse]:
    files = await storage_service.list_classroom_materials(
        organization_id=context.classroom.organization_id,
        classroom_id=context.classroom.id,
    )

    return [
        ClassroomAttachmentResponse(
            file_name=f["file_name"],
            file_path=f["file_path"],
            size_bytes=f["size_bytes"],
            content_type=f["content_type"],
            uploaded_at=f["uploaded_at"],
        )
        for f in files
    ]


@router.get(
    "/{classroom_id}/attachments/{file_name}/download",
    response_model=ClassroomAttachmentDownloadResponse,
    summary="Retorna Signed URL temporária do Supabase Storage para download direto",
)
async def get_attachment_download_url(
    file_name: str,
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
) -> ClassroomAttachmentDownloadResponse:
    download_url = await storage_service.create_signed_download_url(
        organization_id=context.classroom.organization_id,
        classroom_id=context.classroom.id,
        file_name=file_name,
        expires_in=3600,
    )

    return ClassroomAttachmentDownloadResponse(
        file_name=file_name,
        download_url=download_url,
        expires_in=3600,
    )


@router.delete(
    "/{classroom_id}/attachments/{file_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui arquivo de apoio do Supabase Storage",
)
async def delete_attachment(
    file_name: str,
    context: Annotated[
        ClassroomContext,
        Depends(require_classroom_permission(can_manage_attachments=True)),
    ],
) -> Response:
    await storage_service.delete_classroom_material(
        organization_id=context.classroom.organization_id,
        classroom_id=context.classroom.id,
        file_name=file_name,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
