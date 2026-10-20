from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import TaskCreate, TaskRead, TaskStatus, TaskUpdate
from app.services.task_service import TaskService

router = APIRouter(tags=["tasks"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TaskService:
    return TaskService(session, user)


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task(project_id: int, data: TaskCreate, service: TaskService = Depends(get_service)):
    return service.create(project_id, data)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(
    project_id: int,
    status: TaskStatus | None = None,
    service: TaskService = Depends(get_service),
):
    return service.list(project_id, status)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, service: TaskService = Depends(get_service)):
    return service.get(task_id)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, data: TaskUpdate, service: TaskService = Depends(get_service)):
    return service.update(task_id, data)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, service: TaskService = Depends(get_service)):
    service.delete(task_id)
    return Response(status_code=204)
