from typing import Any
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class ImportBatch(SQLModel, table=True):
    __tablename__ = 'co_import_batch'
    __table_args__ = (UniqueConstraint('created_by', 'source_sha256', 'kind', 'project_id'),)
    id: str = Field(primary_key=True)
    created_by: str = Field(foreign_key='co_user.id', index=True)
    filename: str
    source_sha256: str
    source_base64: str
    kind: str
    project_id: str = ''
    status: str = 'pending'
    version: int = 1
    created_at: str
    confirmed_at: str | None = None
    rows: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    result: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
