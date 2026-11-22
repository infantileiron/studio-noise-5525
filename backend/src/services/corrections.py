import json

from fastapi import HTTPException

from src.config.runtime import database
from src.models.studio import READING_SELECT, audit
from src.services.diagnostics import build_snapshot
from src.utils.documents import encode, fingerprint


def recent(session_id=None):
    sql = '''SELECT c.id, c.reading_id, CAST(c.noise_before AS DOUBLE) AS noise_before,
                    CAST(c.noise_after AS DOUBLE) AS noise_after, c.traffic_before, c.traffic_after,
                    c.reason, c.created_at, r.reference, s.code AS session_code, a.email AS actor
             FROM corrections c
             JOIN readings r ON r.id=c.reading_id
             JOIN sessions s ON s.id=c.session_id
             JOIN accounts a ON a.id=c.actor_id'''
    params = ()
    if session_id is not None:
        sql += ' WHERE c.session_id=%s'
        params = (session_id,)
    with database() as cursor:
        cursor.execute(sql + ' ORDER BY c.id DESC LIMIT 50', params)
        return cursor.fetchall()


def requeue(cursor, session_id, correction_id):
    """包含该时段的诊断全部按当前源数据排队重算；补正与重算快照在同一事务入账。

    先锁定全部相关诊断行再重建快照，使并发补正在诊断行上串行：
    后入账的补正一定拿到更新的数据版本，其快照也包含此前已入账的补正。
    """
    cursor.execute("SELECT id, method_id, snapshot->'$.sessions' AS sessions_json FROM diagnostics FOR UPDATE")
    affected = [(row['id'], row['method_id'], [session['id'] for session in json.loads(row['sessions_json'])])
                for row in cursor.fetchall()]
    affected = [item for item in affected if session_id in item[2]]
    for diagnostic_id, method_id, session_ids in affected:
        cursor.execute("UPDATE diagnostics SET revision=revision+1, state='queued' WHERE id=%s", (diagnostic_id,))
        cursor.execute('SELECT revision FROM diagnostics WHERE id=%s', (diagnostic_id,))
        revision = cursor.fetchone()['revision']
        _, snapshot = build_snapshot(cursor, method_id, session_ids)
        cursor.execute('''INSERT INTO runs(diagnostic_id, revision, correction_id, fingerprint, snapshot)
                          VALUES (%s,%s,%s,%s,%s)''',
                       (diagnostic_id, revision, correction_id, fingerprint(snapshot), encode(snapshot)))
    return len(affected)


def create(data, account):
    changes = {key: data[key] for key in ('noise', 'traffic') if data.get(key) is not None}
    with database() as cursor:
        cursor.execute(READING_SELECT + ' WHERE r.id=%s FOR UPDATE', (data['reading_id'],))
        reading = cursor.fetchone()
        if reading is None:
            raise HTTPException(404, '找不到声测记录')
        changed = {key: value for key, value in changes.items() if value != reading[key]}
        if not changed:
            raise HTTPException(422, '补正值与当前记录相同，无需入账')
        cursor.execute('''INSERT INTO corrections(reading_id, session_id, noise_before, noise_after,
                          traffic_before, traffic_after, reason, actor_id)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                       (reading['id'], reading['session_id'],
                        reading['noise'] if 'noise' in changed else None, changed.get('noise'),
                        reading['traffic'] if 'traffic' in changed else None, changed.get('traffic'),
                        data['reason'], account['id']))
        correction_id = cursor.lastrowid
        assignments = ','.join(f'{key}=%s' for key in changed)
        cursor.execute(f'UPDATE readings SET {assignments} WHERE id=%s', (*changed.values(), reading['id']))
        requeued = requeue(cursor, reading['session_id'], correction_id)
        audit(cursor, account['id'], 'correction.create', reading['reference'])
    return {'id': correction_id, 'reference': reading['reference'], 'changed': changed, 'requeued': requeued}
