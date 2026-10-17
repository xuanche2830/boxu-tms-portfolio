from __future__ import annotations

import json
import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo
from .db import REFERENCE

DICTIONARY = json.loads((REFERENCE / 'field-dictionary.json').read_text(encoding='utf-8'))
RULES = json.loads((REFERENCE / 'business-rules.json').read_text(encoding='utf-8'))
LOCATIONS = json.loads((REFERENCE / 'location-master.json').read_text(encoding='utf-8'))['records']
CONTRACT = json.loads((REFERENCE / 'import-contract.json').read_text(encoding='utf-8'))
ENUMS = DICTIONARY['enums']
RELEASES = ['customs', 'carrier', 'terminal', 'other_hold']
PHYSICAL = ['VESSEL_ARRIVAL', 'DISCHARGED', 'PORT_GATE_OUT', 'WAREHOUSE_ARRIVAL', 'WAREHOUSE_SIGNED', 'EMPTY_RETURN']
STAGES = {'VESSEL_ARRIVAL': 'arrived', 'DISCHARGED': 'discharged', 'PORT_GATE_OUT': 'gate_out', 'WAREHOUSE_SIGNED': 'warehouse_signed', 'EMPTY_RETURN': 'empty_returned'}
TERMINATORS = {'port_storage': ('DISCHARGED', 'PORT_GATE_OUT'), 'demurrage': ('DISCHARGED', 'PORT_GATE_OUT'), 'detention': ('PORT_GATE_OUT', 'EMPTY_RETURN'), 'combined_dd': ('DISCHARGED', 'EMPTY_RETURN')}


class DomainError(ValueError):
    pass


