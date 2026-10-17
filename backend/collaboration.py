"""Loopback-only collaboration pilot, isolated from the unauthenticated legacy app."""
from contextlib import asynccontextmanager
import hashlib
import json
import os
import re
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, event
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, create_engine, select
from . import collab_auth as auth, collab_policy as policy, project_logistics as business
from .collab_models import AUTH_MODELS, Grant, LoginSession, Organization, SchemaVersion, SecurityAudit, User
from .db import DATA, ROOT, identifier, now
from .domain import DomainError
from .models import Audit
from .project_models import PROJECT_TABLES, CommandReceipt, Project, Partner, ShippingRequest, TransportOrder

PREFIX = '/api/collab'
PORT = int(os.environ.get('TMS_COLLAB_PORT', '8768'))
if not 1 <= PORT <= 65535:
    raise RuntimeError('协同服务端口无效')
from pathlib import Path
from sqlalchemy import func
from . import collab_database as database, collab_backup as backup, evidence_storage

DEMO = os.environ.get('TMS_COLLAB_DEMO') == '1'
DEMO_PORT = int(os.environ.get('TMS_COLLAB_DEMO_PORT', '8769'))
WORK_PORT = int(os.environ.get('TMS_COLLAB_WORK_PORT', '8768'))
engine = database.make_engine()
BACKUPS = DATA / 'backups' / 'collaboration-demo' if DEMO else Path(os.environ.get('TMS_COLLAB_BACKUP_DIR', str(DATA / 'backups' / 'collaboration')))


def migrate():
    database.migrate(engine)


@asynccontextmanager
async def lifespan(app):
    migrate()
    if DEMO:
        from .collab_demo import seed
        seed(engine)
    yield


