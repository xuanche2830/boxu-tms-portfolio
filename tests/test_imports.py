"""HTTP regression for v0.10. Uses a disposable database and random loopback port."""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4
from openpyxl import Workbook
import acceptance_common as t


def encoded(text):
    return base64.b64encode(text.encode('utf-8-sig') if isinstance(text, str) else text).decode()


def csv_request(title, count='2', date='2026-12-15', extra=''):
    return '需求名称,货物,单元类型,数量,起点,终点,期望到货日,负责人,备注\r\n' + f'{title},合成备件,包裹,{count},东莞演示仓,大阪演示点,{date},合成人员,{extra}\r\n'


def upload(client, content, kind='requests', project='', filename='synthetic.csv', status=200):
    return client.post('/imports', dict(filename=filename, source_base64=encoded(content), kind=kind, project_id=project), status=status)


def save(client, batch, edit=None, status=200):
    rows = []
    for r in batch['rows']:
        row = {k: r[k] for k in ['row_number', 'include', 'reviewed', 'fields']}
        row['reviewed'] = True
        if edit:
            edit(row)
        rows.append(row)
    return client.put('/imports/' + batch['id'], {'version': batch['version'], 'rows': rows}, status=status)


def confirm(client, batch, status=200, version=None):
    return client.post('/imports/' + batch['id'] + '/confirm', {'version': batch['version'] if version is None else version, 'confirm': True}, status=status)


def requests(client):
    return client.get('/project-logistics')['requests']


