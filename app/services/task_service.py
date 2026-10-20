from sqlalchemy.orm import Session

from app.errors import InvalidDataError, NotFoundError
from app.models import Task, User
from app.repositories.task_repository import TaskRepository
from app.schemas import TaskCreate, TaskUpdate
from app.services.base import ProjectScopedService, changes_in

DONE = "done"
COMPLETE = 100


class TaskService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.tasks = TaskRepository(session)

    def create(self, project_id: int, data: TaskCreate) -> Task:
        self._ensure_project_exists(project_id)
        self._ensure_assignee_can_see_the_project(data.assignee_id)

        values = data.model_dump()

        if values["progress"] is None:
            values["progress"] = COMPLETE if values["status"] == DONE else 0

        self._ensure_done_is_complete(values["status"], values["progress"])

        task = self.tasks.save(Task(project_id=project_id, created_by=self.user.id, **values))
        self._record("created", "task", project_id, task.id, task.title)

        return task

    def list(self, project_id: int, status: str | None = None) -> list[Task]:
        self._ensure_project_exists(project_id)

        return self.tasks.list_by_project(project_id, status)

    def get(self, task_id: int) -> Task:
        task = self.tasks.get(task_id)

        if task is None or not self._owns(task.project_id):
            raise NotFoundError("Task not found")

        return task

    def update(self, task_id: int, data: TaskUpdate) -> Task:
        task = self.get(task_id)
        changes = changes_in(data, nullable=("description", "assignee_id", "due_date"))

        if "assignee_id" in changes:
            self._ensure_assignee_can_see_the_project(changes["assignee_id"])

        if changes.get("status") == DONE and "progress" not in changes:
            changes["progress"] = COMPLETE

        self._ensure_done_is_complete(
            changes.get("status", task.status), changes.get("progress", task.progress)
        )

        for field, value in changes.items():
            setattr(task, field, value)

        task = self.tasks.save(task)
        self._record(
            "updated", "task", task.project_id, task.id, task.title, fields=sorted(changes)
        )

        return task

    def delete(self, task_id: int) -> None:
        task = self.get(task_id)
        project_id, title = task.project_id, task.title
        self.tasks.delete(task)
        self._record("deleted", "task", project_id, task_id, title)

    def _ensure_assignee_can_see_the_project(self, assignee_id: int | None) -> None:
        # Projects are not shared, so only their owner can work on their tasks.
        if assignee_id is not None and assignee_id != self.user.id:
            raise InvalidDataError("A task can only be assigned to the owner of the project")

    def _ensure_done_is_complete(self, status: str, progress: int) -> None:
        if status == DONE and progress != COMPLETE:
            raise InvalidDataError("A task that is done must have a progress of 100")
