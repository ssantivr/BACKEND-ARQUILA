from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AIExtraction, Elevation, File, Plan


class FileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, file_id: int) -> File | None:
        return self.session.get(File, file_id)

    def get_in_project(self, file_id: int, project_id: int) -> File | None:
        file = self.get(file_id)
        return file if file is not None and file.project_id == project_id else None

    def list_by_project(self, project_id: int) -> list[File]:
        query = select(File).where(File.project_id == project_id)
        return list(self.session.scalars(query.order_by(File.id)))

    def save(self, file: File) -> File:
        self.session.add(file)
        self.session.commit()
        self.session.refresh(file)
        return file

    def delete(self, file: File) -> None:
        # The readings first, in the order apply and undo lock them.
        readings = update(AIExtraction).where(AIExtraction.file_id == file.id)
        self.session.execute(
            readings.where(AIExtraction.status == "review").values(status="failed")
        )
        self.session.execute(readings.values(file_id=None, proposal=None))

        for model in (Plan, Elevation):
            self.session.execute(update(model).where(model.file_id == file.id).values(file_id=None))

        self.session.delete(file)
        self.session.commit()