def main():
    os.environ['TMS_COLLAB_DEMO'] = '0'
    t.REPORT = t.WORK / ('acceptance-v010-' + t.RUN + '.json')
    status = 'failed'
    process = None
    try:
        with t.LOG.open('w', encoding='utf-8') as log:
            process = t.boot(log)
            owner = t.Client()
            owner.identity = owner.post('/setup', {'username': 'import.owner', 'password': 'Synthetic-Owner-2026!', 'display_name': '合成测试负责人', 'company': '合成验收企业'})
            owner.post('/demo-login', {'role': 'owner'}, status=404)
            t.check('work process cookie name', sorted(c.name for c in owner.cookies), ['tms_collab_session'])
            anon = t.Client()
            anon.get('/imports', 401)
            partner = owner.post('/project-logistics/partners', t.command(name='合成测试货代', kind='forwarder', contact='不存在的测试联系人'))['id']
            users = {}
            clients = {}
            for role, name in [('employee', 'import.employee'), ('employee', 'import.other'), ('partner', 'import.partner')]:
                body = {'username': name, 'password': 'Synthetic-Initial-2026!', 'display_name': '合成测试成员', 'role': role}
                if role == 'partner':
                    body['partner_id'] = partner
                users[name] = owner.post('/users', body)['id']
                client = t.Client()
                client.login(name, 'Synthetic-Initial-2026!')
                client.change_password('Synthetic-Initial-2026!', 'Synthetic-Changed-2026!')
                clients[name] = client
            emp, other, freight = [clients[x] for x in ['import.employee', 'import.other', 'import.partner']]
            freight.get('/imports', 403)
            upload(freight, '项目编号,项目名称,负责人,部门\nT1,演示,负责人,部门', 'projects', status=403)
            upload(emp, '项目编号,项目名称,负责人,部门\nT1,演示,负责人,部门', 'projects', status=403)

            content = '项目编号,项目名称,负责人,部门,备注\r\nSYNTH-P1,合成项目一,测试负责人,测试部,口头说已发运\r\nSYNTH-P2,合成项目二,测试负责人,测试部,待核实\r\n'
            batch = upload(owner, content, 'projects')
            t.check('preview makes zero business projects', owner.get('/project-logistics')['projects'], [])
            t.check('remarks not silently promoted', batch['rows'][0]['fields']['note'], '')
            t.check('original remarks preserved', batch['rows'][0]['raw']['备注'], '口头说已发运')
            confirm(owner, batch, 422)
            same = upload(owner, content, 'projects')
            t.check('same source reopens batch', same['id'], batch['id'])
            t.check('same source flagged', same['duplicate_source'])
            batch = save(owner, batch)
            confirm(owner, batch, 409, version=batch['version'] + 1)
            confirmed = confirm(owner, batch)
            t.check('project import writes both', len(confirmed['result']), 2)
            t.check('confirm retry idempotent', confirm(owner, batch)['replayed'])
            project, second_project = [r['id'] for r in confirmed['result']]
            save(owner, batch, status=409)
            original = owner.get('/imports/' + batch['id'] + '/source')
            t.check('source bytes roundtrip', base64.b64decode(original['source_base64']), content.encode('utf-8-sig'))
            emp.get('/imports/' + batch['id'], 404)
            emp.get('/imports/' + batch['id'] + '/source', 404)
            upload(emp, csv_request('未授权需求'), project=project, status=404)
            grant = owner.post('/grants', {'user_id': users['import.employee'], 'kind': 'project', 'resource_id': project})['id']

            malformed = csv_request('待修正需求', '2托盘', '下周五', '猜测已签收')
            draft = upload(emp, malformed, project=project)
            t.check('invalid count/date visible', len(draft['rows'][0]['errors']), 2)
            t.check('employee list private to creator', len(emp.get('/imports')['batches']), 1)
            t.check('owner cannot inspect another private draft', owner.call('GET', '/imports/' + draft['id'])[0], 404)
            t.check('other employee sees no batches', other.get('/imports')['batches'], [])
            confirm(emp, draft, 422)
            draft = save(emp, draft, lambda r: r['fields'].update(unit_count='2', requested_delivery='2026-12-15'))
            t.check('corrected validation clear', draft['rows'][0]['errors'], [])
            t.check('correction leaves original row intact', draft['rows'][0]['raw']['数量'], '2托盘')
            confirmed_req = confirm(emp, draft)
            t.check('one request created after explicit confirm', len(requests(owner)), 1)
            t.check('import never creates events or orders', owner.get('/project-logistics')['orders'], [])
            fresh_same = upload(emp, csv_request('待修正需求', extra='改过文件名或附加备注'), project=project)
            t.check('changed source still detects existing request', any('已有相同需求' in e for e in fresh_same['rows'][0]['errors']))
            confirm(emp, save(emp, fresh_same), 422)

            mixed = csv_request('原子性好行') + '原子性坏行,备件,包裹,not-a-count,东莞,大阪,2026-12-15,测试人,\r\n'
            atomic = save(emp, upload(emp, mixed, project=project))
            before = len(requests(owner))
            confirm(emp, atomic, 422)
            t.check('invalid second row prevents first row writing', len(requests(owner)), before)
            atomic = save(emp, atomic, lambda r: r.update(include=False) if r['row_number'] == 3 else None)
            confirmed_atomic = confirm(emp, atomic)
            t.check('excluded row not written', len(confirmed_atomic['result']), 1)
            t.check('excluded source still retained', len(confirmed_atomic['rows']), 2)

            mapped = upload(emp, '业务主题,品名,包装,件数,发货地,收货地,交期,跟进人,散乱说明\n自定义表头,合成零件,托盘,4,东莞,东京,2026-12-16,测试员工,未确认口述\n', project=project)
            mapping = dict(title='业务主题', cargo='品名', unit_kind='包装', unit_count='件数', origin='发货地', destination='收货地', requested_delivery='交期', owner='跟进人', note='')
            mapped = emp.put('/imports/' + mapped['id'] + '/mapping', {'version': mapped['version'], 'mapping': mapping})
            t.check('custom headers map values', mapped['rows'][0]['fields']['title'], '自定义表头')
            t.check('custom mapping preserves unknown raw', mapped['rows'][0]['raw']['散乱说明'], '未确认口述')
            t.check('custom mapping requires fresh review', mapped['rows'][0]['reviewed'], False)
            t.check('custom mapping keeps notes blank unless selected', mapped['rows'][0]['fields']['note'], '')
            mapped = save(emp, mapped)
            stale = dict(mapped)
            mapped = emp.put('/imports/' + mapped['id'] + '/mapping', {'version': mapped['version'], 'mapping': mapping})
            confirm(emp, stale, 409)
            save(emp, stale, status=409)
            confirm(emp, save(emp, mapped))

            book = Workbook()
            sheet = book.active
            sheet.title = '合成需求'
            sheet.append(['需求名称', '货物', '单元类型', '数量', '起点', '终点', '期望到货日', '负责人', '备注'])
            sheet.append(['XLSX日期练习', '合成部件', '包裹', 3, '东莞', '大阪', __import__('datetime').date(2026, 12, 17), '测试员', '=1+1'])
            buffer = io.BytesIO()
            book.save(buffer)
            xlsx = upload(emp, buffer.getvalue(), project=project, filename='synthetic.xlsx')
            t.check('xlsx date normalized', xlsx['rows'][0]['fields']['requested_delivery'], '2026-12-17')
            t.check('xlsx formula retained only as raw', xlsx['rows'][0]['raw']['备注'], '=1+1')
            t.check('xlsx formula not evaluated', xlsx['rows'][0]['fields']['note'], '')
            confirm(emp, save(emp, xlsx))
            book.create_sheet('不应静默遗漏')
            buffer = io.BytesIO(); book.save(buffer)
            upload(emp, buffer.getvalue(), project=project, filename='multi.xlsx', status=422)

            upload(emp, b'x' * 60001, project=project, status=422)
            upload(emp, '需求名称,需求名称\n重复,重复', project=project, status=422)
            upload(emp, '需求名称,\n标题,空表头', project=project, status=422)
            upload(emp, '需求名称\n' + '\n'.join('行' for _ in range(101)), project=project, status=422)
            upload(emp, b'not-a-zip-file', project=project, filename='broken.xlsx', status=422)
            upload(emp, 'anything', project=project, filename='data.xls', status=422)
            emp.post('/imports', dict(filename='bad.csv', source_base64='not base64', kind='requests', project_id=project), status=422)

            repeated = upload(owner, '项目编号,项目名称,负责人,部门\nCASE-CODE,大写,人,部\ncase-code,小写,人,部', 'projects')
            t.check('project codes duplicate ignoring case before commit', any('相同记录' in e for e in repeated['rows'][1]['errors']))
            confirm(owner, save(owner, repeated), 422)

            revoke = save(emp, upload(emp, csv_request('撤销前待确认'), project=project))
            owner.delete('/grants/' + grant)
            confirm(emp, revoke, 404)
            emp.get('/imports/' + revoke['id'], 404)
            emp.get('/imports/' + revoke['id'] + '/source', 404)
            t.check('revoked target hidden from list', emp.get('/imports')['batches'], [])
            owner.post('/grants', {'user_id': users['import.employee'], 'kind': 'project', 'resource_id': project})

            concurrent = [t.Client(), t.Client()]
            for c in concurrent:
                c.login('import.owner', 'Synthetic-Owner-2026!')
            a = save(owner, upload(owner, csv_request('并发只创建一次', extra='来源A'), project=project))
            b = save(owner, upload(owner, csv_request('并发只创建一次', extra='来源B'), project=project))
            barrier = threading.Barrier(2)
            def commit(index):
                item = [a, b][index]
                barrier.wait()
                return concurrent[index].call('POST', '/imports/' + item['id'] + '/confirm', {'version': item['version'], 'confirm': True})[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = list(pool.map(commit, [0, 1]))
            t.check('concurrent batches same project serialize before duplicate check', sorted(codes), [200, 422])
            t.check('concurrent duplicate creates one request', sum(r['title'] == '并发只创建一次' for r in requests(owner)), 1)
            a = save(owner, upload(owner, csv_request('同批并发确认'), project=project))
            b = a
            barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = list(pool.map(commit, [0, 1]))
            t.check('same batch concurrent retry returns success twice', sorted(codes), [200, 200])
            t.check('same batch concurrent retry creates one', sum(r['title'] == '同批并发确认' for r in requests(owner)), 1)

            # Restart validates persistence of drafts, original source and idempotency.
            t.stop(process)
            process = t.boot(log)
            persisted = owner.get('/imports/' + a['id'])
            t.check('confirmed batch persisted after restart', persisted['status'], 'confirmed')
            t.check('source hash persisted after restart', persisted['source_sha256'], a['source_sha256'])
            t.check('retry after restart is replay', confirm(owner, a)['replayed'])
            pending = emp.get('/imports/' + revoke['id'])
            t.check('unconfirmed draft persists after restart', pending['status'], 'pending')
            t.check('pending source survives restart', pending['rows'][0]['raw']['需求名称'], '撤销前待确认')
            status = 'passed'
    finally:
        t.stop(process)
        t.REPORT.write_text(json.dumps({'result': status, 'checks': len(t.CHECKS), 'items': t.CHECKS, 'database': str(t.DATABASE), 'log': str(t.LOG)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': status, 'checks': len(t.CHECKS), 'report': str(t.REPORT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
