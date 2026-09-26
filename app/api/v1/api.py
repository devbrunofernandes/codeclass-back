from fastapi import APIRouter

from app.api.v1 import (
    assignments,
    auth,
    chat,
    classrooms,
    health,
    organizations,
    submissions,
    users,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(organizations.router, prefix="/orgs", tags=["Organizations"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(classrooms.router, tags=["Classrooms"])
api_router.include_router(chat.router, tags=["Chat"])
api_router.include_router(assignments.router, tags=["Assignments"])
api_router.include_router(submissions.router, tags=["Submissions"])
