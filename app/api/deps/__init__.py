from app.api.deps.authentication import (
    get_current_active_member,
    get_current_user,
    security,
)
from app.api.deps.contexts import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
)
from app.api.deps.database import get_db
from app.api.deps.guards import (
    require_admin_or_owner,
    require_assignment_permission,
    require_classroom_permission,
    require_org_member,
    require_owner,
    require_roles,
    require_submission_permission,
    require_teacher,
    require_teacher_admin_or_owner,
    verify_org_access,
)
from app.api.deps.resolvers import (
    get_assignment_context,
    get_classroom_context,
    get_submission_context,
)

__all__ = [
    "AssignmentContext",
    "ClassroomContext",
    "SubmissionContext",
    "get_assignment_context",
    "get_classroom_context",
    "get_current_active_member",
    "get_current_user",
    "get_db",
    "get_submission_context",
    "require_admin_or_owner",
    "require_assignment_permission",
    "require_classroom_permission",
    "require_org_member",
    "require_owner",
    "require_roles",
    "require_submission_permission",
    "require_teacher",
    "require_teacher_admin_or_owner",
    "security",
    "verify_org_access",
]
