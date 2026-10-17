"""Immutable private files and append-only review history for transport orders."""
from sqlmodel import Field, SQLModel


class EvidenceRequirement(SQLModel, table=True):
    __tablename__ = 'co_evidence_requirement'
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    unit_id: str | None = Field(default=None, foreign_key='pl_unit.id')
    kind: str
    note: str
    created_by: str = Field(foreign_key='co_user.id')
    created_at: str


class EvidenceFile(SQLModel, table=True):
    __tablename__ = 'co_evidence_file'
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    unit_id: str | None = Field(default=None, foreign_key='pl_unit.id')
    requirement_id: str | None = Field(default=None, foreign_key='co_evidence_requirement.id')
    kind: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    storage_key: str = Field(unique=True)
    uploaded_by: str = Field(foreign_key='co_user.id')
    uploaded_at: str
    note: str = ''
    review_status: str = 'pending'
    version: int = 1
    command_id: str = Field(unique=True)
    signature: str


class EvidenceReview(SQLModel, table=True):
    __tablename__ = 'co_evidence_review'
    id: str = Field(primary_key=True)
    evidence_id: str = Field(foreign_key='co_evidence_file.id', index=True)
    reviewer_id: str = Field(foreign_key='co_user.id')
    outcome: str
    note: str
    created_at: str


EVIDENCE_MODELS = [EvidenceRequirement, EvidenceFile, EvidenceReview]
