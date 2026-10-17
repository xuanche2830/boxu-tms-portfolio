from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PField, field_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .db import ENGINES, audit, identifier, now
from .domain import DomainError, dt
from .models import Audit, Migration, Setting
from .project_models import (PROJECT_TABLES, CommandReceipt, HandlingUnit, Partner,
                             Project, ShippingRequest, TransportEvent, TransportIssue,
                             TransportOrder, TransportReference)

MODES = {'express': '国际快递', 'sea': '海运', 'air': '空运', 'road': '公路', 'rail': '铁路', 'other': '其他'}
STATES = {'assigned': '待接单', 'accepted': '待发运', 'in_transit': '运输中',
          'partial_delivered': '部分签收', 'delivered': '全部签收', 'closed': '已关单', 'cancelled': '已取消'}
UNIT_KINDS = {'package': '包裹', 'pallet': '托盘', 'container': '集装箱', 'piece': '独立件'}
REF_KINDS = {'tracking': '快递单号', 'house': '分运单 / HBL / HAWB', 'master': '主运单 / MBL / MAWB', 'booking': '订舱号', 'other': '其他参考号'}
EVENT_NAMES = {'accept': '确认接单', 'dispatch': '确认发运', 'receive': '按件签收', 'eta': '更新预计到达',
               'note': '补充跟进记录', 'cancel': '取消委托', 'close': '关单', 'reopen': '重新打开', 'reassign': '更换合作伙伴'}


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    command_id: str = PField(min_length=16, max_length=80)


