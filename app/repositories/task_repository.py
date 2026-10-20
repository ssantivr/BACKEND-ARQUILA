from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, task_id: int) -> Task | None:
        return self.session.get(Task, task_id)

    def list_by_project(self, project_id: int, status: str | None = None) -> list[Task]:
        query = select(Task).where(Task.project_id == project_id)

        if status is not None:
            query = query.where(Task.status == status)

        return list(self.session.scalars(query.order_by(Task.id)))

    def save(self, task: Task) -> Task:
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def delete(self, task: Task) -> None:
        self.session.delete(task)
        self.session.commit()
