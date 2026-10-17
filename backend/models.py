from __future__ import annotations

from typing import Any
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class Shipment(SQLModel, table=True):
    __tablename__ = 'shipment'
    id: str = Field(primary_key=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Trip(SQLModel, table=True):
    __tablename__ = 'container_trip'
    __table_args__ = (UniqueConstraint('shipment_id', 'container_number'),)
    id: str = Field(primary_key=True)
    shipment_id: str = Field(foreign_key='shipment.id', index=True)
    container_number: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Milestone(SQLModel, table=True):
    __tablename__ = 'milestone'
    __table_args__ = (UniqueConstraint('source_id', 'source_event_id'),)
    id: str = Field(primary_key=True)
    shipment_id: str = Field(foreign_key='shipment.id', index=True)
    container_trip_id: str | None = Field(default=None, foreign_key='container_trip.id', index=True)
    source_id: str = Field(foreign_key='source.id')
    source_event_id: str | None = None
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Release(SQLModel, table=True):
    __tablename__ = 'release_condition'
    id: str = Field(primary_key=True)
    container_trip_id: str = Field(foreign_key='container_trip.id', index=True)
    kind: str = Field(index=True)
    revision: int = 1
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Deadline(SQLModel, table=True):
    __tablename__ = 'deadline'
    __table_args__ = (UniqueConstraint('container_trip_id', 'kind'),)
    id: str = Field(primary_key=True)
    container_trip_id: str = Field(foreign_key='container_trip.id', index=True)
    kind: str
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Task(SQLModel, table=True):
    __tablename__ = 'pickup_task'
    __table_args__ = (UniqueConstraint('container_trip_id'),)
    id: str = Field(primary_key=True)
    container_trip_id: str = Field(foreign_key='container_trip.id', index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ExceptionRecord(SQLModel, table=True):
    __tablename__ = 'exception_record'
    id: str = Field(primary_key=True)
    container_trip_id: str = Field(foreign_key='container_trip.id', index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Source(SQLModel, table=True):
    __tablename__ = 'source'
    id: str = Field(primary_key=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Audit(SQLModel, table=True):
    __tablename__ = 'audit_log'
    id: str = Field(primary_key=True)
    entity_id: str = Field(index=True)
    occurred_at: str
    action: str
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ImportBatch(SQLModel, table=True):
    __tablename__ = 'import_batch'
    id: str = Field(primary_key=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Setting(SQLModel, table=True):
    __tablename__ = 'setting'
    id: str = Field(primary_key=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class Migration(SQLModel, table=True):
    __tablename__ = 'schema_migration'
    version: int = Field(primary_key=True)
    applied_at: str
