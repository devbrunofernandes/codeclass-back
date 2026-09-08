from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "app": settings.PROJECT_NAME,
    }