class ProjectInput(Command):
    code: str = PField(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    name: str = PField(min_length=1, max_length=100)
    owner: str = PField(min_length=1, max_length=60)
    department: str = PField(min_length=1, max_length=80)
    note: str = PField(default='', max_length=2000)


class PartnerInput(Command):
    name: str = PField(min_length=1, max_length=100)
    kind: Literal['forwarder', 'express']
    contact: str = PField(min_length=1, max_length=100)
    note: str = PField(default='', max_length=2000)


class RequestInput(Command):
    project_id: str
    title: str = PField(min_length=1, max_length=100)
    cargo: str = PField(min_length=1, max_length=300)
    unit_kind: Literal['package', 'pallet', 'container', 'piece']
    unit_count: int = PField(ge=1, le=200, strict=True)
    origin: str = PField(min_length=1, max_length=150)
    destination: str = PField(min_length=1, max_length=150)
    requested_delivery: str
    owner: str = PField(min_length=1, max_length=60)
    note: str = PField(default='', max_length=2000)

    @field_validator('requested_delivery')
    @classmethod
    def valid_date(cls, value):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('期望到货日请填写 YYYY-MM-DD')
        date.fromisoformat(value)
        return value


class OrderInput(Command):
    request_id: str
    request_version: int = PField(ge=1, strict=True)
    partner_id: str
    mode: Literal['express', 'sea', 'air', 'road', 'rail', 'other']
    carrier: str = PField(default='', max_length=100)
    owner: str = PField(min_length=1, max_length=60)
    unit_count: int = PField(ge=1, le=200, strict=True)
    note: str = PField(default='', max_length=2000)


class Versioned(Command):
    version: int = PField(ge=1, strict=True)


class ProjectEdit(ProjectInput):
    version: int = PField(ge=1, strict=True)


class PartnerEdit(PartnerInput):
    version: int = PField(ge=1, strict=True)


class RequestEdit(RequestInput):
    version: int = PField(ge=1, strict=True)


class ReferenceInput(Versioned):
    kind: Literal['tracking', 'house', 'master', 'booking', 'other']
    issuer: str = PField(min_length=1, max_length=100)
    value: str = PField(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9._/-]*$')
    unit_id: str | None = None
    replaces_id: str | None = None
    reason: str = PField(default='', max_length=1000)


class ActionInput(Versioned):
    action: Literal['accept', 'dispatch', 'receive', 'eta', 'note', 'cancel', 'close', 'reopen', 'reassign']
    occurred_at: str
    reported_by: str = PField(min_length=1, max_length=100)
    evidence: str = PField(min_length=1, max_length=2000)
    unit_ids: list[str] = PField(default_factory=list, max_length=200)
    receiver: str = PField(default='', max_length=100)
    partner_id: str | None = None

    @field_validator('occurred_at')
    @classmethod
    def aware_timestamp(cls, value):
        try:
            return dt(value).isoformat()
        except DomainError as error:
            raise ValueError(str(error)) from error


class IssueInput(Versioned):
    title: str = PField(min_length=1, max_length=300)
    owner: str = PField(min_length=1, max_length=60)


class ResolveInput(Versioned):
    resolution: str = PField(min_length=1, max_length=2000)


def get(session, model, key):
    row = session.get(model, key)
    if row is None:
        raise HTTPException(404, '关联记录不存在，请刷新后重新选择')
    return row


def bump(session, row, expected):
    model = type(row)
    result = session.exec(update(model).where(model.id == row.id, model.version == expected).values(version=expected + 1))
    if result.rowcount != 1:
        raise HTTPException(409, '记录已被更新，请刷新页面后重新操作；当前填写内容尚未写入')
    session.refresh(row)


def active_order(order):
    if order.status in ['closed', 'cancelled']:
        raise DomainError('此委托已关单或取消，不能继续修改')


def command(session, name, payload, handler):
    data = payload.model_dump()
    signature = hashlib.sha256(json.dumps({'name': name, 'data': data}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    old = session.get(CommandReceipt, payload.command_id)
    if old:
        if old.signature != signature:
            raise HTTPException(409, '同一个操作编号不能提交不同内容，请重新打开表单')
        return {**old.result, 'replayed': True}
    try:
        result = handler()
        session.add(CommandReceipt(id=payload.command_id, signature=signature, result=result, created_at=now()))
        session.commit()
        return result
    except IntegrityError:
        session.rollback()
        old = session.get(CommandReceipt, payload.command_id)
        if old and old.signature == signature:
            return {**old.result, 'replayed': True}
        raise HTTPException(409, '项目编号、合作伙伴名称或运输单号已存在，请刷新核对')


def create_project(session, data):
    row = Project(id=identifier('PRJ'), created_at=now(), **data.model_dump(exclude={'command_id', 'code'}), code=data.code.upper())
    session.add(row)
    audit(session, row.id, 'project_create', None, row.model_dump())
    return {'id': row.id}


def create_partner(session, data):
    row = Partner(id=identifier('PTN'), created_at=now(), normalized_name=''.join(data.name.casefold().split()), **data.model_dump(exclude={'command_id'}))
    session.add(row)
    audit(session, row.id, 'partner_create', None, row.model_dump())
    return {'id': row.id}


def create_request(session, data):
    get(session, Project, data.project_id)
    row = ShippingRequest(id=identifier('REQ'), created_at=now(), **data.model_dump(exclude={'command_id'}))
    session.add(row)
    audit(session, row.id, 'request_create', None, row.model_dump())
    return {'id': row.id}


def create_order(session, data):
    request = get(session, ShippingRequest, data.request_id)
    get(session, Partner, data.partner_id)
    if data.mode == 'express' and not data.carrier:
        raise DomainError('国际快递需填写实际快递品牌，例如 UPS；委托货代与实际承运商分别保存')
    bump(session, request, data.request_version)
    orders = session.exec(select(TransportOrder).where(TransportOrder.request_id == request.id, TransportOrder.status != 'cancelled')).all()
    allocated = sum(len(session.exec(select(HandlingUnit).where(HandlingUnit.order_id == order.id)).all()) for order in orders)
    if allocated + data.unit_count > request.unit_count:
        raise DomainError(f'本需求仅剩 {request.unit_count - allocated} 个运输单元可分配，不能超量委托')
    row = TransportOrder(id=identifier('SHP'), created_at=now(), **data.model_dump(exclude={'command_id', 'request_version', 'unit_count'}))
    session.add(row)
    session.flush()
    for i in range(data.unit_count):
        session.add(HandlingUnit(id=identifier('UNIT'), order_id=row.id, label=f'{UNIT_KINDS[request.unit_kind]} {i + 1:02}', kind=request.unit_kind))
    audit(session, row.id, 'order_create', None, {**row.model_dump(), 'unit_count': data.unit_count})
    return {'id': row.id}


def edit_master(session, model, key, data):
    row = get(session, model, key)
    before = row.model_dump()
    if model is Project and row.code != data.code.upper():
        raise DomainError('项目编号创建后保持不变，名称与负责人可以修改')
    if model is ShippingRequest:
        if row.project_id != data.project_id:
            raise DomainError('需求所属项目不能通过编辑更换')
        if session.exec(select(TransportOrder).where(TransportOrder.request_id == key)).first():
            raise DomainError('此需求已有委托历史，请新建补充需求以保留原始货物和路线')
    bump(session, row, data.version)
    for field, value in data.model_dump(exclude={'command_id', 'version'}).items():
        setattr(row, field, value.upper() if model is Project and field == 'code' else value)
    if model is Partner:
        row.normalized_name = ''.join(row.name.casefold().split())
    session.add(row)
    audit(session, key, model.__tablename__ + '_edit', before, row.model_dump())
    return {'id': key}


def add_reference(session, key, data):
    order = get(session, TransportOrder, key)
    active_order(order)
    bump(session, order, data.version)
    if data.unit_id and get(session, HandlingUnit, data.unit_id).order_id != key:
        raise DomainError('单号只能关联当前委托内的运输单元')
    old = None
    old_before = None
    if data.replaces_id:
        old = get(session, TransportReference, data.replaces_id)
        if old.order_id != key or old.status != 'active':
            raise DomainError('只能替换当前委托内的有效单号')
        if not data.reason:
            raise DomainError('更换单号必须记录原因')
        if old.kind != data.kind or old.unit_id != data.unit_id:
            raise DomainError('换单需保持单号类型与关联单件一致；其他单号请单独新增')
        old_before = old.model_dump()
        old.status = 'replaced'
        session.add(old)
    row = TransportReference(id=identifier('REF'), order_id=key, created_at=now(),
                             **data.model_dump(exclude={'command_id', 'version', 'value'}), value=data.value.upper())
    session.add(row)
    audit(session, key, 'reference_replace' if old else 'reference_add', old_before, row.model_dump())
    return {'id': row.id, 'order_id': key}


def add_action(session, key, data):
    order = get(session, TransportOrder, key)
    before = order.model_dump()
    action = data.action
    if action != 'reopen':
        active_order(order)
    bump(session, order, data.version)
    at = dt(data.occurred_at)
    if action != 'eta' and at > datetime.now(timezone.utc):
        raise DomainError('实际动作不能填写未来时间；预计到达请使用“更新预计”')
    all_events = session.exec(select(TransportEvent).where(TransportEvent.order_id == key)).all()
    physical = [e for e in all_events if e.kind in ['accept', 'dispatch', 'receive', 'reassign', 'close', 'reopen', 'cancel'] and e.classifier == 'ACT']
    if action in ['accept', 'dispatch', 'receive', 'reassign', 'cancel', 'close', 'reopen'] and physical and at < max(dt(e.occurred_at) for e in physical):
        raise DomainError('动作时间早于已有接单、发运或签收记录，请核对后再提交')
    if action != 'receive' and data.unit_ids:
        raise DomainError('仅按件签收时可以选择运输单元')
    if action != 'reassign' and data.partner_id:
        raise DomainError('仅更换合作伙伴时可以指定新的伙伴')
    if action == 'accept':
        if order.status != 'assigned':
            raise DomainError('只有待接单委托可以确认接单')
        order.status = 'accepted'
    elif action == 'dispatch':
        if order.status != 'accepted':
            raise DomainError('需先确认接单，才能登记实际发运')
        order.status = 'in_transit'
    elif action == 'receive':
        if order.status not in ['in_transit', 'partial_delivered']:
            raise DomainError('只有已发运的委托可以登记签收')
        if not data.receiver or not data.unit_ids or len(set(data.unit_ids)) != len(data.unit_ids):
            raise DomainError('请选择未签收单件并填写签收人，不得重复选择')
        units = session.exec(select(HandlingUnit).where(HandlingUnit.order_id == key)).all()
        selected = [u for u in units if u.id in data.unit_ids]
        if len(selected) != len(data.unit_ids) or any(u.received_at for u in selected):
            raise DomainError('选择中包含其他委托的单件或已签收单件')
        for unit in selected:
            unit.received_at, unit.receiver = data.occurred_at, data.receiver
            session.add(unit)
        order.status = 'delivered' if all(u.received_at for u in units) else 'partial_delivered'
    elif action == 'eta':
        if order.status in ['delivered', 'closed']:
            raise DomainError('全部签收后无需更新预计到达时间')
        order.eta = data.occurred_at
    elif action == 'cancel':
        if order.status not in ['assigned', 'accepted']:
            raise DomainError('仅未发运委托可取消；发运后请登记异常跟进')
        req = get(session, ShippingRequest, order.request_id)
        bump(session, req, req.version)
        order.status = 'cancelled'
    elif action == 'reassign':
        if order.status not in ['assigned', 'accepted'] or not data.partner_id:
            raise DomainError('仅未发运委托可以更换合作伙伴')
        if data.partner_id == order.partner_id:
            raise DomainError('请选择不同的合作伙伴')
        get(session, Partner, data.partner_id)
        if session.exec(select(TransportReference).where(TransportReference.order_id == key, TransportReference.status == 'active')).first():
            raise DomainError('已有有效单号，先取消未发运委托并重新分配，避免将旧伙伴单号带给新伙伴')
        order.partner_id, order.status = data.partner_id, 'assigned'
    elif action == 'close':
        if order.status != 'delivered':
            raise DomainError('需全部单件签收后才能关单')
        if session.exec(select(TransportIssue).where(TransportIssue.order_id == key, TransportIssue.status == 'open')).first():
            raise DomainError('尚有未解决异常，请先记录处理结果')
        order.status = 'closed'
    elif action == 'reopen':
        if order.status != 'closed':
            raise DomainError('只有已关单委托可以重新打开；已取消委托需重新分配')
        order.status = 'delivered'
    event = TransportEvent(id=identifier('EVT'), order_id=key, kind=action,
                           classifier='EST' if action == 'eta' else 'NOTE' if action == 'note' else 'ACT',
                           occurred_at=data.occurred_at, recorded_at=now(), reported_by=data.reported_by, actor=session.info.get('actor', 'local-user'),
                           evidence=data.evidence, details={'unit_ids': data.unit_ids, 'receiver': data.receiver,
                           'from_status': before['status'], 'to_status': order.status,
                           'from_partner_id': before['partner_id'], 'to_partner_id': order.partner_id})
    session.add(order)
    session.add(event)
    audit(session, key, 'transport_' + action, before, {**order.model_dump(), 'event_id': event.id})
    return {'id': event.id, 'order_id': key}


def create_issue(session, key, data):
    order = get(session, TransportOrder, key)
    active_order(order)
    bump(session, order, data.version)
    row = TransportIssue(id=identifier('ISS'), order_id=key, title=data.title, owner=data.owner, created_at=now())
    session.add(row)
    audit(session, key, 'transport_issue_create', None, row.model_dump())
    return {'id': row.id, 'order_id': key}


def resolve_issue(session, key, issue_id, data):
    order = get(session, TransportOrder, key)
    active_order(order)
    issue = get(session, TransportIssue, issue_id)
    if issue.order_id != key or issue.status != 'open':
        raise DomainError('只能处理当前委托内未解决的异常')
    bump(session, order, data.version)
    before = issue.model_dump()
    issue.status, issue.resolution, issue.resolved_at = 'resolved', data.resolution, now()
    session.add(issue)
    audit(session, key, 'transport_issue_resolve', before, issue.model_dump())
    return {'id': issue.id, 'order_id': key}


def export_records(session):
    return {name: [row.model_dump() for row in session.exec(select(model)).all()] for name, model in PROJECT_TABLES.items()}


def overview(session, data=None):
    data = export_records(session) if data is None else data
    projects = {r['id']: r for r in data['projects']}
    partners = {r['id']: r for r in data['partners']}
    requests = {r['id']: r for r in data['requests']}
    for order in data['orders']:
        request = requests[order['request_id']]
        units = [u for u in data['units'] if u['order_id'] == order['id']]
        refs = [r for r in data['references'] if r['order_id'] == order['id'] and r['status'] == 'active']
        issues = [i for i in data['issues'] if i['order_id'] == order['id'] and i['status'] == 'open']
        order.update(project_id=request['project_id'], project_name=projects[request['project_id']]['name'],
                     project_code=projects[request['project_id']]['code'], partner_name=partners[order['partner_id']]['name'],
                     request_title=request['title'], origin=request['origin'], destination=request['destination'],
                     unit_count=len(units), received_count=sum(bool(u['received_at']) for u in units),
                     references=refs, open_issues=len(issues), requested_delivery=request['requested_delivery'])
    for request in data['requests']:
        orders = [o for o in data['orders'] if o['request_id'] == request['id'] and o['status'] != 'cancelled']
        request.update(allocated_count=sum(o['unit_count'] for o in orders), received_count=sum(o['received_count'] for o in orders),
                       project_name=projects[request['project_id']]['name'])
    for project in data['projects']:
        requests_for = [r for r in data['requests'] if r['project_id'] == project['id']]
        orders = [o for o in data['orders'] if o['project_id'] == project['id'] and o['status'] != 'cancelled']
        project.update(request_count=len(requests_for), order_count=len(orders), open_issues=sum(o['open_issues'] for o in orders),
                       unallocated=sum(r['unit_count'] - r['allocated_count'] for r in requests_for),
                       completed_count=sum(o['status'] in ['delivered', 'closed'] for o in orders))
    data['orders'].sort(key=lambda r: r['created_at'], reverse=True)
    data['projects'].sort(key=lambda r: r['created_at'], reverse=True)
    data.update(mode=session.info['mode'], generated_at=now(), capability='local_internal_foundation',
                labels={'modes': MODES, 'states': STATES, 'units': UNIT_KINDS, 'references': REF_KINDS, 'events': EVENT_NAMES})
    return data


def detail(session, key):
    order = get(session, TransportOrder, key)
    request = get(session, ShippingRequest, order.request_id)
    audits = session.exec(select(Audit).where(Audit.entity_id == key)).all()
    return {'order': order.model_dump(), 'request': request.model_dump(),
            'project': get(session, Project, request.project_id).model_dump(),
            'partner': get(session, Partner, order.partner_id).model_dump(),
            **{name: [r.model_dump() for r in session.exec(select(model).where(model.order_id == key)).all()]
               for name, model in [('units', HandlingUnit), ('references', TransportReference), ('events', TransportEvent), ('issues', TransportIssue)]},
            'audit': [a.model_dump() for a in sorted(audits, key=lambda x: x.occurred_at, reverse=True)]}


def router(session_dep):
    routes = APIRouter(prefix='/api/project-logistics', tags=['project-logistics'])

    @routes.get('')
    def listing(session: Session = Depends(session_dep)):
        return overview(session)

    @routes.get('/orders/{key}')
    def order_detail(key: str, session: Session = Depends(session_dep)):
        return detail(session, key)

    @routes.post('/projects')
    def project_create(data: ProjectInput, session: Session = Depends(session_dep)):
        return command(session, 'project', data, lambda: create_project(session, data))

    @routes.post('/partners')
    def partner_create(data: PartnerInput, session: Session = Depends(session_dep)):
        return command(session, 'partner', data, lambda: create_partner(session, data))

    @routes.post('/requests')
    def request_create(data: RequestInput, session: Session = Depends(session_dep)):
        return command(session, 'request', data, lambda: create_request(session, data))

    @routes.post('/orders')
    def order_create(data: OrderInput, session: Session = Depends(session_dep)):
        return command(session, 'order', data, lambda: create_order(session, data))

    @routes.put('/projects/{key}')
    def project_edit(key: str, data: ProjectEdit, session: Session = Depends(session_dep)):
        return command(session, key + '/edit', data, lambda: edit_master(session, Project, key, data))

    @routes.put('/partners/{key}')
    def partner_edit(key: str, data: PartnerEdit, session: Session = Depends(session_dep)):
        return command(session, key + '/edit', data, lambda: edit_master(session, Partner, key, data))

    @routes.put('/requests/{key}')
    def request_edit(key: str, data: RequestEdit, session: Session = Depends(session_dep)):
        return command(session, key + '/edit', data, lambda: edit_master(session, ShippingRequest, key, data))

    @routes.post('/orders/{key}/references')
    def reference_create(key: str, data: ReferenceInput, session: Session = Depends(session_dep)):
        return command(session, key + '/reference', data, lambda: add_reference(session, key, data))

    @routes.post('/orders/{key}/actions')
    def action_create(key: str, data: ActionInput, session: Session = Depends(session_dep)):
        return command(session, key + '/action', data, lambda: add_action(session, key, data))

    @routes.post('/orders/{key}/issues')
    def issue_create(key: str, data: IssueInput, session: Session = Depends(session_dep)):
        return command(session, key + '/issue', data, lambda: create_issue(session, key, data))

    @routes.post('/orders/{key}/issues/{issue_id}/resolve')
    def issue_resolve(key: str, issue_id: str, data: ResolveInput, session: Session = Depends(session_dep)):
        return command(session, key + '/issue/' + issue_id, data, lambda: resolve_issue(session, key, issue_id, data))

    return routes


def initialize_projects():
    """Additive schema v2; existing sea-import rows are never inferred into projects."""
    for mode, engine in ENGINES.items():
        with Session(engine) as session:
            if not session.get(Migration, 2):
                session.add(Migration(version=2, applied_at=now()))
            if not session.get(Setting, 'project-logistics-v1'):
                if mode == 'demo':
                    seed_demo(session)
                session.add(Setting(id='project-logistics-v1', data={'at': now(), 'mode': mode}))
            session.commit()


def seed_demo(session):
    """Fictional examples, created once in demo only. No carrier queries."""
    stamp = datetime.now(timezone.utc)
    expected = (stamp + timedelta(days=7)).date().isoformat()
    common = {'command_id': 'initial-demo-seed'}
    partner_ids = []
    for name, kind, contact in [('远帆货代（模拟）', 'forwarder', '陈经理（模拟）'), ('启航物流（模拟）', 'forwarder', '周经理（模拟）'), ('UPS 渠道（模拟）', 'express', '渠道联系人（模拟）')]:
        partner_ids.append(create_partner(session, PartnerInput(**common, name=name, kind=kind, contact=contact))['id'])
    for index, (code, name, owner, destination) in enumerate([
        ('DEMO-NEO', '德国实验室设备交付', '林晓（模拟）', '德国 · 慕尼黑实验室'),
        ('DEMO-ARC', '日本展会样品运输', '张禾（模拟）', '日本 · 东京会展中心'),
        ('DEMO-WAVE', '美国售后备件补货', '李沐（模拟）', '美国 · 洛杉矶服务中心'),
    ]):
        project_id = create_project(session, ProjectInput(**common, code=code, name=name, owner=owner, department='项目交付组', note='虚构演示项目，用于练习；未连接真实业务。'))['id']
        session.flush()
        request_id = create_request(session, RequestInput(**common, project_id=project_id, title=['首批设备与配件', '展会样品', '紧急备件'][index], cargo=['设备附件、测试模组', '展示样品', '设备备件'][index], unit_kind='package', unit_count=[4, 3, 2][index], origin='中国 · 东莞', destination=destination, requested_delivery=expected, owner=owner))['id']
        session.flush()
        if index == 2:
            continue
        order_id = create_order(session, OrderInput(**common, request_id=request_id, request_version=1, partner_id=partner_ids[index], mode=['air', 'express'][index], carrier=['航空承运商待确认', 'UPS'][index], owner=owner, unit_count=2))['id']
        session.flush()
        order = get(session, TransportOrder, order_id)
        add_reference(session, order_id, ReferenceInput(**common, version=order.version, kind='tracking' if index else 'house', issuer='UPS（模拟）' if index else '远帆货代（模拟）', value=f'DEMO-REF-{index + 1:03}'))
        session.flush()
        for action, hours in [('accept', 30), ('dispatch', 24)]:
            add_action(session, order_id, ActionInput(**common, version=order.version, action=action, occurred_at=(stamp - timedelta(hours=hours)).isoformat(), reported_by='演示来源', evidence='虚构业务动作，用于观察流程'))
            session.flush()
        if index == 0:
            unit = session.exec(select(HandlingUnit).where(HandlingUnit.order_id == order_id)).first()
            add_action(session, order_id, ActionInput(**common, version=order.version, action='receive', occurred_at=(stamp - timedelta(hours=2)).isoformat(), unit_ids=[unit.id], receiver='演示收货人', reported_by='演示来源', evidence='模拟第一件已签收，第二件仍在运输'))
            session.flush()
            create_issue(session, order_id, IssueInput(**common, version=order.version, title='第二件预计晚到，需要确认交付安排（模拟）', owner=owner))
            session.flush()
        add_action(session, order_id, ActionInput(**common, version=order.version, action='eta', occurred_at=(stamp + timedelta(days=2)).isoformat(), reported_by='演示来源', evidence='演示预计时间，不代表实际到达'))
        session.flush()
