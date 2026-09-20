from collections.abc import Callable, Coroutine
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.classroom import (
    ClassroomDetailResponse,
    ClassroomMembersResponse,
    ClassroomMyClassResponse,
    ClassroomStudentMemberResponse,
    ClassroomTeacherResponse,
)

RoleClassroomQueryHandler = Callable[
    [OrganizationMember, AsyncSession],
    Coroutine[Any, Any, list[ClassroomMyClassResponse]],
]


class ClassroomService:
    def __init__(self) -> None:
        # Strategy Pattern: mapeia cada papel institucional ao seu algoritmo de consulta específico
        self._role_query_strategies: dict[OrgRole, RoleClassroomQueryHandler] = {
            OrgRole.OWNER: self._list_for_management,
            OrgRole.ADMIN: self._list_for_management,
            OrgRole.TEACHER: self._list_for_teacher,
            OrgRole.STUDENT: self._list_for_student,
        }

    # --- Estratégias de Consulta de Turmas por Papel (Strategy Pattern) ---

    async def _list_for_management(
        self, member: OrganizationMember, db: AsyncSession
    ) -> list[ClassroomMyClassResponse]:
        """Estratégia para Coordenação (Owner/Admin): visualização completa com papel contextual."""
        stmt = (
            select(Classroom)
            .where(Classroom.organization_id == member.organization_id)
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        classrooms = result.scalars().all()
        role_label: Literal["owner", "admin"] = (
            "owner" if member.role == OrgRole.OWNER else "admin"
        )
        return [
            ClassroomMyClassResponse(
                id=c.id,
                organization_id=c.organization_id,
                teacher_id=c.teacher_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at,
                role_in_class="teacher"
                if c.teacher_id == member.user_id
                else role_label,
            )
            for c in classrooms
        ]

    async def _list_for_teacher(
        self, member: OrganizationMember, db: AsyncSession
    ) -> list[ClassroomMyClassResponse]:
        """Estratégia para Docentes: retorna turmas sob sua responsabilidade."""
        stmt = (
            select(Classroom)
            .where(
                Classroom.organization_id == member.organization_id,
                Classroom.teacher_id == member.user_id,
            )
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        classrooms = result.scalars().all()
        return [
            ClassroomMyClassResponse(
                id=c.id,
                organization_id=c.organization_id,
                teacher_id=c.teacher_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at,
                role_in_class="teacher",
            )
            for c in classrooms
        ]

    async def _list_for_student(
        self, member: OrganizationMember, db: AsyncSession
    ) -> list[ClassroomMyClassResponse]:
        """Estratégia para Discentes: retorna turmas em que está devidamente matriculado."""
        stmt = (
            select(Classroom)
            .join(ClassroomStudent, Classroom.id == ClassroomStudent.classroom_id)
            .where(
                Classroom.organization_id == member.organization_id,
                ClassroomStudent.student_id == member.user_id,
            )
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        classrooms = result.scalars().all()
        return [
            ClassroomMyClassResponse(
                id=c.id,
                organization_id=c.organization_id,
                teacher_id=c.teacher_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at,
                role_in_class="student",
            )
            for c in classrooms
        ]

    async def list_user_classrooms(
        self, member: OrganizationMember, db: AsyncSession
    ) -> list[ClassroomMyClassResponse]:
        """Ponto de entrada polimórfico que despacha a consulta para a estratégia do papel do membro."""
        strategy = self._role_query_strategies.get(member.role, self._list_for_student)
        return await strategy(member, db)

    # --- Operações de Ciclo de Vida da Sala de Aula ---

    async def create_classroom(
        self,
        organization_id: UUID,
        name: str,
        description: str | None,
        teacher_id: UUID | None,
        creator_member: OrganizationMember,
        db: AsyncSession,
    ) -> Classroom:
        """Cria uma sala de aula validando permissões do criador e docência associada."""
        if creator_member.role == OrgRole.TEACHER:
            assigned_teacher_id = creator_member.user_id
        else:
            # Coordenação (Admin ou Owner)
            if teacher_id is not None:
                stmt = select(OrganizationMember).where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == teacher_id,
                )
                target_member = (await db.execute(stmt)).scalar_one_or_none()

                if target_member is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="O professor indicado não pertence a esta organização.",
                    )
                if not target_member.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="O professor indicado está inativo nesta organização.",
                    )
                if target_member.role not in (
                    OrgRole.TEACHER,
                    OrgRole.ADMIN,
                    OrgRole.OWNER,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="O usuário indicado deve possuir papel docente ou administrativo.",
                    )
                assigned_teacher_id = teacher_id
            else:
                assigned_teacher_id = creator_member.user_id

        classroom = Classroom(
            organization_id=organization_id,
            teacher_id=assigned_teacher_id,
            name=name,
            description=description,
        )
        db.add(classroom)
        await db.commit()
        await db.refresh(classroom)
        return classroom

    async def get_classroom_details(
        self, classroom: Classroom, db: AsyncSession
    ) -> ClassroomDetailResponse:
        """Monta os detalhes enriquecidos da sala com contagem agregada de alunos."""
        count_stmt = (
            select(func.count())
            .select_from(ClassroomStudent)
            .where(ClassroomStudent.classroom_id == classroom.id)
        )
        total_students = (await db.execute(count_stmt)).scalar() or 0

        return ClassroomDetailResponse(
            id=classroom.id,
            organization_id=classroom.organization_id,
            teacher_id=classroom.teacher_id,
            name=classroom.name,
            description=classroom.description,
            created_at=classroom.created_at,
            teacher=ClassroomTeacherResponse(
                id=classroom.teacher.id,
                full_name=classroom.teacher.full_name,
                email=classroom.teacher.email,
            ),
            total_students=total_students,
        )

    async def update_classroom(
        self,
        classroom: Classroom,
        name: str | None,
        description: str | None,
        db: AsyncSession,
    ) -> Classroom:
        """Atualiza campos opcionais da sala de aula."""
        if name is not None:
            classroom.name = name
        if description is not None:
            classroom.description = description

        await db.commit()
        await db.refresh(classroom)
        return classroom

    async def delete_classroom(self, classroom: Classroom, db: AsyncSession) -> None:
        """Remove a sala de aula e dados associados via cascata relacional."""
        await db.delete(classroom)
        await db.commit()

    # --- Gestão de Matrículas e Membros da Turma ---

    async def enroll_student(
        self,
        classroom: Classroom,
        student_id: UUID,
        db: AsyncSession,
    ) -> ClassroomStudentMemberResponse:
        """Matricula estudante validando tenant, atividade e unicidade com proteção contra race conditions."""
        member_stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == classroom.organization_id,
                OrganizationMember.user_id == student_id,
            )
        )
        student_member = (await db.execute(member_stmt)).scalar_one_or_none()

        if student_member is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O usuário indicado não pertence a esta organização.",
            )

        if not student_member.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível matricular um usuário desativado na organização.",
            )

        if student_member.role != OrgRole.STUDENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Apenas membros com papel de estudante podem ser matriculados na turma.",
            )

        # Checagem preliminar de duplicidade
        enrolled_stmt = select(ClassroomStudent).where(
            ClassroomStudent.classroom_id == classroom.id,
            ClassroomStudent.student_id == student_id,
        )
        if (await db.execute(enrolled_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O estudante já está matriculado nesta turma.",
            )

        new_enrollment = ClassroomStudent(
            classroom_id=classroom.id,
            student_id=student_id,
        )
        db.add(new_enrollment)
        try:
            await db.commit()
            await db.refresh(new_enrollment)
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O estudante já está matriculado nesta turma.",
            )

        return ClassroomStudentMemberResponse(
            student_id=student_member.user.id,
            full_name=student_member.user.full_name,
            email=student_member.user.email,
            enrolled_at=new_enrollment.enrolled_at,
        )

    async def unenroll_student(
        self, classroom_id: UUID, student_id: UUID, db: AsyncSession
    ) -> None:
        """Desvincula um aluno da turma."""
        enrolled_stmt = select(ClassroomStudent).where(
            ClassroomStudent.classroom_id == classroom_id,
            ClassroomStudent.student_id == student_id,
        )
        enrollment = (await db.execute(enrolled_stmt)).scalar_one_or_none()

        if enrollment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="O estudante não está matriculado nesta turma.",
            )

        await db.delete(enrollment)
        await db.commit()

    async def list_classroom_members(
        self, classroom: Classroom, db: AsyncSession
    ) -> ClassroomMembersResponse:
        """Recupera o docente e todos os estudantes matriculados com join otimizado."""
        teacher_resp = ClassroomTeacherResponse(
            id=classroom.teacher.id,
            full_name=classroom.teacher.full_name,
            email=classroom.teacher.email,
        )

        stmt = (
            select(ClassroomStudent, User)
            .join(User, ClassroomStudent.student_id == User.id)
            .where(ClassroomStudent.classroom_id == classroom.id)
            .order_by(ClassroomStudent.enrolled_at.asc())
        )
        results = (await db.execute(stmt)).all()

        students_resp = [
            ClassroomStudentMemberResponse(
                student_id=user.id,
                full_name=user.full_name,
                email=user.email,
                enrolled_at=enrollment.enrolled_at,
            )
            for enrollment, user in results
        ]

        return ClassroomMembersResponse(teacher=teacher_resp, students=students_resp)

    async def list_organization_classrooms(
        self, organization_id: UUID, db: AsyncSession
    ) -> list[Classroom]:
        """Lista todas as turmas de uma organização para supervisão institucional."""
        stmt = (
            select(Classroom)
            .where(Classroom.organization_id == organization_id)
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


classroom_service = ClassroomService()
