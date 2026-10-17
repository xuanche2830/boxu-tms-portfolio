"""Every resource read, write, aggregate and export passes this server policy."""
from fastapi import HTTPException
from sqlmodel import select
from . import project_logistics as business
from .collab_models import Grant, Organization
from .project_models import PROJECT_TABLES, Project, Partner, ShippingRequest, TransportOrder, HandlingUnit

PARTNER_ACTIONS = {'accept', 'dispatch', 'eta', 'note'}


def user(session):
    return session.info['user']


def owner_only(session):
    if user(session).role != 'owner':
        raise HTTPException(403, '此操作需要企业负责人权限')


def internal_only(session):
    if user(session).role not in ['owner', 'employee']:
        raise HTTPException(403, '此操作需要企业内部授权')


def grants(session, kind):
    return set(session.exec(select(Grant.resource_id).where(Grant.user_id == user(session).id, Grant.kind == kind)).all())


def project_access(session, key):
    internal_only(session)
    if user(session).role != 'owner' and key not in grants(session, 'project'):
        raise HTTPException(404, '记录不存在或没有访问权限')
    return business.get(session, Project, key)


def order_access(session, key):
    row = session.get(TransportOrder, key)
    if not row:
        raise HTTPException(404, '记录不存在或没有访问权限')
    if user(session).role == 'partner':
        org = session.get(Organization, user(session).organization_id)
        if key not in grants(session, 'order') or org.partner_id != row.partner_id or row.status == 'cancelled':
            raise HTTPException(404, '记录不存在或没有访问权限')
    else:
        req = business.get(session, ShippingRequest, row.request_id)
        project_access(session, req.project_id)
    return row


def allowed_actions(session, order):
    choices = {'assigned': ['accept', 'cancel', 'reassign'], 'accepted': ['dispatch', 'cancel', 'reassign'],
               'in_transit': ['receive'], 'partial_delivered': ['receive'], 'delivered': ['close'],
               'closed': ['reopen'], 'cancelled': []}[order.status]
    if order.status not in ['closed', 'cancelled']:
        choices += ['note']
        if order.status != 'delivered':
            choices += ['eta']
    return [a for a in choices if user(session).role != 'partner' or a in PARTNER_ACTIONS]


def event_visible(session, row):
    # Internal follow-up notes are not shared. Operational evidence is shared with the assigned partner.
    return user(session).role != 'partner' or row.get('kind') != 'note' or row.get('actor') == user(session).id


def sanitize(session, data):
    if user(session).role != 'partner':
        return data
    for row in data.get('projects', []):
        row.update(owner='', department='', note='')
    for row in data.get('requests', []):
        own_orders = {o['id'] for o in data['orders'] if o['request_id'] == row['id'] and o['status'] != 'cancelled'}
        row.update(owner='', note='', unit_count=sum(u['order_id'] in own_orders for u in data['units']))
    for row in data.get('orders', []):
        row.update(owner='', note='')
    for row in data.get('partners', []):
        row['note'] = ''
    partner_by_order = {o['id']: o['partner_id'] for o in data['orders']}
    data['events'] = [e for e in data.get('events', []) if event_visible(session, e) and
                      e['kind'] not in ['reassign', 'cancel'] and
                      e.get('details', {}).get('from_partner_id') in [None, partner_by_order.get(e['order_id'])]]
    for event in data['events']:
        event['details'] = {key: value for key, value in event.get('details', {}).items()
                            if key in ['unit_ids', 'receiver', 'from_status', 'to_status']}
    return data


def scoped_records(session):
    role = user(session).role
    if role == 'owner':
        return business.export_records(session)
    if role == 'employee':
        project_ids = grants(session, 'project')
        requests = session.exec(select(ShippingRequest).where(ShippingRequest.project_id.in_(project_ids))).all()
        request_ids = {r.id for r in requests}
        orders = session.exec(select(TransportOrder).where(TransportOrder.request_id.in_(request_ids))).all()
        partners = session.exec(select(Partner)).all()
    else:
        org = session.get(Organization, user(session).organization_id)
        orders = session.exec(select(TransportOrder).where(TransportOrder.id.in_(grants(session, 'order')),
                             TransportOrder.partner_id == org.partner_id, TransportOrder.status != 'cancelled')).all()
        requests = session.exec(select(ShippingRequest).where(ShippingRequest.id.in_({o.request_id for o in orders}))).all()
        project_ids = {r.project_id for r in requests}
        partners = session.exec(select(Partner).where(Partner.id == org.partner_id)).all()
    projects = session.exec(select(Project).where(Project.id.in_(project_ids))).all()
    result = {k: [r.model_dump() for r in rows] for k, rows in [('projects', projects), ('partners', partners), ('requests', requests), ('orders', orders)]}
    order_ids = {o.id for o in orders}
    for key in ['units', 'references', 'events', 'issues']:
        model = PROJECT_TABLES[key]
        result[key] = [r.model_dump() for r in session.exec(select(model).where(model.order_id.in_(order_ids))).all()]
    return sanitize(session, result)


def capabilities(session):
    return {'collaboration': True, 'internal': user(session).role != 'partner', 'manage_partners': user(session).role == 'owner'}


def overview(session):
    return {**business.overview(session, scoped_records(session)), 'access': capabilities(session)}


def detail(session, key):
    order = order_access(session, key)
    result = business.detail(session, key)
    if user(session).role == 'partner':
        records = {k: [result[k[:-1]]] for k in ['projects', 'requests', 'orders', 'partners']}
        records.update(units=result['units'], events=result['events'])
        sanitize(session, records)
        result['events'] = records['events']
        result['audit'] = []
    result['access'] = {**capabilities(session), 'actions': allowed_actions(session, order)}
    return result
