import logging
from pathlib import Path

from fastapi import HTTPException
from pymysql.err import IntegrityError

from src.config.runtime import database
from src.constants.labels import Arrangement, Role
from src.models.studio import METHOD_COLUMNS, READING_SELECT, RUN_COLUMNS, RUN_FROM, audit, decode_json
from src.services.correlation import ALGORITHM, assemble, calculate, leave_one_out
from src.utils.documents import encode, fingerprint

logger = logging.getLogger(__name__)


def build_snapshot(cursor, method_id, session_ids):
    """按当前源数据冻结某组时段的配对样本，供初次诊断与补正重算共用。"""
    cursor.execute(f'SELECT {METHOD_COLUMNS} FROM methods WHERE id=%s', (method_id,))
    method = decode_json(cursor.fetchone(), 'controls')
    if method is None:
        raise HTTPException(404, '找不到变量版本')
    placeholders = ','.join(['%s'] * len(session_ids))
    cursor.execute(f'SELECT id, code FROM sessions WHERE id IN ({placeholders}) ORDER BY id', session_ids)
    selected = cursor.fetchall()
    cursor.execute(READING_SELECT + f' WHERE r.session_id IN ({placeholders}) ORDER BY r.id', session_ids)
    readings = cursor.fetchall()
    return method, {'algorithm': ALGORITHM, 'method': method, 'sessions': selected, 'readings': readings}


def queue(data, account):
    session_ids = sorted(data['session_ids'])
    try:
        with database() as cursor:
            method, snapshot = build_snapshot(cursor, data['method_id'], session_ids)
            if len(snapshot['sessions']) != len(session_ids):
                raise HTTPException(404, '部分测量时段不存在，请重新选择')
            if len(snapshot['readings']) > 4000:
                raise HTTPException(422, '单次诊断最多处理 4000 条声测，请缩小时段范围')
            checksum = fingerprint(snapshot)
            cursor.execute('''INSERT INTO diagnostics(method_id, title, owner_id, fingerprint, snapshot)
                              VALUES (%s,%s,%s,%s,%s)''',
                           (method['id'], data['title'], account['id'], checksum, encode(snapshot)))
            identifier = cursor.lastrowid
            cursor.execute('''INSERT INTO runs(diagnostic_id, revision, fingerprint, snapshot)
                              VALUES (%s,0,%s,%s)''', (identifier, checksum, encode(snapshot)))
            audit(cursor, account['id'], 'diagnostic.queue', str(identifier))
    except IntegrityError as error:
        raise HTTPException(409, '诊断单名称已使用') from error
    return {'id': identifier, 'state': 'queued', 'fingerprint': checksum, 'n': len(snapshot['readings'])}


def list_runs(account):
    scope = " WHERE d.arrangement='active'" if account['role'] == Role.viewer else ''
    columns = RUN_COLUMNS.replace('d.result,', 'NULL AS result,')
    with database() as cursor:
        cursor.execute('SELECT ' + columns + ' ' + RUN_FROM + scope + ' ORDER BY d.id DESC LIMIT 100')
        return cursor.fetchall()


