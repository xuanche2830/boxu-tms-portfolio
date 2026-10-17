from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select
from .models import Audit, Deadline, ExceptionRecord, Milestone, Migration, Release, Setting, Shipment, Source, Task, Trip

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / 'reference'
DATA = Path(os.environ.get('TMS_DATA_DIR', str(ROOT / 'data'))).resolve()
ENGINES = {}
MODELS = {'shipments': Shipment, 'container_trips': Trip, 'milestone_events': Milestone,
          'release_conditions': Release, 'deadlines': Deadline, 'pickup_tasks': Task,
          'exceptions': ExceptionRecord, 'sources': Source}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix: str) -> str:
    return prefix + '-' + uuid4().hex[:12]


def make_row(model, data):
    fields = {k: data[k] for k in model.model_fields if k != 'data' and k in data}
    return model(**fields, data=data)


def audit(session: Session, entity_id: str, action: str, before, after, batch_id=None):
    session.add(Audit(id=identifier('AU'), entity_id=entity_id, occurred_at=now(), action=action,
                      data={'actor': session.info.get('actor', 'local-user'), 'before': before, 'after': after, 'import_batch_id': batch_id}))


def initialize():
    DATA.mkdir(exist_ok=True)
    for mode in ['demo', 'workspace']:
        engine = create_engine(f'sqlite:///{(DATA / (mode + ".sqlite")).as_posix()}', connect_args={'check_same_thread': False, 'timeout': 20})
        @event.listens_for(engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA busy_timeout=20000')
        ENGINES[mode] = engine
        # Migration v1: indexed relations + JSON payloads retain the frozen field contract.
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            if not session.get(Migration, 1):
                session.add(Migration(version=1, applied_at=now()))
            if not session.get(Setting, 'initialized'):
                if mode == 'demo':
                    fixture = json.loads((REFERENCE / 'demo-fixture.json').read_text(encoding='utf-8'))
                    for key in ['sources', 'shipments', 'container_trips', 'milestone_events', 'release_conditions', 'deadlines', 'pickup_tasks', 'exceptions']:
                        for item in fixture[key]:
                            data = dict(item)
                            if key == 'container_trips':
                                data.pop('physical_stage', None)
                                data.pop('readiness', None)
                            if key == 'pickup_tasks':
                                data['action_stage'] = next(t['physical_stage'] for t in fixture['container_trips'] if t['id'] == data['container_trip_id'])
                            session.add(make_row(MODELS[key], data))
                        session.flush()
                    session.add(Setting(id='clock', data={'as_of': fixture['as_of'], 'kind': 'fixed_demo'}))
                    audit(session, 'demo-seed', 'initialize', None, {'fixture_version': fixture['version'], 'containers': 18})
                else:
                    session.add(Setting(id='clock', data={'as_of': None, 'kind': 'live'}))
                session.add(Setting(id='initialized', data={'at': now(), 'mode': mode}))
            # Bind saved next-action text to its business context. Existing records get
            # this additive JSON field once; later condition/deadline changes invalidate it.
            from .domain import build_view
            rows = {r['id']: r for r in build_view(snapshot(session), observation(session), mode)}
            for task in session.exec(select(Task)).all():
                if not task.data.get('action_context') and task.container_trip_id in rows:
                    task.data = {**task.data, 'action_context': rows[task.container_trip_id]['action_context']}
            session.commit()


def snapshot(session: Session):
    return {key: [row.data for row in session.exec(select(model)).all()] for key, model in MODELS.items()}


def observation(session: Session) -> str:
    setting = session.get(Setting, 'clock')
    return setting.data.get('as_of') or now()
