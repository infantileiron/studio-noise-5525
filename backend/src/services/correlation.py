import numpy as np

from src.constants.labels import HVAC_RANK
from src.services.directions import consistent, sign

ALGORITHM = 'residual-pearson-v1'


def pearson(x, y):
    if len(x) < 2:
        return None
    left = x - x.mean()
    right = y - y.mean()
    divisor = np.linalg.norm(left) * np.linalg.norm(right)
    return None if divisor == 0 else float(np.clip(left @ right / divisor, -1, 1))


def control_matrix(rows, controls):
    columns = [np.ones(len(rows), dtype=float)]
    labels = ['intercept']
    levels = {}
    for group in controls:
        key = 'session_id' if group == 'session' else group
        values = [str(row[key]) for row in rows]
        categories = sorted(set(values))
        if group == 'hvac':
            categories.sort(key=HVAC_RANK.__getitem__)
        levels[group] = categories
        for category in categories[1:]:
            columns.append(np.array([value == category for value in values], dtype=float))
            labels.append(f'{group}={category}')
    return np.column_stack(columns), labels, levels


def calculate(snapshot):
    rows, method = snapshot['readings'], snapshot['method']
    predictor = method['predictor']
    controls = method['controls']
    x = np.array([row['traffic'] if predictor == 'traffic' else HVAC_RANK[row['hvac']] for row in rows], dtype=float)
    y = np.array([row['noise'] for row in rows], dtype=float)
    raw = pearson(x, y)
    matrix, labels, levels = control_matrix(rows, controls)
    result = {
        'algorithm': ALGORITHM, 'n': len(rows), 'raw': raw, 'partial': None,
        'rows': [{'reference': row['reference'], 'session': row['code'], 'band': row['band'],
                  'x': float(value), 'y': row['noise']} for row, value in zip(rows, x)],
        'columns': labels, 'levels': levels, 'rank': 0, 'df': None, 'warnings': [],
    }
    if len(rows) < 4:
        result['warnings'].append('TOO_FEW_ROWS')
        return 'blocked', result

    measured = np.column_stack((x, y))
    # NumPy's relative cutoff is shared by rank estimation and the least-squares fit.
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, measured, rcond=None)
    result['rank'] = int(rank)
    result['df'] = int(len(rows) - rank - 1)
    absent = [name for name, categories in levels.items() if len(categories) < 2]
    if rank < matrix.shape[1]:
        result['warnings'].append('RANK_DEFICIENT')
    if absent:
        result['warnings'].append('NO_CONTROL_VARIATION')
    if result['df'] < 2:
        result['warnings'].append('LOW_RESIDUAL_DF')
    if result['warnings']:
        return 'blocked', result

    residuals = measured - matrix @ coefficients
    centered_scale = np.maximum(1, np.linalg.norm(measured - measured.mean(axis=0), axis=0))
    if np.any(np.linalg.norm(residuals, axis=0) <= 1e-10 * centered_scale):
        result['warnings'].append('ZERO_RESIDUAL_VARIATION')
        return 'blocked', result

    for point, (left, right) in zip(result['rows'], residuals):
        point.update(rx=float(left), ry=float(right))
    partial = pearson(*residuals.T)
    result['partial'] = partial
    result['absolute_drop'] = abs(raw) - abs(partial)
    return 'complete', result


def leave_one_out(snapshot):
    """逐个剔除时段后按同一口径重算，报告剔除每个时段后的方向。"""
    outcomes = []
    for session in snapshot['sessions']:
        reduced = {**snapshot, 'readings': [row for row in snapshot['readings']
                                            if row['session_id'] != session['id']]}
        state, result = calculate(reduced)
        outcomes.append({'session_id': session['id'], 'code': session['code'],
                         'state': state, 'direction': sign(result.get('partial'))})
    return outcomes


def assemble(reference, state, partial, leave_out):
    """汇总全样本与逐个剔除时段的方向，核对是否都和参照（原诊断）方向一致。"""
    full = sign(partial) if state == 'complete' else None
    return {'reference': reference, 'full': full, 'leave_out': leave_out,
            'consistent': consistent(reference, full, [item['direction'] for item in leave_out])}