def get_run(identifier, account, snapshot=False):
    scope = " AND d.arrangement='active'" if account['role'] == Role.viewer else ''
    columns = RUN_COLUMNS + (', d.snapshot' if snapshot else '')
    with database() as cursor:
        cursor.execute('SELECT ' + columns + ' ' + RUN_FROM + ' WHERE d.id=%s' + scope, (identifier,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, '找不到可阅诊断单')
        cursor.execute('''SELECT r.revision, r.correction_id, r.state, r.applied, r.created_at, r.finished_at,
                          r.result->'$.directions' AS directions
                          FROM runs r WHERE r.diagnostic_id=%s ORDER BY r.revision DESC''', (identifier,))
        row['runs'] = [{**decode_json(item, 'directions'),
                        'created_at': item['created_at'].isoformat(),
                        'finished_at': item['finished_at'].isoformat() if item['finished_at'] else None}
                       for item in cursor.fetchall()]
    return decode_json(row, 'result', *(['snapshot'] if snapshot else []))


def publish(identifier, text, account):
    with database() as cursor:
        cursor.execute('SELECT state, arrangement FROM diagnostics WHERE id=%s FOR UPDATE', (identifier,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, '找不到诊断单')
        if row['state'] != 'complete':
            raise HTTPException(409, '仅可发布已算完的诊断')
        if row['arrangement'] == Arrangement.active:
            raise HTTPException(409, '复测安排已发布，无需重复发布')
        cursor.execute('''UPDATE diagnostics SET decision=%s, reviewer_id=%s, reviewed_at=CURRENT_TIMESTAMP,
                          arrangement='active', basis_revision=revision, withdrawn_at=NULL, withdraw_note=NULL
                          WHERE id=%s''', (text, account['id'], identifier))
        audit(cursor, account['id'], 'diagnostic.publish', str(identifier))
    return get_run(identifier, account)


def export(identifier, account):
    run = get_run(identifier, account, snapshot=True)
    if run['state'] not in ('complete', 'blocked'):
        raise HTTPException(409, '诊断尚无可导出的计算证据')
    prefix = 'published' if run['reviewed_at'] else 'working'
    path = Path(f'/exports/studio-{identifier}-{prefix}.json')
    document = encode({**run, **{key: run[key].isoformat() if run[key] else None
                                for key in ('created_at', 'finished_at', 'reviewed_at', 'withdrawn_at')}})
    with database() as cursor:
        audit(cursor, account['id'], 'diagnostic.export', str(identifier))
    return path.name, document


def fetch_run(cursor, identifier, revision):
    cursor.execute('''SELECT revision, correction_id, state, fingerprint, snapshot, result, applied,
                      created_at, finished_at FROM runs WHERE diagnostic_id=%s AND revision=%s''',
                   (identifier, revision))
    return decode_json(cursor.fetchone(), 'snapshot', 'result')


def export_run(identifier, revision, account):
    run = get_run(identifier, account)
    with database() as cursor:
        record = fetch_run(cursor, identifier, revision)
        if record is None:
            raise HTTPException(404, '找不到该次计算记录')
        if record['result'] is None:
            raise HTTPException(409, '该次计算尚无结果，无法导出')
        document = encode({
            'diagnostic': {key: run[key] for key in
                           ('id', 'title', 'version', 'predictor', 'revision', 'basis_revision', 'arrangement')},
            'run': {**record, 'created_at': record['created_at'].isoformat(),
                    'finished_at': record['finished_at'].isoformat() if record['finished_at'] else None},
        })
        audit(cursor, account['id'], 'diagnostic.export', f'{identifier}#{revision}')
    return f'studio-{identifier}-r{revision}.json', document


def recheck(identifier, revision, account):
    """复算某次历史计算：快照已冻结，同一算法应得到同一结果。"""
    get_run(identifier, account)
    with database() as cursor:
        record = fetch_run(cursor, identifier, revision)
        if record is None:
            raise HTTPException(404, '找不到该次计算记录')
        if record['result'] is None:
            raise HTTPException(409, '该次计算尚无结果，无法复算')
        snapshot = record['snapshot']
        if fingerprint(snapshot) != record['fingerprint']:
            raise HTTPException(409, '快照指纹不匹配，无法复算')
        state, result = calculate(snapshot)
        stored = record['result']
        if stored.get('directions'):
            result['directions'] = assemble(stored['directions'].get('reference'), state,
                                            result.get('partial'), leave_one_out(snapshot))
        match = state == record['state'] and encode(result) == encode(stored)
        audit(cursor, account['id'], 'diagnostic.recheck', f'{identifier}#{revision}')
    return {'revision': revision, 'match': match, 'state': record['state'],
            'partial': stored.get('partial'), 'recomputed_partial': result.get('partial')}