def dt(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError('timezone')
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise DomainError('时间必须是带时区的ISO8601，例如2026-10-13T09:00:00+08:00')


def day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise DomainError('日期必须是YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DomainError('日期不存在')


def require(data, keys):
    missing = [k for k in keys if data.get(k) is None or str(data.get(k)).strip() == '']
    if missing:
        raise DomainError('缺少必填字段：' + '、'.join(missing))
    wrong = [k for k in keys if k not in ['is_demo', 'is_transshipment'] and not isinstance(data.get(k), str)]
    if wrong:
        raise DomainError('以下字段必须填写文本：' + '、'.join(wrong))


def one_of(data, key, choices):
    if data.get(key) not in choices:
        raise DomainError(f'{key}必须是：' + '、'.join(choices))


def timezone_valid(value):
    try:
        ZoneInfo(value)
    except Exception:
        raise DomainError('业务时区无效')


def container_valid(number: str, mode: str):
    if mode == 'demo':
        if not re.fullmatch(r'DEMO-[A-Za-z0-9-]+', number):
            raise DomainError('演示库柜号必须使用DEMO-前缀')
        return
    if not re.fullmatch(r'[A-Z]{3}[UJZ]\d{7}', number):
        raise DomainError('柜号应为ISO6346的4个字母和7位数字')
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    values = [n for n in range(10, 39) if n % 11 != 0]
    codes = dict(zip(letters, values))
    expected = sum((int(c) if c.isdigit() else codes[c]) * (2 ** i) for i, c in enumerate(number[:10])) % 11 % 10
    if expected != int(number[-1]):
        raise DomainError('柜号校验位不符，请核对原始单据')


def port_valid(code):
    entry = next((x for x in LOCATIONS if x['unlocode'] == code), None)
    if not entry or not entry['function'].startswith('1'):
        raise DomainError('本版地点库已核对海港CNYTN、CNNSA；其他地点须先扩充已核对主数据')


def clean(data: dict[str, Any]):
    for key, value in data.items():
        if key in ['is_demo', 'is_transshipment']:
            if value is not None and not isinstance(value, bool):
                raise DomainError(key + '必须为true或false')
        elif value is not None and not isinstance(value, str):
            raise DomainError(key + '必须填写文本；请核对原始值及格式')
    return {k: (v.strip() or None) if isinstance(v, str) else v for k, v in data.items()}


def actual_events(state, trip, as_of):
    accepted = []
    for e in state['milestone_events']:
        if e['shipment_id'] != trip['shipment_id'] or e.get('validity', 'accepted') != 'accepted':
            continue
        if e.get('container_trip_id') != trip['id'] and not (e.get('container_trip_id') is None and e['milestone'] in ['VESSEL_ARRIVAL', 'VESSEL_DEPARTURE']):
            continue
        if e['classifier'] == 'ACT' and dt(e['occurred_at']) <= dt(as_of):
            accepted.append(e)
    # Imported normalized events still need business guards; invalid physical data is quarantined on write.
    return accepted


def derive_trip(state, trip, as_of, mode):
    ship = next(s for s in state['shipments'] if s['id'] == trip['shipment_id'])
    events = actual_events(state, trip, as_of)
    milestones = {}
    for e in sorted(events, key=lambda e: dt(e['occurred_at'])):
        milestones.setdefault(e['milestone'], e)
    stage = 'in_transit'
    for code in ['VESSEL_ARRIVAL', 'DISCHARGED', 'PORT_GATE_OUT', 'WAREHOUSE_SIGNED', 'EMPTY_RETURN']:
        if code in milestones:
            stage = STAGES[code]
    release_history = [r for r in state['release_conditions'] if r['container_trip_id'] == trip['id']]
    conditions = {}
    for kind in RELEASES:
        relevant = [r for r in release_history if r['kind'] == kind and (not r.get('confirmed_at') or dt(r['confirmed_at']) <= dt(as_of))]
        conditions[kind] = max(relevant, key=lambda r: r.get('revision', 1), default={'kind': kind, 'status': 'unknown', 'evidence': None, 'confirmed_at': None})
    if 'PORT_GATE_OUT' in milestones:
        readiness = 'pickup_completed'
    elif 'DISCHARGED' not in milestones:
        readiness = 'not_applicable'
    elif any(c['status'] == 'blocked' for c in conditions.values()):
        readiness = 'blocked'
    elif all(c['status'] == 'clear' for c in conditions.values()):
        readiness = 'ready'
    else:
        readiness = 'pending_confirmation'
    task = next((x for x in state['pickup_tasks'] if x['container_trip_id'] == trip['id'] and x.get('status') != 'cancelled'), None)
    clocks = []
    for d in [x for x in state['deadlines'] if x['container_trip_id'] == trip['id']]:
        clock = dict(d)
        start = milestones.get(d['start_milestone'])
        end = milestones.get(d['end_milestone'])
        zone = ZoneInfo(d.get('timezone') or ship['timezone'])
        due = d.get('due_date') if d['precision'] == 'date' else d.get('due_at')
        state_code = 'not_started'
        remaining = None
        if start:
            if not due:
                state_code = 'ended_unconfirmed' if end else 'pending_confirmation'
            elif d['precision'] == 'date':
                remaining = (day(due) - dt(as_of).astimezone(zone).date()).days
                if end:
                    state_code = 'ended_late' if dt(end['occurred_at']).astimezone(zone).date() > day(due) else 'ended_on_time'
                else:
                    state_code = 'overdue' if remaining < 0 else 'near' if remaining <= RULES['near_calendar_days'] else 'safe'
            else:
                remaining = (dt(due) - dt(as_of)).total_seconds() / 86400
                state_code = ('ended_late' if dt(end['occurred_at']) > dt(due) else 'ended_on_time') if end else ('overdue' if remaining < 0 else 'near' if remaining <= 1 else 'safe')
        clock.update(state=state_code, remaining_days=remaining, start_at=start['occurred_at'] if start else None, end_at=end['occurred_at'] if end else None)
        clocks.append(clock)
    # Every started trip needs storage and one return clock; omissions never become "safe".
    needed = ['port_storage']
    kinds = {c['kind'] for c in clocks}
    if 'combined_dd' not in kinds and 'detention' not in kinds:
        needed.append('combined_dd')
    for kind in needed:
        if kind not in kinds:
            a, b = TERMINATORS[kind]
            clocks.append({'id': None, 'container_trip_id': trip['id'], 'kind': kind, 'precision': 'date', 'due_date': None, 'due_at': None, 'basis_kind': None, 'evidence': None, 'state': 'ended_unconfirmed' if b in milestones else 'pending_confirmation' if a in milestones else 'not_started', 'remaining_days': None, 'start_at': milestones[a]['occurred_at'] if a in milestones else None, 'end_at': milestones[b]['occurred_at'] if b in milestones else None, 'start_milestone': a, 'end_milestone': b})
    alerts = []
    if 'VESSEL_ARRIVAL' in milestones and 'PORT_GATE_OUT' not in milestones:
        alerts.append('actual_arrived_not_picked')
    if readiness == 'ready' and not (task and task.get('appointment_at')):
        alerts.append('ready_unappointed')
    confirmed = [c for c in clocks if c.get('basis_kind') == 'confirmed' or (mode == 'demo' and c.get('basis_kind') == 'synthetic')]
    for status in ['near', 'overdue']:
        if any(c['state'] == status for c in confirmed):
            alerts.append('confirmed_' + status)
        if any(c['state'] == status and c.get('basis_kind') == 'reference' for c in clocks):
            alerts.append('reference_' + status)
    unknown_release = 'DISCHARGED' in milestones and 'PORT_GATE_OUT' not in milestones and any(c['status'] == 'unknown' for c in conditions.values())
    if unknown_release or any(c['state'] == 'pending_confirmation' and not c.get('end_at') for c in clocks):
        alerts.append('pending_confirmation')
    if 'WAREHOUSE_SIGNED' in milestones and 'EMPTY_RETURN' not in milestones:
        alerts.append('delivered_not_returned')
    exceptions = [e for e in state['exceptions'] if e['container_trip_id'] == trip['id']]
    quarantined = [e for e in state['milestone_events'] if e['shipment_id'] == trip['shipment_id'] and (e.get('container_trip_id') == trip['id'] or (e.get('container_trip_id') is None and e['milestone'] in ['VESSEL_ARRIVAL', 'VESSEL_DEPARTURE'])) and e.get('validity') == 'quarantined']
    if quarantined:
        alerts.append('data_conflict')
    eta_events = [e for e in state['milestone_events'] if e['shipment_id'] == ship['id'] and (e.get('container_trip_id') in [None, trip['id']]) and e['milestone'] == 'VESSEL_ARRIVAL' and e['classifier'] == 'EST' and e.get('validity', 'accepted') == 'accepted']
    def eta_key(e):
        source = next((s for s in state['sources'] if s['id'] == e['source_id']), {})
        return (int(source.get('priority', 0)), dt(e.get('source_created_at') or e['received_at']), dt(e['received_at']))
    eta = max(eta_events, key=eta_key, default=None)
    complete = all(c in milestones for c in ['PORT_GATE_OUT', 'WAREHOUSE_SIGNED', 'EMPTY_RETURN']) and not quarantined and not any(e['status'] not in ['resolved', 'waived'] for e in exceptions)
    if stage == 'empty_returned':
        action = '处理未结异常后关单' if not complete else '核对记录后关单'
    elif stage == 'warehouse_signed':
        action = '安排还空柜并获取回单'
    elif stage == 'gate_out':
        action = '跟进到仓与签收'
    elif readiness == 'blocked':
        action = '解除提柜限制'
    elif readiness == 'ready':
        action = '执行提柜预约' if task and task.get('appointment_at') else '分派拖车并预约提柜'
    elif stage == 'discharged':
        action = '跟进可提条件确认'
    elif stage == 'arrived':
        action = '确认卸船计划，不开始免费期计时'
    else:
        action = '核实船期，等待实际到港'
    if task:
        task = dict(task)
        task['status'] = 'empty_returned' if 'EMPTY_RETURN' in milestones else 'delivered' if 'WAREHOUSE_SIGNED' in milestones else 'picked_up' if 'PORT_GATE_OUT' in milestones else 'scheduled' if task.get('appointment_at') else 'assigned' if task.get('owner') and task.get('haulier') else 'draft'
    context = hashlib.sha256(json.dumps({'stage': stage, 'readiness': readiness,
        'clocks': [{k: c.get(k) for k in ['kind', 'due_date', 'due_at', 'basis_kind', 'state']} for c in sorted(clocks, key=lambda c:c['kind'])],
        'open_exceptions': sorted(e['id'] for e in exceptions if e['status'] not in ['resolved', 'waived']),
        'quarantined': sorted(e['id'] for e in quarantined)}, sort_keys=True).encode()).hexdigest()
    custom_action = (task or {}).get('next_action') if (task or {}).get('action_stage') == stage and (task or {}).get('action_context') == context else None
    action = custom_action or action
    if stage == 'warehouse_signed' and not custom_action:
        return_clock = next((c for c in clocks if c['kind'] in ['detention', 'combined_dd']), None)
        if return_clock and (return_clock.get('due_date') or return_clock.get('due_at')):
            when = return_clock.get('due_date') or return_clock.get('due_at')
            action = ('按独立还柜期限' if return_clock['kind'] == 'detention' else '按合并还柜期限') + when + '安排还空柜并取得回单'
    if quarantined:
        action = '先复核隔离节点，再继续执行与关单'
    if stage == 'empty_returned' and any(e['status'] not in ['resolved', 'waived'] for e in exceptions):
        action = '先处理异常，不能直接关单'
    if readiness == 'blocked' and not custom_action:
        action = '解除提柜限制'
    return {**trip, 'shipment': ship, 'physical_stage': stage, 'readiness': readiness, 'conditions': list(conditions.values()), 'deadlines': clocks, 'alerts': alerts, 'milestones': milestones, 'eta': eta, 'task': task, 'exceptions': exceptions, 'quarantined_events': quarantined, 'close_eligible': complete, 'next_action': action, 'action_context': context}


def build_view(state, as_of, mode):
    rows = [derive_trip(state, trip, as_of, mode) for trip in state['container_trips']]
    eligible = {}
    for ship in state['shipments']:
        group = [r for r in rows if r['shipment_id'] == ship['id']]
        eligible[ship['id']] = bool(group) and all(r['close_eligible'] for r in group)
    for r in rows:
        stored = r['shipment'].get('lifecycle', 'open')
        r['shipment_lifecycle'] = 'closed' if stored == 'closed' and eligible[r['shipment_id']] else 'needs_review' if stored == 'closed' else 'close_eligible' if eligible[r['shipment_id']] else 'open'
        if r['shipment_lifecycle'] == 'closed':
            r['next_action'] = '已关单，保留记录；需要更正时先重开'
        elif r['shipment_lifecycle'] == 'needs_review':
            r['next_action'] = '关单后资料需复核，请先重开处理'
        elif r['close_eligible'] and not eligible[r['shipment_id']]:
            r['next_action'] = '本柜完成，等待同票其余柜完成后整票关单'
    return rows


def validate_event(data, state, as_of):
    require(data, ['shipment_id', 'milestone', 'classifier', 'occurred_at', 'location', 'source_id', 'raw_reference'])
    one_of(data, 'milestone', ENUMS['milestone'])
    one_of(data, 'classifier', ENUMS['classifier'])
    occurred = dt(data['occurred_at'])
    if data.get('source_created_at'):
        dt(data['source_created_at'])
    if data['classifier'] == 'ACT' and occurred > dt(as_of):
        raise DomainError('实际节点晚于观察时刻，请先调整顶部观察时钟')
    trip = next((t for t in state['container_trips'] if t['id'] == data.get('container_trip_id')), None)
    if data.get('container_trip_id') and not trip:
        raise DomainError('本次柜子ID不存在，请核对节点关联')
    ship = next((s for s in state['shipments'] if s['id'] == data['shipment_id']), None)
    if not ship or (trip and trip['shipment_id'] != ship['id']):
        raise DomainError('运输批次或柜子关联不符')
    if data['milestone'] not in ['VESSEL_ARRIVAL', 'VESSEL_DEPARTURE', 'DOCUMENT_UPDATE', 'UNMAPPED'] and not trip:
        raise DomainError('设备与仓库节点必须关联有效柜子')
    if data['milestone'] in ['VESSEL_ARRIVAL', 'DISCHARGED', 'PORT_GATE_OUT'] and data['location'] != ship['pod_unlocode']:
        raise DomainError('该节点必须是本票目的港，不能将中转港操作计入进口到港提柜')
    if data['milestone'] in ['VESSEL_ARRIVAL', 'DISCHARGED'] and data.get('mode_of_transport') != 'VESSEL':
        raise DomainError('船到港与卸船必须明确运输方式为VESSEL')
    if data['milestone'] == 'DISCHARGED' and (data.get('empty_indicator') != 'LADEN' or data.get('is_transshipment') is not False):
        raise DomainError('进口卸船须为重柜LADEN，且明确不是中转')
    if data['milestone'] == 'PORT_GATE_OUT' and data.get('empty_indicator') != 'LADEN':
        raise DomainError('进口提柜出闸须为重柜LADEN')
    if data['milestone'] == 'EMPTY_RETURN':
        task = next((x for x in state['pickup_tasks'] if x['container_trip_id'] == trip['id']), None)
        if data.get('empty_indicator') != 'EMPTY' or not data.get('facility_id') or not task or task.get('empty_return_facility') != data.get('facility_id'):
            raise DomainError('还空柜需EMPTY标识并与任务指定还柜设施相符；先填写任务还柜地点')
    if data['milestone'] in ['WAREHOUSE_ARRIVAL', 'WAREHOUSE_SIGNED'] and data['location'] != trip['warehouse']:
        raise DomainError('仓库节点地点应匹配本柜目的仓')
    warnings = []
    targets = [trip] if trip else [t for t in state['container_trips'] if t['shipment_id'] == ship['id']] if data['milestone'] == 'VESSEL_ARRIVAL' else []
    for target in targets if data['classifier'] == 'ACT' and data['milestone'] in PHYSICAL else []:
        actual = actual_events(state, target, as_of)
        sequence = PHYSICAL.index(data['milestone'])
        for e in actual:
            if e['milestone'] not in PHYSICAL:
                continue
            pos = PHYSICAL.index(e['milestone'])
            if pos == sequence and dt(e['occurred_at']) != occurred:
                warnings.append('同类实际节点时间冲突，记录隔离待确认')
            if (pos < sequence and dt(e['occurred_at']) > occurred) or (pos > sequence and dt(e['occurred_at']) < occurred):
                warnings.append('节点时间顺序矛盾，记录隔离待确认')
        prerequisite = {'DISCHARGED': 'VESSEL_ARRIVAL', 'PORT_GATE_OUT': 'DISCHARGED', 'WAREHOUSE_ARRIVAL': 'PORT_GATE_OUT', 'WAREHOUSE_SIGNED': 'PORT_GATE_OUT', 'EMPTY_RETURN': 'WAREHOUSE_SIGNED'}.get(data['milestone'])
        if prerequisite and not any(e['milestone'] == prerequisite for e in actual):
            warnings.append('缺少实际前置节点' + prerequisite + '，记录隔离待确认')
    return list(dict.fromkeys(warnings))