app = FastAPI(title='泊序 · 协同试点', version='0.12.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def boundary(request: Request, call_next):
    if request.headers.get('host') not in [f'127.0.0.1:{PORT}', f'localhost:{PORT}'] or not request.client or request.client.host not in ['127.0.0.1', '::1']:
        return JSONResponse({'detail': '当前协同试点仅开放本机访问'}, status_code=403)
    if request.method not in ['GET', 'HEAD']:
        origin = request.headers.get('origin')
        expected_origin = 'http://' + request.headers.get('host', '')
        if (origin and origin != expected_origin) or request.headers.get('x-tms-client') != 'collaboration-v1':
            return JSONResponse({'detail': '请求来源不允许'}, status_code=403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return JSONResponse({'detail': '请求需要JSON格式'}, status_code=415)
        limit = evidence_storage.MAX_JSON_BYTES if request.method == 'POST' and re.fullmatch(r'/api/collab/project-logistics/orders/[^/]+/evidence', request.url.path) else 100_000
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return JSONResponse({'detail': '请求内容过大；附件单件最多2 MiB，其他表单最多100 KB'}, status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(DomainError)
async def domain_error(request, error):
    return JSONResponse({'detail': str(error)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Do not echo raw rejected input (including passwords) into validation responses.
    return JSONResponse({'detail': '字段格式不符合要求，请检查必填项、数量、账号格式和密码长度'}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, error):
    return JSONResponse({'detail': '账号、组织或授权已存在，请刷新核对'}, status_code=409)


def connection():
    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def signed_in(request: Request, session: Session = Depends(connection)):
    account = auth.authenticate(session, request)
    expected = request.headers.get('x-expected-user')
    if expected and expected != account.id:
        raise HTTPException(401, '其他标签页已切换账号，请重新载入当前会话')
    if account.must_change_password and request.url.path not in [PREFIX + '/me', PREFIX + '/password', PREFIX + '/logout']:
        raise HTTPException(403, '首次登录请先修改初始密码')
    return session


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=60, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=1, max_length=128)

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        return value.lower()


class SetupInput(LoginInput):
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)
    company: str = Field(min_length=1, max_length=100)


class NewUser(LoginInput):
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)
    role: Literal['employee', 'partner']
    partner_id: str | None = None


class ActiveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool


class GrantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str
    kind: Literal['project', 'order']
    resource_id: str


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def whoami(session, account, login_record):
    org = business.get(session, Organization, account.organization_id)
    return {'user': auth.public_user(account), 'organization': {'id': org.id, 'name': org.name},
            'csrf': login_record.csrf, 'expires_at': login_record.expires_at, 'storage': engine.dialect.name, 'demo': DEMO}


@app.get('/api/health')
def health():
    return {'application': 'harbor-tms-collaboration', 'version': app.version, 'pid': os.getpid(), 'demo': DEMO,
            'instance': hashlib.sha256(str(ROOT.resolve()).casefold().encode()).hexdigest()[:16]}


@app.get(PREFIX + '/status')
def status(session: Session = Depends(connection)):
    return {'setup_required': session.exec(select(User.id)).first() is None, 'version': app.version, 'demo': DEMO, 'demo_url': f'http://127.0.0.1:{DEMO_PORT}/collaboration#projects', 'work_url': f'http://127.0.0.1:{WORK_PORT}/collaboration#projects'}


class DemoLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['owner', 'employee', 'partner'] = 'owner'


@app.post(PREFIX + '/demo-login')
def demo_login(data: DemoLogin, request: Request, response: Response, session: Session = Depends(connection)):
    if not DEMO:
        raise HTTPException(404, '演示入口仅在独立演示空间开放')
    from .collab_demo import DEMO_USERS
    account = session.get(User, DEMO_USERS[data.role])
    if not account or not account.active:
        raise HTTPException(409, '演示账号已停用，请使用演示负责人恢复')
    record = auth.start_session(session, response, account, request.cookies.get(auth.COOKIE, ''))
    auth.log(session, account.id, 'demo_role_selected')
    session.commit()
    return whoami(session, account, record)


@app.post(PREFIX + '/setup')
def setup(data: SetupInput, request: Request, response: Response, session: Session = Depends(connection)):
    if session.exec(select(User.id)).first():
        raise HTTPException(409, '已经初始化，请使用已有账号登录')
    org = Organization(id='ORG-ENTERPRISE', name=data.company.strip(), kind='enterprise')
    session.add(org)
    session.flush()  # Fixed organization key also prevents two simultaneous initial owners.
    account = User(id=identifier('USR'), username=data.username, display_name=data.display_name.strip(),
                   password_hash=auth.hash_password(data.password), role='owner', organization_id=org.id, created_at=now())
    session.add(account)
    session.flush()
    record = auth.start_session(session, response, account)
    auth.log(session, account.id, 'setup', {'organization_id': org.id})
    session.commit()
    return whoami(session, account, record)


@app.post(PREFIX + '/login')
def login(data: LoginInput, request: Request, response: Response, session: Session = Depends(connection)):
    account, record = auth.login(session, request, response, data.username, data.password)
    return whoami(session, account, record)


@app.get(PREFIX + '/me')
def me(session: Session = Depends(signed_in)):
    return whoami(session, policy.user(session), session.info['login_session'])


@app.post(PREFIX + '/logout')
def logout(response: Response, session: Session = Depends(signed_in)):
    session.delete(session.info['login_session'])
    auth.log(session, policy.user(session).id, 'logout')
    session.commit()
    response.delete_cookie(auth.COOKIE, path=PREFIX)
    return {'ok': True}


@app.get(PREFIX + '/admin')
def admin(session: Session = Depends(signed_in)):
    policy.owner_only(session)
    data = policy.overview(session)
    return {'users': [auth.public_user(u) for u in session.exec(select(User)).all()],
            'organizations': [o.model_dump() for o in session.exec(select(Organization)).all()],
            'grants': [g.model_dump() for g in session.exec(select(Grant)).all()],
            'projects': [{'id': p['id'], 'name': p['name'], 'code': p['code']} for p in data['projects']],
            'partners': data['partners'], 'orders': data['orders'],
            'audit': [a.model_dump() for a in session.exec(select(SecurityAudit).order_by(SecurityAudit.occurred_at.desc()).limit(100)).all()]}


@app.get(PREFIX + '/maintenance')
def maintenance(session: Session = Depends(signed_in)):
    policy.owner_only(session)
    return {'storage': engine.dialect.name, 'revision': database.revision(session.connection()),
            'expected_revision': database.HEAD,
            'counts': {name: session.exec(select(func.count()).select_from(model)).one()
                       for name, model in [('projects', Project), ('orders', TransportOrder), ('users', User)]},
            'backups': backup.list_backups(BACKUPS)}


@app.post(PREFIX + '/maintenance/backups')
def make_backup(session: Session = Depends(signed_in)):
    policy.owner_only(session)
    try:
        result = backup.create_backup(engine, BACKUPS)
    except ValueError as error:
        raise HTTPException(422, str(error))
    auth.log(session, policy.user(session).id, 'backup_created', {'file': result['file']})
    session.commit()
    return {'file': result['file'], 'created_at': result['created_at'],
            'records': sum(row['count'] for row in result['tables'].values()), 'revision': result['revision']}


@app.post(PREFIX + '/password')
def change_password(data: PasswordInput, request: Request, response: Response, session: Session = Depends(signed_in)):
    account = policy.user(session)
    if not auth.verify_password(data.current_password, account.password_hash):
        raise HTTPException(422, '当前密码不正确')
    if data.new_password == data.current_password:
        raise HTTPException(422, '新密码不能与初始密码相同')
    account.password_hash = auth.hash_password(data.new_password)
    account.must_change_password = False
    session.add(account)
    session.exec(delete(LoginSession).where(LoginSession.user_id == account.id))
    record = auth.start_session(session, response, account)
    auth.log(session, account.id, 'password_changed')
    session.commit()
    return whoami(session, account, record)


@app.post(PREFIX + '/users')
def create_user(data: NewUser, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    org_id = policy.user(session).organization_id
    if data.role == 'partner':
        if not data.partner_id:
            raise HTTPException(422, '货代账号必须选择所属合作伙伴')
        partner = business.get(session, Partner, data.partner_id)
        org = session.exec(select(Organization).where(Organization.partner_id == partner.id)).first()
        if not org:
            org = Organization(id=identifier('ORG'), name=partner.name, kind='partner', partner_id=partner.id)
            session.add(org)
            session.flush()
        org_id = org.id
    elif data.partner_id:
        raise HTTPException(422, '员工账号不能绑定货代组织')
    account = User(id=identifier('USR'), username=data.username, display_name=data.display_name.strip(),
                   password_hash=auth.hash_password(data.password), role=data.role, organization_id=org_id, created_at=now(), must_change_password=True)
    session.add(account)
    session.flush()
    auth.log(session, policy.user(session).id, 'user_create', {'user_id': account.id, 'role': account.role, 'organization_id': org_id})
    session.commit()
    return auth.public_user(account)


@app.put(PREFIX + '/users/{key}/active')
def user_active(key: str, data: ActiveInput, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    account = business.get(session, User, key)
    if account.role == 'owner':
        raise HTTPException(422, '本版不支持停用初始企业负责人')
    account.active = data.active
    session.add(account)
    if not data.active:
        session.exec(delete(LoginSession).where(LoginSession.user_id == key))
    auth.log(session, policy.user(session).id, 'user_active', {'user_id': key, 'active': data.active})
    session.commit()
    return {'ok': True}


@app.post(PREFIX + '/grants')
def create_grant(data: GrantInput, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    account = business.get(session, User, data.user_id)
    if not account.active:
        raise HTTPException(422, '请先启用账号')
    if data.kind == 'project' and account.role == 'employee':
        business.get(session, Project, data.resource_id)
    elif data.kind == 'order' and account.role == 'partner':
        order = business.get(session, TransportOrder, data.resource_id)
        org = business.get(session, Organization, account.organization_id)
        if org.partner_id != order.partner_id or order.status == 'cancelled':
            raise HTTPException(422, '只能授权当前委托伙伴组织内的账号，且委托不能已取消')
    else:
        raise HTTPException(422, '员工按项目授权，货代按运输委托授权')
    grant = Grant(id=identifier('GRT'), created_by=policy.user(session).id, created_at=now(), **data.model_dump())
    session.add(grant)
    auth.log(session, policy.user(session).id, 'grant_create', data.model_dump())
    session.commit()
    return {'id': grant.id}


@app.delete(PREFIX + '/grants/{key}')
def revoke_grant(key: str, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    grant = business.get(session, Grant, key)
    auth.log(session, policy.user(session).id, 'grant_revoke', grant.model_dump())
    session.delete(grant)
    session.commit()
    return {'ok': True}


def command(session, name, data, handler):
    # Principal namespace prevents another identity from replaying a prior user's command receipt.
    return business.command(session, policy.user(session).id + ':' + name, data, handler)


@app.get(PREFIX + '/project-logistics')
def listing(session: Session = Depends(signed_in)):
    return policy.overview(session)


@app.get(PREFIX + '/project-logistics/orders/{key}')
def order_detail(key: str, session: Session = Depends(signed_in)):
    return policy.detail(session, key)


@app.post(PREFIX + '/project-logistics/projects')
def create_project(data: business.ProjectInput, session: Session = Depends(signed_in)):
    policy.internal_only(session)
    def write():
        result = business.create_project(session, data)
        if policy.user(session).role == 'employee':
            session.add(Grant(id=identifier('GRT'), user_id=policy.user(session).id, kind='project', resource_id=result['id'],
                              created_by=policy.user(session).id, created_at=now()))
        return result
    return command(session, 'project', data, write)


@app.put(PREFIX + '/project-logistics/projects/{key}')
def edit_project(key: str, data: business.ProjectEdit, session: Session = Depends(signed_in)):
    policy.project_access(session, key)
    return command(session, key + '/edit', data, lambda: business.edit_master(session, Project, key, data))


@app.post(PREFIX + '/project-logistics/partners')
def create_partner(data: business.PartnerInput, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    return command(session, 'partner', data, lambda: business.create_partner(session, data))


@app.put(PREFIX + '/project-logistics/partners/{key}')
def edit_partner(key: str, data: business.PartnerEdit, session: Session = Depends(signed_in)):
    policy.owner_only(session)
    return command(session, key + '/edit', data, lambda: business.edit_master(session, Partner, key, data))


@app.post(PREFIX + '/project-logistics/requests')
def create_request(data: business.RequestInput, session: Session = Depends(signed_in)):
    policy.project_access(session, data.project_id)
    return command(session, 'request', data, lambda: business.create_request(session, data))


@app.put(PREFIX + '/project-logistics/requests/{key}')
def edit_request(key: str, data: business.RequestEdit, session: Session = Depends(signed_in)):
    row = session.get(ShippingRequest, key)
    if not row:
        raise HTTPException(404, '记录不存在或没有访问权限')
    policy.project_access(session, row.project_id)
    return command(session, key + '/edit', data, lambda: business.edit_master(session, ShippingRequest, key, data))


@app.post(PREFIX + '/project-logistics/orders')
def create_order(data: business.OrderInput, session: Session = Depends(signed_in)):
    row = session.get(ShippingRequest, data.request_id)
    if not row:
        raise HTTPException(404, '记录不存在或没有访问权限')
    policy.project_access(session, row.project_id)
    return command(session, 'order', data, lambda: business.create_order(session, data))


@app.post(PREFIX + '/project-logistics/orders/{key}/references')
def reference(key: str, data: business.ReferenceInput, session: Session = Depends(signed_in)):
    policy.order_access(session, key)
    return command(session, key + '/ref', data, lambda: business.add_reference(session, key, data))


@app.post(PREFIX + '/project-logistics/orders/{key}/actions')
def action(key: str, data: business.ActionInput, session: Session = Depends(signed_in)):
    order = policy.order_access(session, key)
    if policy.user(session).role == 'partner' and data.action not in policy.PARTNER_ACTIONS:
        raise HTTPException(403, '当前账号不能执行此动作；签收复核、异常结案和关单由内部员工确认')
    def write():
        result = business.add_action(session, key, data)
        if data.action in ['reassign', 'cancel']:
            old = session.exec(select(Grant).where(Grant.kind == 'order', Grant.resource_id == key)).all()
            for grant in old:
                session.delete(grant)
            auth.log(session, policy.user(session).id, 'order_grants_revoked', {'order_id': key, 'count': len(old)})
        return result
    return command(session, key + '/action', data, write)


@app.post(PREFIX + '/project-logistics/orders/{key}/issues')
def issue(key: str, data: business.IssueInput, session: Session = Depends(signed_in)):
    policy.order_access(session, key)
    return command(session, key + '/issue', data, lambda: business.create_issue(session, key, data))


@app.post(PREFIX + '/project-logistics/orders/{key}/issues/{issue_id}/resolve')
def resolve(key: str, issue_id: str, data: business.ResolveInput, session: Session = Depends(signed_in)):
    policy.internal_only(session)
    policy.order_access(session, key)
    return command(session, key + '/issue/' + issue_id, data, lambda: business.resolve_issue(session, key, issue_id, data))


@app.get(PREFIX + '/project-logistics-export')
def export(session: Session = Depends(signed_in)):
    records = policy.scoped_records(session)
    ids = {r['id'] for key in ['projects', 'requests', 'orders'] for r in records[key]}
    audits = [] if policy.user(session).role == 'partner' else [a.model_dump() for a in session.exec(select(Audit).where(Audit.entity_id.in_(ids))).all()]
    body = {'application': 'harbor-tms-collaboration', 'scope': '当前账号获授权范围', 'exported_at': now(), 'records': records, 'audit': audits}
    auth.log(session, policy.user(session).id, 'export', {'orders': len(records['orders'])})
    session.commit()
    return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="collaboration-records.json"'})


from . import collab_import
collab_import.register(app, signed_in)
from . import collab_evidence
collab_evidence.register(app, signed_in, engine)


@app.get('/')
@app.get('/collaboration')
def index():
    return FileResponse(ROOT / 'web' / 'index.html')


app.mount('/assets', StaticFiles(directory=ROOT / 'web' / 'assets'), name='assets')
