import json
import logging
import os
import time
from pathlib import Path

from src.config.runtime import cache, database
from src.models.studio import audit
from src.services.correlation import assemble, calculate, leave_one_out
from src.services.directions import arrangement_action, sign, withdraw_note
from src.utils.documents import encode, fingerprint

logger = logging.getLogger(__name__)


def process():
    with database() as cursor:
        cursor.execute('''SELECT id, diagnostic_id, revision, fingerprint, snapshot FROM runs
                          WHERE state='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''')
        task = cursor.fetchone()
        if not task:
            return False
        try:
            snapshot = json.loads(task['snapshot'])
            if fingerprint(snapshot) != task['fingerprint']:
                raise ValueError('snapshot fingerprint mismatch')
            state, result = calculate(snapshot)
            leave_out = None
            if task['revision'] > 0:
                try:
                    leave_out = leave_one_out(snapshot)
                except Exception:
                    logger.exception('Leave-one-out failed for diagnostic %s revision %s',
                                     task['diagnostic_id'], task['revision'])
            pending = Path(f"/exports/.{task['diagnostic_id']}-{task['revision']}.tmp")
            pending.write_text(encode(result), encoding='utf-8')
            os.replace(pending, f"/exports/result-{task['diagnostic_id']}-r{task['revision']}.json")
        except Exception:
            logger.exception('Diagnostic %s revision %s failed', task['diagnostic_id'], task['revision'])
            snapshot, leave_out = None, None
            state, result = 'failed', {'warnings': ['CALCULATION_FAILED']}
        apply(cursor, task, snapshot, state, result, leave_out)
        return True


def apply(cursor, task, snapshot, state, result, leave_out):
    """入账计算结果：只有基于最新数据版本的结果才能更新诊断并驱动复测安排。

    晚算完的旧版本结果仅保留在计算记录里（仍可复算），绝不触碰当前结果与安排，
    因此并发补正时已撤下的安排不会被旧结果恢复。
    """
    cursor.execute('SELECT revision, arrangement, result AS current_result FROM diagnostics WHERE id=%s FOR UPDATE',
                   (task['diagnostic_id'],))
    current = cursor.fetchone()
    if current is None:
        return
    subject = f"{task['diagnostic_id']}#{task['revision']}"
    if task['revision'] > 0 and leave_out is not None:
        reference = None
        if current['current_result']:
            reference = sign(json.loads(current['current_result']).get('partial'))
        result['directions'] = assemble(reference, state, result.get('partial'), leave_out)
    applied = task['revision'] == current['revision']
    cursor.execute('UPDATE runs SET state=%s, result=%s, applied=%s, finished_at=CURRENT_TIMESTAMP WHERE id=%s',
                   (state, encode(result), 1 if applied else 0, task['id']))
    if applied:
        cursor.execute('''UPDATE diagnostics SET state=%s, result=%s, fingerprint=%s, snapshot=%s,
                          finished_at=CURRENT_TIMESTAMP WHERE id=%s''',
                       (state, encode(result), task['fingerprint'], task['snapshot'], task['diagnostic_id']))
        if task['revision'] > 0:
            action = arrangement_action(current['arrangement'],
                                        (result.get('directions') or {}).get('consistent'))
            if action == 'rebase':
                cursor.execute('UPDATE diagnostics SET basis_revision=%s WHERE id=%s',
                               (task['revision'], task['diagnostic_id']))
                audit(cursor, None, 'arrangement.rebase', subject)
            elif action == 'withdraw':
                cursor.execute('''UPDATE diagnostics SET arrangement='withdrawn', withdrawn_at=CURRENT_TIMESTAMP,
                                  withdraw_note=%s WHERE id=%s''',
                               (withdraw_note(result.get('directions')), task['diagnostic_id']))
                audit(cursor, None, 'arrangement.withdraw', subject)
    else:
        audit(cursor, None, 'diagnostic.superseded', subject)
    audit(cursor, None, f'diagnostic.{state}', subject)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            completed = process()
            cache.set('studio:worker:heartbeat', 'ready', ex=12)
            if not completed:
                time.sleep(0.5)
        except Exception:
            logger.exception('Worker dependency unavailable')
            time.sleep(2)


if __name__ == '__main__':
    main()
