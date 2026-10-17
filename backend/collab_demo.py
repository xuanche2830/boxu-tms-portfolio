"""Synthetic training space. This module is called only against the dedicated demo database."""
import secrets
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from . import collab_auth as auth, project_logistics as business
from .collab_models import Grant, Organization, User
from .db import identifier, now
from .project_models import HandlingUnit, ShippingRequest, TransportOrder

DEMO_USERS = {'owner': 'DEMO-OWNER', 'employee': 'DEMO-EMPLOYEE', 'partner': 'DEMO-PARTNER'}


def seed(engine):
    with Session(engine) as session:
        if session.exec(select(User.id)).first():
            return  # Never overwrite exercises or identities on restart.
        org = Organization(id='DEMO-ORG', name='合成示例 · 澄川设备', kind='enterprise')
        session.add(org)
        session.flush()
        owner = User(id=DEMO_USERS['owner'], username='demo.owner', display_name='演示负责人', password_hash=auth.hash_password(secrets.token_urlsafe(32)), role='owner', organization_id=org.id, created_at=now())
        session.add(owner)
        session.flush()
        session.info.update(user=owner, actor=owner.id, mode='collaboration')
        partner_id = business.create_partner(session, business.PartnerInput(command_id='demo-partner-seed', name='合成示例 · 岭川货运', kind='forwarder', contact='演示联系人（非真实）', note='纯合成演示资料'))['id']
        project_id = business.create_project(session, business.ProjectInput(command_id='demo-project-seed', code='DEMO-TRAINING', name='合成演示 · 设备备件交付', owner='演示负责人', department='项目支持', note='所有公司、人员、运输及证据均为合成示例'))['id']
        session.flush()
        partner_org = Organization(id='DEMO-PARTNER-ORG', name='合成示例 · 岭川货运', kind='partner', partner_id=partner_id)
        session.add(partner_org)
        session.flush()
        for role, org_id in [('employee', org.id), ('partner', partner_org.id)]:
            session.add(User(id=DEMO_USERS[role], username='demo.' + role, display_name='演示项目员工' if role == 'employee' else '演示货代人员', password_hash=auth.hash_password(secrets.token_urlsafe(32)), role=role, organization_id=org_id, created_at=now()))
        session.flush()
        session.add(Grant(id=identifier('GRT'), user_id=DEMO_USERS['employee'], kind='project', resource_id=project_id, created_by=owner.id, created_at=now()))
        today = datetime.now(timezone.utc)
        base = today - timedelta(days=4)
        scenarios = [('设备配件首批', 0, False), ('维护工具补发', 1, False), ('预约变更案例', 2, True), ('分批到货案例', 3, False), ('交付复核案例', 4, False), ('历史交付案例', 5, False)]
        for number, (title, stage, has_issue) in enumerate(scenarios, 1):
            request_id = business.create_request(session, business.RequestInput(command_id=f'demo-request-{number:04}', project_id=project_id, title=title, cargo='合成样例：设备维护备件', unit_kind='package' if number % 2 else 'container', unit_count=3, origin='东莞演示仓' if number % 2 else '深圳演示装运点', destination='大阪演示收货点' if number % 2 else '横滨演示收货点', requested_delivery=(today + timedelta(days=2)).date().isoformat(), owner='演示项目员工', note='可在此练习；非真实运输'))['id']
            session.flush()
            order_id = business.create_order(session, business.OrderInput(command_id=f'demo-order-{number:06}', request_id=request_id, request_version=1, partner_id=partner_id, mode='express' if number % 2 else 'sea', carrier='合成快递渠道' if number % 2 else '合成海运渠道', owner='演示项目员工', unit_count=3, note='合成演示委托'))['id']
            session.flush()
            session.add(Grant(id=identifier('GRT'), user_id=DEMO_USERS['partner'], kind='order', resource_id=order_id, created_by=owner.id, created_at=now()))
            units = session.exec(select(HandlingUnit).where(HandlingUnit.order_id == order_id)).all()
            for step, action in enumerate(['accept', 'dispatch', 'receive', 'receive', 'close'][:stage]):
                order = session.get(TransportOrder, order_id)
                ids = [units[0].id] if step == 2 else [u.id for u in units[1:]] if step == 3 else []
                business.add_action(session, order_id, business.ActionInput(command_id=f'demo-action-{number}-{step:04}', version=order.version, action=action,
                    occurred_at=(base + timedelta(hours=step * 8)).isoformat(), reported_by='合成演示记录', evidence='演示证据：用于理解业务流程，不代表真实运输', unit_ids=ids, receiver='演示收货人' if ids else ''))
                session.flush()
            if stage >= 2:
                order = session.get(TransportOrder, order_id)
                if order.status != 'closed':
                    business.add_reference(session, order_id, business.ReferenceInput(command_id=f'demo-ref-{number:08}', version=order.version, kind='tracking' if number % 2 else 'house', issuer='合成演示渠道', value=f'DEMO-ONLY-{number:04}'))
                    session.flush()
            if has_issue:
                order = session.get(TransportOrder, order_id)
                business.create_issue(session, order_id, business.IssueInput(command_id='demo-issue-00001', version=order.version, title='合成异常：收货预约变更，待确认新的入场时间', owner='演示项目员工'))
        auth.log(session, owner.id, 'demo_seeded', {'synthetic': True, 'scenario_count': len(scenarios)})
        session.commit()
