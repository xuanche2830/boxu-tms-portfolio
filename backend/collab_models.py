"""Single enterprise collaboration: identities and explicit resource grants."""
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class Organization(SQLModel, table=True):
    __tablename__ = 'co_organization'
    id: str = Field(primary_key=True)
    name: str
    kind: str
    partner_id: str | None = Field(default=None, foreign_key='pl_partner.id', unique=True)


class User(SQLModel, table=True):
    __tablename__ = 'co_user'
    id: str = Field(primary_key=True)
    username: str = Field(unique=True, index=True)
    display_name: str
    password_hash: str
    role: str
    organization_id: str = Field(foreign_key='co_organization.id')
    active: bool = True
    must_change_password: bool = False
    created_at: str


class LoginSession(SQLModel, table=True):
    __tablename__ = 'co_session'
    token_hash: str = Field(primary_key=True)
    user_id: str = Field(foreign_key='co_user.id', index=True)
    csrf: str
    expires_at: str


class Grant(SQLModel, table=True):
    __tablename__ = 'co_grant'
    __table_args__ = (UniqueConstraint('user_id', 'kind', 'resource_id'),)
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key='co_user.id', index=True)
    kind: str
    resource_id: str = Field(index=True)
    created_by: str = Field(foreign_key='co_user.id')
    created_at: str


class LoginAttempt(SQLModel, table=True):
    __tablename__ = 'co_login_attempt'
    id: str = Field(primary_key=True)
    username: str = Field(index=True)
    address: str = Field(index=True)
    occurred_at: str = Field(index=True)


class SecurityAudit(SQLModel, table=True):
    __tablename__ = 'co_security_audit'
    id: str = Field(primary_key=True)
    actor: str
    action: str
    occurred_at: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class SchemaVersion(SQLModel, table=True):
    __tablename__ = 'co_schema_version'
    version: int = Field(primary_key=True)
    applied_at: str


AUTH_MODELS = [Organization, User, LoginSession, Grant, LoginAttempt, SecurityAudit, SchemaVersion]
