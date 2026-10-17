"""Project logistics foundation. Typed, additive tables; no implied user permissions."""
from __future__ import annotations

from typing import Any
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = 'pl_project'
    id: str = Field(primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    owner: str
    department: str
    note: str = ''
    version: int = 1
    created_at: str


class Partner(SQLModel, table=True):
    __tablename__ = 'pl_partner'
    id: str = Field(primary_key=True)
    name: str
    normalized_name: str = Field(unique=True)
    kind: str
    contact: str
    note: str = ''
    version: int = 1
    created_at: str


class ShippingRequest(SQLModel, table=True):
    __tablename__ = 'pl_request'
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key='pl_project.id', index=True)
    title: str
    cargo: str
    unit_kind: str
    unit_count: int
    origin: str
    destination: str
    requested_delivery: str
    owner: str
    note: str = ''
    version: int = 1
    created_at: str


class TransportOrder(SQLModel, table=True):
    __tablename__ = 'pl_order'
    id: str = Field(primary_key=True)
    request_id: str = Field(foreign_key='pl_request.id', index=True)
    partner_id: str = Field(foreign_key='pl_partner.id', index=True)
    mode: str
    carrier: str = ''
    owner: str
    status: str = Field(default='assigned', index=True)
    eta: str | None = None
    note: str = ''
    version: int = 1
    created_at: str


class HandlingUnit(SQLModel, table=True):
    __tablename__ = 'pl_unit'
    __table_args__ = (UniqueConstraint('order_id', 'label'),)
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    label: str
    kind: str
    received_at: str | None = None
    receiver: str | None = None


class TransportReference(SQLModel, table=True):
    __tablename__ = 'pl_reference'
    __table_args__ = (UniqueConstraint('order_id', 'kind', 'issuer', 'value'),)
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    unit_id: str | None = Field(default=None, foreign_key='pl_unit.id')
    kind: str
    issuer: str
    value: str
    status: str = 'active'
    replaces_id: str | None = Field(default=None, foreign_key='pl_reference.id')
    reason: str = ''
    created_at: str


class TransportEvent(SQLModel, table=True):
    __tablename__ = 'pl_event'
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    kind: str
    classifier: str
    occurred_at: str
    recorded_at: str
    reported_by: str
    evidence: str
    actor: str = 'local-user'
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class TransportIssue(SQLModel, table=True):
    __tablename__ = 'pl_issue'
    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key='pl_order.id', index=True)
    title: str
    owner: str
    status: str = 'open'
    resolution: str = ''
    created_at: str
    resolved_at: str | None = None


class CommandReceipt(SQLModel, table=True):
    __tablename__ = 'pl_command'
    id: str = Field(primary_key=True)
    signature: str
    result: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: str


PROJECT_TABLES = {
    'projects': Project, 'partners': Partner, 'requests': ShippingRequest,
    'orders': TransportOrder, 'units': HandlingUnit, 'references': TransportReference,
    'events': TransportEvent, 'issues': TransportIssue,
}
